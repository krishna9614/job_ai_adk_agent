"""Identity-provider abstraction. Supabase Auth owns credentials; we never store passwords."""

import logging
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from supabase import Client, create_client
from supabase.lib.client_options import SyncClientOptions
from supabase_auth.errors import AuthApiError, AuthError

from app.core.errors import (
    AuthenticationError,
    AuthProviderUnavailableError,
    ConflictError,
    ForbiddenError,
    RateLimitedError,
    ValidationFailedError,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuthIdentity:
    auth_user_id: uuid.UUID
    email: str
    email_verified_at: datetime | None = None


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


class AuthProvider(Protocol):
    def sign_up(self, email: str, password: str) -> AuthResult: ...

    def sign_in(self, email: str, password: str) -> AuthResult: ...

    def verify_access_token(self, token: str) -> AuthIdentity:
        """Return the identity for a valid access token or raise AuthenticationError."""
        ...


_SIGNUP_CONFLICT_CODES = {"user_already_exists", "email_exists"}
_RATE_LIMIT_CODES = {"over_request_rate_limit", "over_email_send_rate_limit"}
_VALIDATION_CODES = {"weak_password", "email_address_invalid", "validation_failed"}


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

    def sign_up(self, email: str, password: str) -> AuthResult:
        try:
            resp = self._new_client().auth.sign_up({"email": email, "password": password})
        except AuthApiError as exc:
            raise self._map_error(exc, conflict_codes=_SIGNUP_CONFLICT_CODES) from exc
        except AuthError as exc:
            raise AuthProviderUnavailableError("Authentication service error") from exc
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
        if resp.user is None or resp.session is None:
            raise AuthenticationError("Invalid email or password")
        return AuthResult(identity=self._identity(resp.user), session=self._session(resp.session))

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
        return AuthIdentity(auth_user_id=auth_user_id, email=claims["email"])

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
