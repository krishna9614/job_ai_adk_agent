from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_access_token, get_auth_service, get_current_user
from app.db.session import get_db
from app.models import User
from app.schemas.auth import EmailRequest, MessageResponse
from app.schemas.profile import ProfileCreate, ProfileRead, ProfileUpdate
from app.schemas.profile_setup import (
    CertificationList,
    CertificationRead,
    EducationList,
    EducationRead,
    ExperienceList,
    ExperienceRead,
    LanguageList,
    LanguageRead,
    OnboardingUpdate,
    PreferencesRead,
    PreferencesUpdate,
    SkillList,
    SkillRead,
)
from app.schemas.user import UserRead
from app.services.auth_service import AuthService
from app.services.profile_service import ProfileService
from app.services.profile_setup_service import ProfileSetupService

router = APIRouter(prefix="/users/me", tags=["users"])


def get_profile_service(db: Session = Depends(get_db)) -> ProfileService:
    return ProfileService(db)


def get_setup_service(db: Session = Depends(get_db)) -> ProfileSetupService:
    return ProfileSetupService(db)


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


@router.patch("/onboarding", response_model=UserRead)
def update_onboarding(
    body: OnboardingUpdate,
    user: User = Depends(get_current_user),
    service: ProfileSetupService = Depends(get_setup_service),
):
    """Records the setup step to resume from; once completed, the status stays completed."""
    return service.update_onboarding(user, body)


@router.get("/preferences", response_model=PreferencesRead)
def read_preferences(
    user: User = Depends(get_current_user), service: ProfileSetupService = Depends(get_setup_service)
):
    """Returns empty defaults (``updated_at`` null) until the first save."""
    return service.get_preferences(user)


@router.patch("/preferences", response_model=PreferencesRead)
def update_preferences(
    body: PreferencesUpdate,
    user: User = Depends(get_current_user),
    service: ProfileSetupService = Depends(get_setup_service),
):
    return service.update_preferences(user, body)


@router.get("/experience", response_model=list[ExperienceRead])
def read_experience(
    user: User = Depends(get_current_user), service: ProfileSetupService = Depends(get_setup_service)
):
    return service.list_experience(user)


@router.put("/experience", response_model=list[ExperienceRead])
def replace_experience(
    body: ExperienceList,
    user: User = Depends(get_current_user),
    service: ProfileSetupService = Depends(get_setup_service),
):
    return service.replace_experience(user, body)


@router.get("/skills", response_model=list[SkillRead])
def read_skills(
    user: User = Depends(get_current_user), service: ProfileSetupService = Depends(get_setup_service)
):
    return service.list_skills(user)


@router.put("/skills", response_model=list[SkillRead])
def replace_skills(
    body: SkillList,
    user: User = Depends(get_current_user),
    service: ProfileSetupService = Depends(get_setup_service),
):
    return service.replace_skills(user, body)


@router.get("/education", response_model=list[EducationRead])
def read_education(
    user: User = Depends(get_current_user), service: ProfileSetupService = Depends(get_setup_service)
):
    return service.list_education(user)


@router.put("/education", response_model=list[EducationRead])
def replace_education(
    body: EducationList,
    user: User = Depends(get_current_user),
    service: ProfileSetupService = Depends(get_setup_service),
):
    return service.replace_education(user, body)


@router.get("/certifications", response_model=list[CertificationRead])
def read_certifications(
    user: User = Depends(get_current_user), service: ProfileSetupService = Depends(get_setup_service)
):
    return service.list_certifications(user)


@router.put("/certifications", response_model=list[CertificationRead])
def replace_certifications(
    body: CertificationList,
    user: User = Depends(get_current_user),
    service: ProfileSetupService = Depends(get_setup_service),
):
    return service.replace_certifications(user, body)


@router.get("/languages", response_model=list[LanguageRead])
def read_languages(
    user: User = Depends(get_current_user), service: ProfileSetupService = Depends(get_setup_service)
):
    return service.list_languages(user)


@router.put("/languages", response_model=list[LanguageRead])
def replace_languages(
    body: LanguageList,
    user: User = Depends(get_current_user),
    service: ProfileSetupService = Depends(get_setup_service),
):
    return service.replace_languages(user, body)
