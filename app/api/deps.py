from functools import lru_cache

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AuthenticationError, AuthProviderUnavailableError
from app.db.session import get_db
from app.models import User
from app.services.auth_provider import AuthProvider, SupabaseAuthProvider
from app.services.auth_service import AuthService

_bearer = HTTPBearer(auto_error=False)


@lru_cache
def _supabase_provider(url: str, anon_key: str) -> SupabaseAuthProvider:
    return SupabaseAuthProvider(url, anon_key)


def get_auth_provider() -> AuthProvider:
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_anon_key:
        raise AuthProviderUnavailableError(
            "Supabase Auth is not configured: set SUPABASE_URL and SUPABASE_ANON_KEY"
        )
    return _supabase_provider(settings.supabase_url, settings.supabase_anon_key)


def get_auth_service(
    db: Session = Depends(get_db), provider: AuthProvider = Depends(get_auth_provider)
) -> AuthService:
    return AuthService(db, provider)


def get_access_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise AuthenticationError("Missing bearer token")
    return credentials.credentials


def get_current_user(
    token: str = Depends(get_access_token), auth: AuthService = Depends(get_auth_service)
) -> User:
    """The authenticated caller, derived only from the verified Supabase access token."""
    return auth.authenticate_token(token)
