"""Profile business logic. This is the single implementation reused by REST and MCP callers."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.models import User, UserProfile
from app.repositories.profile_repository import ProfileRepository
from app.schemas.profile import ProfileCreate, ProfileUpdate


class ProfileService:
    def __init__(self, db: Session):
        self.db = db
        self.profiles = ProfileRepository(db)

    def get_profile(self, user: User) -> UserProfile:
        profile = self.profiles.get_by_user_id(user.id)
        if profile is None:
            raise NotFoundError("Profile not found")
        return profile

    def create_profile(self, user: User, data: ProfileCreate) -> UserProfile:
        if self.profiles.get_by_user_id(user.id) is not None:
            raise ConflictError("Profile already exists")
        try:
            profile = self.profiles.create(user.id, data.model_dump())
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise ConflictError("Profile already exists") from exc
        self.db.refresh(profile)
        return profile

    def update_profile(self, user: User, data: ProfileUpdate) -> UserProfile:
        profile = self.get_profile(user)
        self.profiles.update(profile, data.model_dump(exclude_unset=True))
        self.db.commit()
        self.db.refresh(profile)
        return profile
