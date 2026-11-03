import re
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, EmailStr, Field, StringConstraints

from app.schemas.user import UserRead

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 72  # bcrypt limit used by Supabase Auth
_PASSWORD_RULES = (
    (re.compile(r"[A-Z]"), "one uppercase letter (A-Z)"),
    (re.compile(r"[a-z]"), "one lowercase letter (a-z)"),
    (re.compile(r"[0-9]"), "one number (0-9)"),
    (re.compile(r"[^A-Za-z0-9]"), "one special character"),
)


def _strong_password(value: str) -> str:
    missing = [label for pattern, label in _PASSWORD_RULES if not pattern.search(value)]
    if missing:
        raise ValueError("Password must contain at least " + ", ".join(missing))
    return value


StrongPassword = Annotated[
    str,
    Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH),
    AfterValidator(_strong_password),
]

_NAME_PART_MAX = 100  # jobai.user_profiles name columns are VARCHAR(100)


def _full_name(value: str) -> str:
    name = " ".join(value.split())
    if not any(ch.isalpha() for ch in name):
        raise ValueError("Full name must contain letters")
    if any(len(part or "") > _NAME_PART_MAX for part in split_full_name(name)):
        raise ValueError(f"Each part of the name must be at most {_NAME_PART_MAX} characters")
    return name


FullName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200), AfterValidator(_full_name)
]


def split_full_name(name: str) -> tuple[str, str | None, str | None]:
    """'Mary Ann van Dyke' -> ('Mary', 'Ann van', 'Dyke'); a single word is a first name."""
    parts = name.split()
    if len(parts) == 1:
        return parts[0], None, None
    middle = " ".join(parts[1:-1]) or None
    return parts[0], middle, parts[-1]


TokenHash = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]


class SignupRequest(BaseModel):
    full_name: FullName
    email: EmailStr
    password: StrongPassword


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=512)


class EmailRequest(BaseModel):
    email: EmailStr


class ConfirmEmailRequest(BaseModel):
    token_hash: TokenHash
    type: Literal["signup", "email", "email_change"]


class RecoveryRequest(BaseModel):
    token_hash: TokenHash


class PasswordResetRequest(BaseModel):
    password: StrongPassword


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"
    expires_in: int | None = None


class SignupResponse(BaseModel):
    user: UserRead
    session: TokenResponse | None = Field(
        None, description="Null when Supabase requires email confirmation before login."
    )
    email_confirmation_required: bool


class LoginResponse(BaseModel):
    user: UserRead
    session: TokenResponse


class ConfirmEmailResponse(BaseModel):
    user: UserRead | None
    session: TokenResponse | None = Field(
        None, description="Null while an email change still awaits confirmation from the other address."
    )
    confirmation_pending: bool


class RecoveryResponse(BaseModel):
    session: TokenResponse


class MessageResponse(BaseModel):
    detail: str
