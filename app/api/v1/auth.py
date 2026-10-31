from fastapi import APIRouter, Depends, status

from app.api.deps import get_auth_service
from app.schemas.auth import LoginRequest, LoginResponse, SignupRequest, SignupResponse
from app.schemas.user import UserRead
from app.services.auth_service import AuthOutcome, AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


def _session_payload(outcome: AuthOutcome) -> dict | None:
    s = outcome.session
    if s is None:
        return None
    return {
        "access_token": s.access_token,
        "refresh_token": s.refresh_token,
        "token_type": s.token_type,
        "expires_in": s.expires_in,
    }


@router.post("/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
def signup(body: SignupRequest, auth: AuthService = Depends(get_auth_service)) -> SignupResponse:
    outcome = auth.sign_up(body.email, body.password)
    return SignupResponse(
        user=UserRead.model_validate(outcome.user),
        session=_session_payload(outcome),
        email_confirmation_required=outcome.session is None,
    )


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, auth: AuthService = Depends(get_auth_service)) -> LoginResponse:
    outcome = auth.sign_in(body.email, body.password)
    return LoginResponse(user=UserRead.model_validate(outcome.user), session=_session_payload(outcome))
