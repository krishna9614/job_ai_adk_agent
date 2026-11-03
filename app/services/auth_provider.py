"""Identity-provider abstraction. Supabase Auth owns credentials; we never store passwords."""

import logging
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

import httpx
from supabase import Client, create_client
from supabase.lib.client_options import SyncClientOptions
from supabase_auth.errors import AuthApiError, AuthError
from supabase_auth.helpers import parse_auth_response

from app.core.errors import (
    AuthenticationError,
    AuthProviderUnavailableError,
    ConflictError,
    ForbiddenError,
    InvalidTokenError,
    PasswordReusedError,
    RateLimitedError,
    ValidationFailedError,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuthIdentity:
    auth_user_id: uuid.UUID
    email: str
    email_verified_at: datetime | None = None
    # Authentication methods from the token's `amr` claim (e.g. "password", "otp", "recovery").
    auth_methods: tuple[str, ...] = ()


@dataclass(frozen=True)
class AuthSession:
    access_token: str
    refresh_token: str | None
    expires_in: int | None
    token_type: str = "bearer"


@dataclass(frozen=True)
class AuthResult:
    identity: AuthIdentity
    session: AuthSession | None


EmailTokenType = Literal["signup", "email", "email_change", "recovery"]


class AuthProvider(Protocol):
    def sign_up(self, email: str, password: str, *, full_name: str | None = None) -> AuthResult: ...

    def sign_in(self, email: str, password: str) -> AuthResult: ...

    def refresh(self, refresh_token: str) -> AuthResult: ...

    def sign_out(self, access_token: str, scope: Literal["global", "local", "others"]) -> None: ...

    def verify_access_token(self, token: str) -> AuthIdentity:
        """Return the identity for a valid access token or raise AuthenticationError."""
        ...

    def send_password_reset(self, email: str) -> None: ...

    def resend_signup_confirmation(self, email: str) -> None: ...

    def verify_email_token(self, token_hash: str, token_type: EmailTokenType) -> AuthResult | None:
        """Consume a one-time email link token; session is None while an email change is half-done."""
        ...

    def update_password(self, access_token: str, password: str) -> None: ...

    def request_email_change(self, access_token: str, email: str) -> None: ...


_SIGNUP_CONFLICT_CODES = {"user_already_exists", "email_exists"}
_RATE_LIMIT_CODES = {"over_request_rate_limit", "over_email_send_rate_limit"}
_VALIDATION_CODES = {"weak_password", "email_address_invalid", "validation_failed"}
_INVALID_LINK_MESSAGE = "This link is invalid, has expired or has already been used"


def _unreachable(exc: httpx.HTTPError) -> AuthProviderUnavailableError:
    """Network failure talking to Supabase (DNS, TLS handshake, timeout): a 503, never a 500."""
    logger.warning("Supabase Auth unreachable: %s: %s", type(exc).__name__, exc)
    return AuthProviderUnavailableError(
        "Couldn't reach the authentication service. Check your connection and try again."
    )


class SupabaseAuthProvider:
    """Supabase Auth via the public (anon/publishable) key."""

    def __init__(self, url: str, anon_key: str):
        self._url = url
        self._anon_key = anon_key
        # Long-lived client used only for stateless token verification (caches JWKS).
        self._verifier = self._new_client()
        self._verifier_lock = threading.Lock()

    def _new_client(self) -> Client:
        # A fresh client per sign-up/sign-in keeps per-user sessions out of shared state.
        return create_client(
            self._url,
            self._anon_key,
            options=SyncClientOptions(auto_refresh_token=False, persist_session=False),
        )

    def sign_up(self, email: str, password: str, *, full_name: str | None = None) -> AuthResult:
        credentials: dict = {"email": email, "password": password}
        if full_name:
            credentials["options"] = {"data": {"full_name": full_name}}
        try:
            resp = self._new_client().auth.sign_up(credentials)
        except AuthApiError as exc:
            raise self._map_error(exc, conflict_codes=_SIGNUP_CONFLICT_CODES) from exc
        except AuthError as exc:
            raise AuthProviderUnavailableError("Authentication service error") from exc
        except httpx.HTTPError as exc:
            raise _unreachable(exc) from exc
        user = resp.user
        # With email confirmation enabled, Supabase hides existing accounts by returning
        # a user with no identities instead of an error.
        if user is None or (user.identities is not None and len(user.identities) == 0):
            raise ConflictError("An account with this email already exists")
        return AuthResult(identity=self._identity(user), session=self._session(resp.session))

    def sign_in(self, email: str, password: str) -> AuthResult:
        try:
            resp = self._new_client().auth.sign_in_with_password(
                {"email": email, "password": password}
            )
        except AuthApiError as exc:
            raise self._map_error(exc) from exc
        except AuthError as exc:
            raise AuthProviderUnavailableError("Authentication service error") from exc
        except httpx.HTTPError as exc:
            raise _unreachable(exc) from exc
        if resp.user is None or resp.session is None:
            raise AuthenticationError("Invalid email or password")
        return AuthResult(identity=self._identity(resp.user), session=self._session(resp.session))

    def refresh(self, refresh_token: str) -> AuthResult:
        try:
            resp = self._new_client().auth.refresh_session(refresh_token)
        except AuthApiError as exc:
            if exc.status and exc.status >= 500:
                raise AuthProviderUnavailableError("Authentication service error") from exc
            raise AuthenticationError("Session has expired, please log in again") from exc
        except AuthError as exc:
            raise AuthenticationError("Session has expired, please log in again") from exc
        except httpx.HTTPError as exc:
            raise _unreachable(exc) from exc
        if resp.user is None or resp.session is None:
            raise AuthenticationError("Session has expired, please log in again")
        return AuthResult(identity=self._identity(resp.user), session=self._session(resp.session))

    def sign_out(self, access_token: str, scope: Literal["global", "local", "others"]) -> None:
        """Revoke refresh tokens (this session, or every session for "global")."""
        try:
            self._new_client().auth.admin.sign_out(access_token, scope)
        except AuthApiError as exc:
            if exc.status and exc.status >= 500:
                raise AuthProviderUnavailableError("Authentication service error") from exc
            # Already signed out / expired token: nothing left to revoke.
            logger.info("sign_out ignored: status=%s code=%s", exc.status, exc.code)
        except httpx.HTTPError as exc:
            raise _unreachable(exc) from exc

    def send_password_reset(self, email: str) -> None:
        try:
            self._new_client().auth.reset_password_for_email(email)
        except AuthApiError as exc:
            raise self._map_error(exc) from exc
        except AuthError as exc:
            raise AuthProviderUnavailableError("Authentication service error") from exc
        except httpx.HTTPError as exc:
            raise _unreachable(exc) from exc

    def resend_signup_confirmation(self, email: str) -> None:
        try:
            self._new_client().auth.resend({"type": "signup", "email": email})
        except AuthApiError as exc:
            raise self._map_error(exc) from exc
        except AuthError as exc:
            raise AuthProviderUnavailableError("Authentication service error") from exc
        except httpx.HTTPError as exc:
            raise _unreachable(exc) from exc

    def verify_email_token(self, token_hash: str, token_type: EmailTokenType) -> AuthResult | None:
        # Called over REST: supabase-py cannot parse GoTrue's reply to the first half of a
        # double-confirmed email change (a message without a user or session).
        resp, body = self._gotrue("POST", "verify", {"token_hash": token_hash, "type": token_type})
        if resp.status_code >= 500:
            raise AuthProviderUnavailableError("Authentication service error")
        if resp.status_code == 429:
            raise RateLimitedError("Too many requests, try again later")
        if not resp.is_success:
            raise InvalidTokenError(_INVALID_LINK_MESSAGE)
        if not body.get("access_token"):
            # Double-confirm email change: this address is confirmed, the other one is still pending.
            return None
        parsed = parse_auth_response(resp)
        return AuthResult(identity=self._identity(parsed.user), session=self._session(parsed.session))

    def update_password(self, access_token: str, password: str) -> None:
        self._update_user(access_token, {"password": password})

    def request_email_change(self, access_token: str, email: str) -> None:
        self._update_user(access_token, {"email": email})

    def _update_user(self, access_token: str, attributes: dict) -> None:
        # GoTrue's PUT /user authorised by the caller's own access token (no service-role key).
        resp, body = self._gotrue("PUT", "user", attributes, access_token)
        if resp.is_success:
            return
        code = body.get("error_code") or body.get("code")
        message = body.get("msg") or body.get("message") or body.get("error_description") or "Request failed"
        exc = AuthApiError(message, resp.status_code, code if isinstance(code, str) else None)
        if exc.code == "same_password":
            raise PasswordReusedError("Your new password must be different from your current password")
        if exc.code in {"email_exists", "user_already_exists"}:
            raise ConflictError("An account with this email already exists")
        if resp.status_code in (401, 403) and exc.code not in _VALIDATION_CODES:
            raise AuthenticationError("Invalid or expired access token")
        raise self._map_error(exc)

    def _gotrue(
        self, method: str, path: str, payload: dict, access_token: str | None = None
    ) -> tuple[httpx.Response, dict]:
        headers = {"apikey": self._anon_key}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        try:
            resp = httpx.request(
                method,
                f"{self._url.rstrip('/')}/auth/v1/{path}",
                json=payload,
                headers=headers,
                timeout=15,
            )
        except httpx.HTTPError as exc:
            raise _unreachable(exc) from exc
        try:
            body = resp.json()
        except ValueError:
            body = {}
        return resp, body if isinstance(body, dict) else {}

    def verify_access_token(self, token: str) -> AuthIdentity:
        try:
            with self._verifier_lock:
                resp = self._verifier.auth.get_claims(jwt=token)
        except AuthApiError as exc:
            if exc.status and exc.status >= 500:
                raise AuthProviderUnavailableError("Authentication service error") from exc
            raise AuthenticationError("Invalid or expired access token") from exc
        except AuthError as exc:
            raise AuthenticationError("Invalid or expired access token") from exc
        except httpx.HTTPError as exc:  # JWKS / Auth server unreachable: not the token's fault
            raise _unreachable(exc) from exc
        except Exception as exc:  # malformed tokens raise non-auth exceptions while decoding
            logger.debug("token verification failed: %s", exc)
            raise AuthenticationError("Invalid or expired access token") from exc
        if resp is None:
            raise AuthenticationError("Invalid or expired access token")
        claims = resp["claims"] if isinstance(resp, dict) else resp.claims
        if claims.get("role") != "authenticated" or not claims.get("sub") or not claims.get("email"):
            raise AuthenticationError("Invalid or expired access token")
        try:
            auth_user_id = uuid.UUID(str(claims["sub"]))
        except ValueError as exc:
            raise AuthenticationError("Invalid or expired access token") from exc
        amr = claims.get("amr") or []
        methods = tuple(
            str(entry.get("method")) if isinstance(entry, dict) else str(entry) for entry in amr
        )
        return AuthIdentity(auth_user_id=auth_user_id, email=claims["email"], auth_methods=methods)

    @staticmethod
    def _identity(user) -> AuthIdentity:
        return AuthIdentity(
            auth_user_id=uuid.UUID(str(user.id)),
            email=user.email,
            email_verified_at=user.email_confirmed_at,
        )

    @staticmethod
    def _session(session) -> AuthSession | None:
        if session is None:
            return None
        return AuthSession(
            access_token=session.access_token,
            refresh_token=session.refresh_token,
            expires_in=session.expires_in,
            token_type=session.token_type or "bearer",
        )

    @staticmethod
    def _map_error(exc: AuthApiError, conflict_codes: set[str] = frozenset()) -> Exception:
        code = exc.code or ""
        if code in conflict_codes:
            return ConflictError("An account with this email already exists")
        if code == "invalid_credentials":
            return AuthenticationError("Invalid email or password")
        if code == "email_not_confirmed":
            return ForbiddenError("Email address has not been confirmed")
        if code in _RATE_LIMIT_CODES or exc.status == 429:
            return RateLimitedError("Too many requests, try again later")
        if code in _VALIDATION_CODES or exc.status in (400, 422):
            return ValidationFailedError(exc.message)
        logger.warning("unexpected Supabase auth error: status=%s code=%s", exc.status, code)
        return AuthProviderUnavailableError("Authentication service error")
