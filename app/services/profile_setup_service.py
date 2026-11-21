"""Profile-setup business logic (preferences, experience, skills, education, certifications,
languages, onboarding progress). Ownership always comes from the authenticated ``User``."""

import uuid
from datetime import date
from typing import Any, TypeVar

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.models import (
    EducationLevel,
    JobPreferences,
    Skill,
    User,
    UserCertification,
    UserEducation,
    UserExperience,
    UserLanguage,
    UserSkill,
)
from app.schemas.profile_setup import (
    CertificationList,
    EducationList,
    EducationRead,
    ExperienceList,
    LanguageList,
    OnboardingUpdate,
    PreferencesRead,
    PreferencesUpdate,
    SkillList,
    SkillRead,
)

Row = TypeVar("Row", UserExperience, UserEducation, UserCertification, UserLanguage)


class ProfileSetupService:
    def __init__(self, db: Session):
        self.db = db

    # Preferences -----------------------------------------------------------------------------

    def get_preferences(self, user: User) -> PreferencesRead:
        prefs = self.db.get(JobPreferences, user.id)
        return PreferencesRead.model_validate(prefs) if prefs else PreferencesRead()

    def update_preferences(self, user: User, data: PreferencesUpdate) -> PreferencesRead:
        prefs = self.db.get(JobPreferences, user.id)
        if prefs is None:
            prefs = JobPreferences(user_id=user.id)
            self.db.add(prefs)
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(prefs, key, value)
        low, high = prefs.minimum_salary, prefs.maximum_salary
        if low is not None and high is not None and low > high:
            raise ValidationFailedError("Minimum salary must not exceed the maximum salary")
        if (low is not None or high is not None) and not (prefs.salary_currency and prefs.salary_period):
            raise ValidationFailedError("Salary needs a currency and a period")
        self._commit()
        self.db.refresh(prefs)
        return PreferencesRead.model_validate(prefs)

    # Ordered lists ---------------------------------------------------------------------------

    def list_experience(self, user: User) -> list[UserExperience]:
        return self._list(UserExperience, user)

    def replace_experience(self, user: User, data: ExperienceList) -> list[UserExperience]:
        return self._replace(UserExperience, user, [i.model_dump() for i in data.items])

    def list_certifications(self, user: User) -> list[UserCertification]:
        return self._list(UserCertification, user)

    def replace_certifications(self, user: User, data: CertificationList) -> list[UserCertification]:
        return self._replace(UserCertification, user, [i.model_dump() for i in data.items])

    def list_languages(self, user: User) -> list[UserLanguage]:
        return self._list(UserLanguage, user)

    def replace_languages(self, user: User, data: LanguageList) -> list[UserLanguage]:
        return self._replace(UserLanguage, user, [i.model_dump() for i in data.items])

    def list_education(self, user: User) -> list[EducationRead]:
        return [self._education_read(e) for e in self._list(UserEducation, user)]

    def replace_education(self, user: User, data: EducationList) -> list[EducationRead]:
        levels = dict(
            self.db.execute(
                select(EducationLevel.code, EducationLevel.id).where(EducationLevel.is_active)
            ).all()
        )
        rows = []
        for item in data.items:
            if item.education_level not in levels:
                raise ValidationFailedError(f"Unknown education level: {item.education_level}")
            rows.append(
                {
                    "id": item.id,
                    "education_level_id": levels[item.education_level],
                    "degree_name": item.degree_name,
                    "institution_name": item.institution_name,
                    "start_date": date(item.start_year, 1, 1) if item.start_year else None,
                    "graduation_year": item.end_year,
                    "is_currently_studying": item.is_currently_studying,
                    "education_status": "pursuing" if item.is_currently_studying else "completed",
                }
            )
        saved = self._replace(UserEducation, user, rows)
        return [self._education_read(e) for e in saved]

    @staticmethod
    def _education_read(row: UserEducation) -> EducationRead:
        return EducationRead(
            id=row.id,
            education_level=row.level.code,
            degree_name=row.degree_name,
            institution_name=row.institution_name,
            start_year=row.start_date.year if row.start_date else None,
            end_year=row.graduation_year,
            is_currently_studying=row.is_currently_studying,
        )

    def _list(self, model: type[Row], user: User) -> list[Row]:
        return list(
            self.db.scalars(
                select(model)
                .where(model.user_id == user.id)
                .order_by(model.display_order, model.created_at)
            )
        )

    def _replace(self, model: type[Row], user: User, items: list[dict[str, Any]]) -> list[Row]:
        existing = {row.id: row for row in self._list(model, user)}
        kept: set[uuid.UUID] = {i["id"] for i in items if i.get("id") is not None}
        unknown = kept - existing.keys()
        if unknown:
            raise NotFoundError("One or more items were not found")
        for row_id, row in existing.items():
            if row_id not in kept:
                self.db.delete(row)
        self.db.flush()  # deletes first, so re-added unique values (e.g. a language) don't clash

        for order, values in enumerate(items):
            row_id = values.pop("id", None)
            if row_id is None:
                self.db.add(model(user_id=user.id, display_order=order, **values))
            else:
                row = existing[row_id]
                for key, value in values.items():
                    setattr(row, key, value)
                row.display_order = order
        self._commit()
        return self._list(model, user)

    # Skills ----------------------------------------------------------------------------------

    def list_skills(self, user: User) -> list[SkillRead]:
        rows = self.db.scalars(
            select(UserSkill)
            .join(UserSkill.skill)
            .where(UserSkill.user_id == user.id)
            .order_by(func.lower(Skill.canonical_name))
        )
        return [SkillRead(name=r.skill.canonical_name, category=r.skill.category) for r in rows]

    def replace_skills(self, user: User, data: SkillList) -> list[SkillRead]:
        wanted: dict[str, str] = {}
        for item in data.items:
            wanted.setdefault(item.name.lower(), item.category)
        names = {item.name.lower(): item.name for item in reversed(data.items)}

        skill_ids: set[uuid.UUID] = set()
        for key, category in wanted.items():
            skill = self._get_or_create_skill(names[key], category)
            skill_ids.add(skill.id)

        current = {
            r.skill_id: r
            for r in self.db.scalars(select(UserSkill).where(UserSkill.user_id == user.id))
        }
        for skill_id, row in current.items():
            if skill_id not in skill_ids:
                self.db.delete(row)
        for skill_id in skill_ids - current.keys():
            self.db.add(UserSkill(user_id=user.id, skill_id=skill_id, source="manual"))
        self._commit()
        return self.list_skills(user)

    def _get_or_create_skill(self, name: str, category: str) -> Skill:
        """Find a skill in the shared catalogue by name (case-insensitive), adding it if new."""
        self.db.execute(
            insert(Skill).values(canonical_name=name, category=category).on_conflict_do_nothing()
        )
        skill = self.db.scalar(select(Skill).where(func.lower(Skill.canonical_name) == name.lower()))
        if skill.category is None:
            skill.category = category
        return skill

    # Onboarding progress ---------------------------------------------------------------------

    def update_onboarding(self, user: User, data: OnboardingUpdate) -> User:
        user.onboarding_step = data.onboarding_step
        if user.onboarding_status != "completed":
            user.onboarding_status = data.onboarding_status
        self._commit()
        self.db.refresh(user)
        return user

    def _commit(self) -> None:
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise ConflictError("These details conflict with data that is already saved") from exc
