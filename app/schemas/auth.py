from pydantic import BaseModel, EmailStr, Field

from app.schemas.user import UserRead


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)


class SignupRequest(Credentials):
    pass


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


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
