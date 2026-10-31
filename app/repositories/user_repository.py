import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import User


class UserRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return self.db.get(User, user_id)

    def get_by_auth_user_id(self, auth_user_id: uuid.UUID) -> User | None:
        return self.db.scalar(select(User).where(User.auth_user_id == auth_user_id))

    def get_by_email(self, email: str) -> User | None:
        return self.db.scalar(select(User).where(func.lower(User.email) == email.lower()))

    def insert_if_absent(
        self, *, auth_user_id: uuid.UUID, email: str, email_verified_at: datetime | None
    ) -> None:
        """Race-safe insert keyed on ``auth_user_id`` (no-op if a row already exists)."""
        stmt = (
            insert(User)
            .values(auth_user_id=auth_user_id, email=email, email_verified_at=email_verified_at)
            .on_conflict_do_nothing(index_elements=[User.auth_user_id])
        )
        self.db.execute(stmt)

    def update(self, user: User, values: dict[str, Any]) -> User:
        for key, value in values.items():
            setattr(user, key, value)
        self.db.flush()
        return user
