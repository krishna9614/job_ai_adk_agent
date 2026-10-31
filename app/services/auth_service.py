from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.errors import AuthenticationError, ConflictError
from app.models import User
from app.services.auth_provider import AuthProvider, AuthSession
from app.services.user_service import UserService


@dataclass(frozen=True)
class AuthOutcome:
    user: User
    session: AuthSession | None


class AuthService:
    def __init__(self, db: Session, provider: AuthProvider):
        self.provider = provider
        self.user_service = UserService(db)

    def sign_up(self, email: str, password: str) -> AuthOutcome:
        if self.user_service.email_is_registered(email):
            raise ConflictError("An account with this email already exists")
        result = self.provider.sign_up(email, password)
        user = self.user_service.sync_authenticated_user(
            result.identity, record_login=result.session is not None
        )
        return AuthOutcome(user=user, session=result.session)

    def sign_in(self, email: str, password: str) -> AuthOutcome:
        result = self.provider.sign_in(email, password)
        if result.session is None:
            raise AuthenticationError("Invalid email or password")
        user = self.user_service.sync_authenticated_user(result.identity, record_login=True)
        return AuthOutcome(user=user, session=result.session)

    def authenticate_token(self, token: str) -> User:
        identity = self.provider.verify_access_token(token)
        return self.user_service.sync_authenticated_user(identity)
