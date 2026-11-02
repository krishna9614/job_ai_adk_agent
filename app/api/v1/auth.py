from fastapi import APIRouter, Depends, Response, status

from app.api.deps import get_access_token, get_auth_service
from app.schemas.auth import (
    ConfirmEmailRequest,
    ConfirmEmailResponse,
    EmailRequest,
    LoginRequest,
    LoginResponse,
    MessageResponse,
    PasswordResetRequest,
    RecoveryRequest,
    RecoveryResponse,
    RefreshRequest,
    SignupRequest,
    SignupResponse,
)
from app.schemas.user import UserRead
from app.services.auth_provider import AuthSession
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])

_RESET_SENT = "If an account exists for this email, we've sent a password reset link."
_VERIFICATION_SENT = "If this email is awaiting verification, we've sent a new link."


def _session_payload(session: AuthSession | None) -> dict | None:
    if session is None:
        return None
    return {
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "token_type": session.token_type,
        "expires_in": session.expires_in,
    }


@router.post("/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
def signup(body: SignupRequest, auth: AuthService = Depends(get_auth_service)) -> SignupResponse:
    outcome = auth.sign_up(body.email, body.password, body.full_name)
    return SignupResponse(
        user=UserRead.model_validate(outcome.user),
        session=_session_payload(outcome.session),
        email_confirmation_required=outcome.session is None,
    )


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, auth: AuthService = Depends(get_auth_service)) -> LoginResponse:
    outcome = auth.sign_in(body.email, body.password)
    return LoginResponse(
        user=UserRead.model_validate(outcome.user), session=_session_payload(outcome.session)
    )


@router.post("/refresh", response_model=LoginResponse)
def refresh(body: RefreshRequest, auth: AuthService = Depends(get_auth_service)) -> LoginResponse:
    outcome = auth.refresh(body.refresh_token)
    return LoginResponse(
        user=UserRead.model_validate(outcome.user), session=_session_payload(outcome.session)
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    token: str = Depends(get_access_token), auth: AuthService = Depends(get_auth_service)
) -> Response:
    auth.sign_out(token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/password/forgot", response_model=MessageResponse, status_code=status.HTTP_202_ACCEPTED
)
def forgot_password(
    body: EmailRequest, auth: AuthService = Depends(get_auth_service)
) -> MessageResponse:
    auth.request_password_reset(body.email)
    return MessageResponse(detail=_RESET_SENT)


@router.post("/password/recovery", response_model=RecoveryResponse)
def start_recovery(
    body: RecoveryRequest, auth: AuthService = Depends(get_auth_service)
) -> RecoveryResponse:
    """Consume the emailed reset link; the returned session may only be used to set a password."""
    return RecoveryResponse(session=_session_payload(auth.start_password_recovery(body.token_hash)))


@router.post("/password/reset", response_model=MessageResponse)
def reset_password(
    body: PasswordResetRequest,
    token: str = Depends(get_access_token),
    auth: AuthService = Depends(get_auth_service),
) -> MessageResponse:
    auth.reset_password(token, body.password)
    return MessageResponse(detail="Your password has been reset. Please log in with your new password.")


@router.post(
    "/verification/resend", response_model=MessageResponse, status_code=status.HTTP_202_ACCEPTED
)
def resend_verification(
    body: EmailRequest, auth: AuthService = Depends(get_auth_service)
) -> MessageResponse:
    auth.resend_verification(body.email)
    return MessageResponse(detail=_VERIFICATION_SENT)


@router.post("/email/confirm", response_model=ConfirmEmailResponse)
def confirm_email(
    body: ConfirmEmailRequest, auth: AuthService = Depends(get_auth_service)
) -> ConfirmEmailResponse:
    outcome = auth.confirm_email(body.token_hash, body.type)
    return ConfirmEmailResponse(
        user=UserRead.model_validate(outcome.user) if outcome.user else None,
        session=_session_payload(outcome.session),
        confirmation_pending=outcome.user is None,
    )
