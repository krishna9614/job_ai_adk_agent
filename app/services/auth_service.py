import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import (
    AppError,
    AuthenticationError,
    AuthProviderUnavailableError,
    ConflictError,
    ForbiddenError,
    InvalidTokenError,
    RecoveryStateError,
    ValidationFailedError,
)
from app.core.recovery_tokens import (
    new_pkce_pair,
    open_recovery_state,
    open_recovery_token,
    seal_recovery_state,
    seal_recovery_token,
)
from app.models import User
from app.repositories.profile_repository import ProfileRepository
from app.schemas.auth import split_full_name
from app.services.auth_provider import AuthProvider, AuthSession, EmailTokenType
from app.services.user_service import UserService

logger = logging.getLogger(__name__)

# `amr` methods of sessions created from an emailed one-time link (Supabase records "otp" for
# recovery links); password logins ("password") cannot set a password without the old one.
_EMAIL_LINK_METHODS = {"recovery", "otp"}


def _reset_redirect_url() -> str | None:
    frontend_url = get_settings().frontend_url
    return f"{frontend_url.rstrip('/')}/reset-password" if frontend_url else None


@dataclass(frozen=True)
class AuthOutcome:
    user: User | None
    session: AuthSession | None


class AuthService:
    def __init__(self, db: Session, provider: AuthProvider):
        self.db = db
        self.provider = provider
        self.user_service = UserService(db)
        self.profiles = ProfileRepository(db)

    def sign_up(self, email: str, password: str, full_name: str) -> AuthOutcome:
        if self.user_service.email_is_registered(email):
            raise ConflictError("An account with this email already exists")
        result = self.provider.sign_up(email, password, full_name=full_name)
        user = self.user_service.sync_authenticated_user(
            result.identity, record_login=result.session is not None
        )
        self._ensure_profile_name(user, full_name)
        return AuthOutcome(user=user, session=result.session)

    def sign_in(self, email: str, password: str) -> AuthOutcome:
        result = self.provider.sign_in(email, password)
        if result.session is None:
            raise AuthenticationError("Invalid email or password")
        user = self.user_service.sync_authenticated_user(result.identity, record_login=True)
        return AuthOutcome(user=user, session=result.session)

    def refresh(self, refresh_token: str) -> AuthOutcome:
        result = self.provider.refresh(refresh_token)
        user = self.user_service.sync_authenticated_user(result.identity)
        return AuthOutcome(user=user, session=result.session)

    def sign_out(self, access_token: str) -> None:
        self.provider.sign_out(access_token, "local")

    def authenticate_token(self, token: str) -> User:
        identity = self.provider.verify_access_token(token)
        return self.user_service.sync_authenticated_user(identity)

    # Email links -----------------------------------------------------------------------------

    def request_password_reset(self, email: str) -> str:
        """Send a PKCE reset email and return the sealed verifier (recovery state).

        Always succeeds from the caller's view, and the state is returned for unknown emails too,
        so responses never reveal registered emails.
        """
        verifier, challenge = new_pkce_pair()
        redirect_to = _reset_redirect_url()
        self._quietly(
            lambda: self.provider.send_password_reset(email, redirect_to=redirect_to, code_challenge=challenge),
            "password reset",
        )
        return seal_recovery_state(verifier)

    def resend_verification(self, email: str) -> None:
        self._quietly(lambda: self.provider.resend_signup_confirmation(email), "verification resend")

    def confirm_email(self, token_hash: str, token_type: EmailTokenType) -> AuthOutcome:
        result = self.provider.verify_email_token(token_hash, token_type)
        if result is None:
            return AuthOutcome(user=None, session=None)
        user = self.user_service.sync_authenticated_user(
            result.identity, record_login=result.session is not None
        )
        return AuthOutcome(user=user, session=result.session)

    def start_password_recovery(
        self, token_hash: str | None = None, *, code: str | None = None, recovery_state: str | None = None
    ) -> str:
        """Exchange a one-time recovery link for a sealed 15-minute ticket that can only set a password.

        `token_hash` comes from a custom email template; `code` from Supabase's default template
        (PKCE), which also needs the recovery state of the browser that asked for the email. The
        Supabase recovery session stays inside the backend, so it can never call other endpoints.
        """
        if code is not None:
            verifier = open_recovery_state(recovery_state) if recovery_state else None
            if verifier is None:
                raise RecoveryStateError(
                    "Open the reset link in the same browser you used to request it, or request a new link."
                )
            result = self.provider.exchange_recovery_code(code, verifier)
        elif token_hash is not None:
            result = self.provider.verify_email_token(token_hash, "recovery")
        else:
            raise InvalidTokenError("This link is invalid, has expired or has already been used")
        if result is None or result.session is None:
            raise InvalidTokenError("This link is invalid, has expired or has already been used")
        self.user_service.sync_authenticated_user(result.identity)
        return seal_recovery_token(result.session.access_token)

    def reset_password(self, recovery_ticket: str, password: str) -> None:
        recovery_token = open_recovery_token(recovery_ticket)
        if recovery_token is None:
            raise AuthenticationError("Your reset session has expired. Please request a new reset link.")
        identity = self.provider.verify_access_token(recovery_token)
        if not _EMAIL_LINK_METHODS.intersection(identity.auth_methods):
            raise ForbiddenError("Open the password reset link from your email to set a new password")
        self.user_service.sync_authenticated_user(identity)
        # Supabase hashes the password and rejects one equal to the current password.
        self.provider.update_password(recovery_token, password)
        # Revoke every refresh token (all devices, including this recovery session).
        self.provider.sign_out(recovery_token, "global")

    def request_email_change(self, access_token: str, user: User, new_email: str) -> None:
        if new_email.lower() == user.email.lower():
            raise ValidationFailedError("This is already your email address")
        if self.user_service.email_is_registered(new_email):
            raise ConflictError("An account with this email already exists")
        self.provider.request_email_change(access_token, new_email)

    # Helpers ---------------------------------------------------------------------------------

    def _ensure_profile_name(self, user: User, full_name: str) -> None:
        if self.profiles.get_by_user_id(user.id) is not None:
            return
        first, middle, last = split_full_name(full_name)
        self.profiles.create(user.id, {"first_name": first, "middle_name": middle, "last_name": last})
        self.db.commit()

    @staticmethod
    def _quietly(action, label: str) -> None:
        try:
            action()
        except AuthProviderUnavailableError:
            raise
        except AppError as exc:
            logger.info("%s request not sent: %s (%s)", label, exc.code, exc.message)
