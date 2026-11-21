"""Request/response models for the profile-setup resources under /users/me."""

import uuid
from datetime import date, datetime
from typing import Annotated, Generic, Literal, Self, TypeVar

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.schemas.profile import CountryCode, Url


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for v in values:
        if v.lower() not in seen:
            seen.add(v.lower())
            out.append(v)
    return out


def _text(max_length: int, min_length: int = 0):
    return StringConstraints(strip_whitespace=True, min_length=min_length, max_length=max_length)


Required = lambda n: Annotated[str, _text(n, 1)]  # noqa: E731
Optional = lambda n: Annotated[str | None, _text(n)]  # noqa: E731
TagList = Annotated[list[Required(200)], Field(max_length=20), AfterValidator(_dedupe)]

EmploymentStatus = Literal["student", "fresher", "employed", "actively_looking"]
WorkType = Literal["remote", "hybrid", "on_site"]
EmploymentType = Literal["full_time", "part_time", "contract", "internship", "freelance"]
SalaryPeriod = Literal["hourly", "monthly", "yearly"]
SkillCategory = Literal["technical", "soft", "tool"]
EducationLevelCode = Literal[
    "high_school", "diploma", "associate", "bachelors", "masters", "mba", "doctorate",
    "professional", "certificate", "other",
]
LanguageProficiency = Literal["basic", "conversational", "intermediate", "professional", "native"]
Currency = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z]{3}$"),
    AfterValidator(lambda v: v.upper() if v else v),
]
Salary = Annotated[float | None, Field(ge=0, le=999_999_999_999)]
Year = Annotated[int | None, Field(ge=1900, le=2200)]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


# Preferences ---------------------------------------------------------------------------------


class PreferencesUpdate(_Input):
    """Partial update; creates the preferences record on first save."""

    employment_status: EmploymentStatus | None = None
    preferred_job_titles: TagList = []
    preferred_locations: TagList = []
    preferred_work_types: Annotated[list[WorkType], Field(max_length=3)] = []
    preferred_employment_types: Annotated[list[EmploymentType], Field(max_length=5)] = []
    minimum_salary: Salary = None
    maximum_salary: Salary = None
    salary_currency: Currency = None
    salary_period: SalaryPeriod | None = None
    notice_period_days: Annotated[int | None, Field(ge=0, le=365)] = None
    willing_to_relocate: bool | None = None
    requires_visa_sponsorship: bool | None = None
    recruiter_visibility: bool = False
    daily_job_match_digest: bool = False

    @model_validator(mode="after")
    def _check(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to update")
        for key in ("recruiter_visibility", "daily_job_match_digest"):
            if key in self.model_fields_set and getattr(self, key) is None:
                raise ValueError(f"{key} cannot be null")
        return self


class PreferencesRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    employment_status: str | None = None
    preferred_job_titles: list[str] = []
    preferred_locations: list[str] = []
    preferred_work_types: list[str] = []
    preferred_employment_types: list[str] = []
    minimum_salary: float | None = None
    maximum_salary: float | None = None
    salary_currency: str | None = None
    salary_period: str | None = None
    notice_period_days: int | None = None
    willing_to_relocate: bool | None = None
    requires_visa_sponsorship: bool | None = None
    recruiter_visibility: bool = False
    daily_job_match_digest: bool = False
    updated_at: datetime | None = None


# Lists (replaced as a whole on save) ---------------------------------------------------------

ItemT = TypeVar("ItemT", bound=BaseModel)


class ItemList(_Input, Generic[ItemT]):
    """The full list for a section: items with an ``id`` are updated, items without one are
    added, and saved items missing from the list are deleted. Order is kept."""

    items: list[ItemT]

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        ids = [i.id for i in self.items if getattr(i, "id", None) is not None]
        if len(ids) != len(set(ids)):
            raise ValueError("Each item id may appear only once")
        return self


class ExperienceItem(_Input):
    id: uuid.UUID | None = None
    company_name: Required(250)
    job_title: Required(200)
    employment_type: EmploymentType | None = None
    work_arrangement: WorkType | None = None
    location_city: Optional(120) = None
    location_state: Optional(120) = None
    location_country: CountryCode = None
    start_date: date
    end_date: date | None = None
    is_current: bool = False
    description: Optional(5000) = None

    @model_validator(mode="after")
    def _dates(self) -> Self:
        if self.is_current and self.end_date is not None:
            raise ValueError("A current role cannot have an end date")
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("End date must be on or after the start date")
        return self


class ExperienceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_name: str
    job_title: str
    employment_type: str | None
    work_arrangement: str | None
    location_city: str | None
    location_state: str | None
    location_country: str | None
    start_date: date
    end_date: date | None
    is_current: bool
    description: str | None


class SkillItem(_Input):
    name: Required(150)
    category: SkillCategory


class SkillList(_Input):
    items: Annotated[list[SkillItem], Field(max_length=60)]


class SkillRead(BaseModel):
    name: str
    category: str | None


class EducationItem(_Input):
    id: uuid.UUID | None = None
    education_level: EducationLevelCode
    degree_name: Required(200)
    institution_name: Required(250)
    start_year: Year = None
    end_year: Year = Field(None, description="Graduation year (expected, while studying)")
    is_currently_studying: bool = False

    @model_validator(mode="after")
    def _years(self) -> Self:
        if self.start_year and self.end_year and self.end_year < self.start_year:
            raise ValueError("End year must be on or after the start year")
        return self


class EducationRead(BaseModel):
    id: uuid.UUID
    education_level: str
    degree_name: str
    institution_name: str
    start_year: int | None
    end_year: int | None
    is_currently_studying: bool


class CertificationItem(_Input):
    id: uuid.UUID | None = None
    certification_name: Required(250)
    issuing_organization: Optional(250) = None
    issue_date: date | None = None
    expiry_date: date | None = None
    credential_id: Optional(200) = None
    credential_url: Url = None

    @model_validator(mode="after")
    def _dates(self) -> Self:
        if self.issue_date and self.expiry_date and self.expiry_date < self.issue_date:
            raise ValueError("Expiry date must be on or after the issue date")
        return self


class CertificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    certification_name: str
    issuing_organization: str | None
    issue_date: date | None
    expiry_date: date | None
    credential_id: str | None
    credential_url: str | None


class LanguageItem(_Input):
    id: uuid.UUID | None = None
    language_name: Required(100)
    proficiency_level: LanguageProficiency


class LanguageList(ItemList[LanguageItem]):
    @model_validator(mode="after")
    def _unique_names(self) -> Self:
        names = [i.language_name.lower() for i in self.items]
        if len(names) != len(set(names)):
            raise ValueError("Each language may appear only once")
        return self


class LanguageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    language_name: str
    proficiency_level: str


class ExperienceList(ItemList[ExperienceItem]):
    items: Annotated[list[ExperienceItem], Field(max_length=30)]


class EducationList(ItemList[EducationItem]):
    items: Annotated[list[EducationItem], Field(max_length=20)]


class CertificationList(ItemList[CertificationItem]):
    items: Annotated[list[CertificationItem], Field(max_length=30)]


# Onboarding progress -------------------------------------------------------------------------


class OnboardingUpdate(_Input):
    onboarding_step: Annotated[int, Field(ge=0, le=6)]
    onboarding_status: Literal["in_progress", "completed"] = "in_progress"
