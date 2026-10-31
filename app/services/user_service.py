from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, ForbiddenError
from app.models import User
from app.repositories.user_repository import UserRepository
from app.services.auth_provider import AuthIdentity

_INACTIVE_STATUSES = {"suspended", "deleted"}


class UserService:
    def __init__(self, db: Session):
        self.db = db
        self.users = UserRepository(db)

    def email_is_registered(self, email: str) -> bool:
        user = self.users.get_by_email(email)
        return user is not None and user.auth_user_id is not None

    def sync_authenticated_user(self, identity: AuthIdentity, *, record_login: bool = False) -> User:
        """Idempotently map a Supabase identity onto ``jobai.users`` (keyed by auth_user_id)."""
        try:
            user = self._get_or_create(identity)
            changes: dict = {}
            if user.email.lower() != identity.email.lower():
                changes["email"] = identity.email
            if identity.email_verified_at and user.email_verified_at is None:
                changes["email_verified_at"] = identity.email_verified_at
            if record_login:
                changes["last_login_at"] = datetime.now(UTC)
            if changes:
                self.users.update(user, changes)
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise ConflictError("An account with this email already exists") from exc
        self.ensure_active(user)
        return user

    def _get_or_create(self, identity: AuthIdentity) -> User:
        user = self.users.get_by_auth_user_id(identity.auth_user_id)
        if user is not None:
            return user
        existing = self.users.get_by_email(identity.email)
        if existing is not None:
            if existing.auth_user_id is not None:
                raise ConflictError("An account with this email already exists")
            # Pre-existing application row without an auth link: attach it.
            return self.users.update(existing, {"auth_user_id": identity.auth_user_id})
        self.users.insert_if_absent(
            auth_user_id=identity.auth_user_id,
            email=identity.email,
            email_verified_at=identity.email_verified_at,
        )
        return self.users.get_by_auth_user_id(identity.auth_user_id)

    @staticmethod
    def ensure_active(user: User) -> None:
        if user.deleted_at is not None or user.account_status in _INACTIVE_STATUSES:
            raise ForbiddenError("Account is not active")
