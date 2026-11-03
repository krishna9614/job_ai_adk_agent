from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_access_token, get_auth_service, get_current_user
from app.db.session import get_db
from app.models import User
from app.schemas.auth import EmailRequest, MessageResponse
from app.schemas.profile import ProfileCreate, ProfileRead, ProfileUpdate
from app.schemas.user import UserRead
from app.services.auth_service import AuthService
from app.services.profile_service import ProfileService

router = APIRouter(prefix="/users/me", tags=["users"])


def get_profile_service(db: Session = Depends(get_db)) -> ProfileService:
    return ProfileService(db)


@router.get("", response_model=UserRead)
def read_me(user: User = Depends(get_current_user)) -> User:
    return user


@router.post("/email-change", response_model=MessageResponse, status_code=status.HTTP_202_ACCEPTED)
def request_email_change(
    body: EmailRequest,
    token: str = Depends(get_access_token),
    user: User = Depends(get_current_user),
    auth: AuthService = Depends(get_auth_service),
) -> MessageResponse:
    """Supabase emails a confirmation link; the stored email changes once it is confirmed."""
    auth.request_email_change(token, user, body.email)
    return MessageResponse(detail=f"We've sent a confirmation link to {body.email}.")


@router.post("/profile", response_model=ProfileRead, status_code=status.HTTP_201_CREATED)
def create_profile(
    body: ProfileCreate,
    user: User = Depends(get_current_user),
    service: ProfileService = Depends(get_profile_service),
):
    return service.create_profile(user, body)


@router.get("/profile", response_model=ProfileRead)
def read_profile(
    user: User = Depends(get_current_user), service: ProfileService = Depends(get_profile_service)
):
    return service.get_profile(user)


@router.patch("/profile", response_model=ProfileRead)
def update_profile(
    body: ProfileUpdate,
    user: User = Depends(get_current_user),
    service: ProfileService = Depends(get_profile_service),
):
    return service.update_profile(user, body)
