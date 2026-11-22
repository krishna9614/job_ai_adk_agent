"""Profile-setup tables owned by db/jobai_v1_schema.sql (only the columns the API uses are mapped)."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    Boolean,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


def _id() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())


def _owner() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )


def _created() -> Mapped[datetime]:
    return mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


def _updated() -> Mapped[datetime]:
    return mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class JobPreferences(Base):
    __tablename__ = "job_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    employment_status: Mapped[str | None] = mapped_column(String(20))
    preferred_job_titles: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    preferred_locations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    preferred_work_types: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    preferred_employment_types: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    minimum_salary: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    maximum_salary: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    salary_currency: Mapped[str | None] = mapped_column(CHAR(3))
    salary_period: Mapped[str | None] = mapped_column(String(20))
    notice_period_days: Mapped[int | None] = mapped_column(Integer)
    willing_to_relocate: Mapped[bool | None] = mapped_column(Boolean)
    requires_visa_sponsorship: Mapped[bool | None] = mapped_column(Boolean)
    recruiter_visibility: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    daily_job_match_digest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class UserExperience(Base):
    __tablename__ = "user_experience"

    id: Mapped[uuid.UUID] = _id()
    user_id: Mapped[uuid.UUID] = _owner()
    company_name: Mapped[str] = mapped_column(String(250), nullable=False)
    job_title: Mapped[str] = mapped_column(String(200), nullable=False)
    employment_type: Mapped[str | None] = mapped_column(String(30))
    work_arrangement: Mapped[str | None] = mapped_column(String(20))
    location_city: Mapped[str | None] = mapped_column(String(120))
    location_state: Mapped[str | None] = mapped_column(String(120))
    location_country: Mapped[str | None] = mapped_column(CHAR(2))
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    description: Mapped[str | None] = mapped_column(Text)
    display_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class Skill(Base):
    """Shared skill catalogue; names are unique case-insensitively."""

    __tablename__ = "skills"

    id: Mapped[uuid.UUID] = _id()
    canonical_name: Mapped[str] = mapped_column(String(150), nullable=False)
    category: Mapped[str | None] = mapped_column(String(80))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _created()


class UserSkill(Base):
    __tablename__ = "user_skills"

    id: Mapped[uuid.UUID] = _id()
    user_id: Mapped[uuid.UUID] = _owner()
    skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skills.id"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="manual")
    created_at: Mapped[datetime] = _created()

    skill: Mapped[Skill] = relationship(lazy="joined")


class EducationLevel(Base):
    __tablename__ = "education_levels"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False)


class UserEducation(Base):
    __tablename__ = "user_education"

    id: Mapped[uuid.UUID] = _id()
    user_id: Mapped[uuid.UUID] = _owner()
    education_level_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("education_levels.id"), nullable=False
    )
    degree_name: Mapped[str] = mapped_column(String(200), nullable=False)
    institution_name: Mapped[str] = mapped_column(String(250), nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date)
    graduation_year: Mapped[int | None] = mapped_column(SmallInteger)
    is_currently_studying: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    education_status: Mapped[str] = mapped_column(String(20), nullable=False, default="completed")
    display_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    level: Mapped[EducationLevel] = relationship(lazy="joined")


class UserCertification(Base):
    __tablename__ = "user_certifications"

    id: Mapped[uuid.UUID] = _id()
    user_id: Mapped[uuid.UUID] = _owner()
    certification_name: Mapped[str] = mapped_column(String(250), nullable=False)
    issuing_organization: Mapped[str | None] = mapped_column(String(250))
    issue_date: Mapped[date | None] = mapped_column(Date)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    credential_id: Mapped[str | None] = mapped_column(String(200))
    credential_url: Mapped[str | None] = mapped_column(Text)
    display_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class UserLanguage(Base):
    __tablename__ = "user_languages"

    id: Mapped[uuid.UUID] = _id()
    user_id: Mapped[uuid.UUID] = _owner()
    language_name: Mapped[str] = mapped_column(String(100), nullable=False)
    proficiency_level: Mapped[str] = mapped_column(String(20), nullable=False)
    display_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()
