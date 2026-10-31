import uuid
from datetime import datetime
from typing import Annotated, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    TypeAdapter,
    model_validator,
)

_http_url = TypeAdapter(HttpUrl)


def _validate_url(value: str | None) -> str | None:
    return str(_http_url.validate_python(value)) if value is not None else None


def _upper(value: str | None) -> str | None:
    return value.upper() if value is not None else None


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
OptName = Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=100)]
Url = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, max_length=2048),
    AfterValidator(_validate_url),
]
CountryCode = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z]{2}$"),
    AfterValidator(_upper),
]


class _ProfileFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    middle_name: OptName = None
    last_name: OptName = None
    preferred_name: OptName = None
    phone_country_code: Annotated[
        str | None, StringConstraints(strip_whitespace=True, pattern=r"^\+?[0-9]{1,7}$")
    ] = None
    phone_number: Annotated[
        str | None, StringConstraints(strip_whitespace=True, pattern=r"^[0-9 ()\-.]{4,30}$")
    ] = None
    city: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=120)] = None
    state_province: Annotated[
        str | None, StringConstraints(strip_whitespace=True, max_length=120)
    ] = None
    country_code: CountryCode = Field(None, description="ISO 3166-1 alpha-2, e.g. US")
    professional_headline: Annotated[
        str | None, StringConstraints(strip_whitespace=True, max_length=250)
    ] = None
    professional_summary: Annotated[
        str | None, StringConstraints(strip_whitespace=True, max_length=5000)
    ] = None
    linkedin_url: Url = None
    github_url: Url = None


class ProfileCreate(_ProfileFields):
    first_name: Name


class ProfileUpdate(_ProfileFields):
    """Partial update: only fields present in the request body are changed."""

    first_name: Name | None = None

    @model_validator(mode="after")
    def _check(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to update")
        if "first_name" in self.model_fields_set and self.first_name is None:
            raise ValueError("first_name cannot be null")
        return self


class ProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    first_name: str
    middle_name: str | None
    last_name: str | None
    preferred_name: str | None
    phone_country_code: str | None
    phone_number: str | None
    city: str | None
    state_province: str | None
    country_code: str | None
    professional_headline: str | None
    professional_summary: str | None
    linkedin_url: str | None
    github_url: str | None
    created_at: datetime
    updated_at: datetime
