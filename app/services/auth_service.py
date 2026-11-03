import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.errors import (
    AppError,
    AuthenticationError,
    AuthProviderUnavailableError,
    ConflictError,
    ForbiddenError,
    InvalidTokenError,
    ValidationFailedError,
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

    def request_password_reset(self, email: str) -> None:
        """Always succeeds from the caller's view so responses never reveal registered emails."""
        self._quietly(lambda: self.provider.send_password_reset(email), "password reset")

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

    def start_password_recovery(self, token_hash: str) -> AuthSession:
        """Exchange a one-time recovery link for a short-lived session used only to set a password."""
        result = self.provider.verify_email_token(token_hash, "recovery")
        if result is None or result.session is None:
            raise InvalidTokenError("This link is invalid, has expired or has already been used")
        self.user_service.sync_authenticated_user(result.identity)
        return result.session

    def reset_password(self, recovery_token: str, password: str) -> None:
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
