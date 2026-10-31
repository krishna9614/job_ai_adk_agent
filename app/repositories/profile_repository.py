import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import UserProfile


class ProfileRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_user_id(self, user_id: uuid.UUID) -> UserProfile | None:
        return self.db.get(UserProfile, user_id)

    def create(self, user_id: uuid.UUID, values: dict[str, Any]) -> UserProfile:
        profile = UserProfile(user_id=user_id, **values)
        self.db.add(profile)
        self.db.flush()
        return profile

    def update(self, profile: UserProfile, values: dict[str, Any]) -> UserProfile:
        for key, value in values.items():
            setattr(profile, key, value)
        self.db.flush()
        return profile
