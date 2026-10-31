import uuid
from datetime import UTC, datetime

from app.core.errors import AuthenticationError, ConflictError
from app.services.auth_provider import AuthIdentity, AuthResult, AuthSession


class FakeAuthProvider:
    """In-memory stand-in for Supabase Auth (passwords never reach our database)."""

    def __init__(self) -> None:
        self._accounts: dict[str, tuple[uuid.UUID, str]] = {}
        self._tokens: dict[str, AuthIdentity] = {}

    def _issue(self, identity: AuthIdentity) -> AuthSession:
        token = f"fake-access-{uuid.uuid4()}"
        self._tokens[token] = identity
        return AuthSession(access_token=token, refresh_token="fake-refresh", expires_in=3600)

    def sign_up(self, email: str, password: str) -> AuthResult:
        key = email.lower()
        if key in self._accounts:
            raise ConflictError("An account with this email already exists")
        auth_id = uuid.uuid4()
        self._accounts[key] = (auth_id, password)
        identity = AuthIdentity(auth_id, email, email_verified_at=datetime.now(UTC))
        return AuthResult(identity=identity, session=self._issue(identity))

    def sign_in(self, email: str, password: str) -> AuthResult:
        account = self._accounts.get(email.lower())
        if account is None or account[1] != password:
            raise AuthenticationError("Invalid email or password")
        identity = AuthIdentity(account[0], email)
        return AuthResult(identity=identity, session=self._issue(identity))

    def verify_access_token(self, token: str) -> AuthIdentity:
        identity = self._tokens.get(token)
        if identity is None:
            raise AuthenticationError("Invalid or expired access token")
        return identity
