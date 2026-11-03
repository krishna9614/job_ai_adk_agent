import secrets
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

from app.core.errors import (
    AuthenticationError,
    ConflictError,
    InvalidTokenError,
    PasswordReusedError,
)
from app.services.auth_provider import AuthIdentity, AuthResult, AuthSession


@dataclass
class _Account:
    auth_id: uuid.UUID
    email: str
    password: str  # in-memory test double only; the real provider is Supabase Auth
    confirmed: bool = True
    metadata: dict = field(default_factory=dict)


@dataclass
class SentEmail:
    type: str
    to: str
    token_hash: str


class FakeAuthProvider:
    """In-memory stand-in for Supabase Auth (passwords never reach our database)."""

    def __init__(self, *, confirm_email: bool = False) -> None:
        self.confirm_email = confirm_email
        self._accounts: dict[str, _Account] = {}
        self._tokens: dict[str, tuple[AuthIdentity, str]] = {}  # access -> (identity, refresh)
        self._refresh: dict[str, uuid.UUID] = {}
        self._email_tokens: dict[str, tuple[str, uuid.UUID, str, datetime]] = {}
        self.outbox: list[SentEmail] = []

    # Helpers for tests -----------------------------------------------------------------------

    def account(self, email: str) -> _Account | None:
        return self._accounts.get(email.lower())

    def last_email(self, type_: str) -> SentEmail:
        return next(m for m in reversed(self.outbox) if m.type == type_)

    def expire_email_tokens(self) -> None:
        for key, (t, aid, email, _) in self._email_tokens.items():
            self._email_tokens[key] = (t, aid, email, datetime.now(UTC) - timedelta(seconds=1))

    # Provider API ----------------------------------------------------------------------------

    def _issue(self, account: _Account, methods: tuple[str, ...] = ("password",)) -> AuthSession:
        token = f"fake-access-{uuid.uuid4()}"
        refresh = f"fake-refresh-{uuid.uuid4()}"
        identity = AuthIdentity(account.auth_id, account.email, auth_methods=methods)
        self._tokens[token] = (identity, refresh)
        self._refresh[refresh] = account.auth_id
        return AuthSession(access_token=token, refresh_token=refresh, expires_in=3600)

    def _by_id(self, auth_id: uuid.UUID) -> _Account:
        return next(a for a in self._accounts.values() if a.auth_id == auth_id)

    def _send(self, type_: str, account: _Account, to: str) -> None:
        token_hash = secrets.token_hex(16)
        self._email_tokens[token_hash] = (type_, account.auth_id, to, datetime.now(UTC) + timedelta(hours=1))
        self.outbox.append(SentEmail(type_, to, token_hash))

    def sign_up(self, email: str, password: str, *, full_name: str | None = None) -> AuthResult:
        key = email.lower()
        if key in self._accounts:
            raise ConflictError("An account with this email already exists")
        account = _Account(uuid.uuid4(), email, password, confirmed=not self.confirm_email)
        account.metadata["full_name"] = full_name
        self._accounts[key] = account
        verified = datetime.now(UTC) if account.confirmed else None
        identity = AuthIdentity(account.auth_id, email, email_verified_at=verified)
        if not account.confirmed:
            self._send("signup", account, email)
            return AuthResult(identity=identity, session=None)
        return AuthResult(identity=identity, session=self._issue(account))

    def sign_in(self, email: str, password: str) -> AuthResult:
        account = self._accounts.get(email.lower())
        if account is None or account.password != password:
            raise AuthenticationError("Invalid email or password")
        if not account.confirmed:
            from app.core.errors import ForbiddenError

            raise ForbiddenError("Email address has not been confirmed")
        identity = AuthIdentity(account.auth_id, account.email)
        return AuthResult(identity=identity, session=self._issue(account))

    def refresh(self, refresh_token: str) -> AuthResult:
        auth_id = self._refresh.pop(refresh_token, None)
        if auth_id is None:
            raise AuthenticationError("Session has expired, please log in again")
        account = self._by_id(auth_id)
        return AuthResult(identity=AuthIdentity(auth_id, account.email), session=self._issue(account))

    def sign_out(self, access_token: str, scope: str) -> None:
        entry = self._tokens.get(access_token)
        if entry is None:
            return
        identity, refresh = entry
        if scope == "global":
            for token, (ident, ref) in list(self._tokens.items()):
                if ident.auth_user_id == identity.auth_user_id:
                    self._tokens.pop(token)
                    self._refresh.pop(ref, None)
        else:
            self._tokens.pop(access_token)
            self._refresh.pop(refresh, None)

    def verify_access_token(self, token: str) -> AuthIdentity:
        entry = self._tokens.get(token)
        if entry is None:
            raise AuthenticationError("Invalid or expired access token")
        return entry[0]

    def send_password_reset(self, email: str) -> None:
        account = self._accounts.get(email.lower())
        if account is not None:
            self._send("recovery", account, account.email)

    def resend_signup_confirmation(self, email: str) -> None:
        account = self._accounts.get(email.lower())
        if account is not None and not account.confirmed:
            self._send("signup", account, account.email)

    def verify_email_token(self, token_hash: str, token_type: str) -> AuthResult | None:
        entry = self._email_tokens.pop(token_hash, None)
        expected = {"email": "signup"}.get(token_type, token_type)
        if entry is None or entry[0] != expected or entry[3] < datetime.now(UTC):
            raise InvalidTokenError("This link is invalid, has expired or has already been used")
        _, auth_id, address, _ = entry
        account = self._by_id(auth_id)
        if token_type == "email_change":
            self._accounts.pop(account.email.lower())
            account.email = address
            self._accounts[address.lower()] = account
        account.confirmed = True
        methods = ("recovery",) if token_type == "recovery" else ("otp",)
        session = self._issue(account, methods)
        identity = replace(self._tokens[session.access_token][0], email_verified_at=datetime.now(UTC))
        return AuthResult(identity=identity, session=session)

    def update_password(self, access_token: str, password: str) -> None:
        account = self._by_id(self.verify_access_token(access_token).auth_user_id)
        if account.password == password:
            raise PasswordReusedError("Your new password must be different from your current password")
        account.password = password

    def request_email_change(self, access_token: str, email: str) -> None:
        account = self._by_id(self.verify_access_token(access_token).auth_user_id)
        if email.lower() in self._accounts:
            raise ConflictError("An account with this email already exists")
        self._send("email_change", account, email)
