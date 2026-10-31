"""SupabaseAuthProvider error mapping with the Supabase client mocked out."""

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from supabase_auth.errors import AuthApiError

from app.core.errors import AuthenticationError, ConflictError, ForbiddenError
from app.services import auth_provider as ap


@pytest.fixture()
def gotrue(monkeypatch):
    auth = MagicMock()
    monkeypatch.setattr(ap, "create_client", lambda *a, **k: SimpleNamespace(auth=auth))
    return auth


def _user(identities):
    return SimpleNamespace(
        id=str(uuid.uuid4()), email="ada@example.com", email_confirmed_at=None, identities=identities
    )


def test_signup_existing_user_error_is_conflict(gotrue):
    gotrue.sign_up.side_effect = AuthApiError("User already registered", 422, "user_already_exists")
    with pytest.raises(ConflictError):
        ap.SupabaseAuthProvider("https://x.supabase.co", "anon").sign_up("ada@example.com", "pw123456")


def test_signup_obfuscated_existing_user_is_conflict(gotrue):
    gotrue.sign_up.return_value = SimpleNamespace(user=_user([]), session=None)
    with pytest.raises(ConflictError):
        ap.SupabaseAuthProvider("https://x.supabase.co", "anon").sign_up("ada@example.com", "pw123456")


def test_signup_pending_confirmation(gotrue):
    gotrue.sign_up.return_value = SimpleNamespace(user=_user([object()]), session=None)
    result = ap.SupabaseAuthProvider("https://x.supabase.co", "anon").sign_up(
        "ada@example.com", "pw123456"
    )
    assert result.session is None


@pytest.mark.parametrize(
    ("code", "expected"),
    [("invalid_credentials", AuthenticationError), ("email_not_confirmed", ForbiddenError)],
)
def test_sign_in_errors(gotrue, code, expected):
    gotrue.sign_in_with_password.side_effect = AuthApiError("nope", 400, code)
    with pytest.raises(expected):
        ap.SupabaseAuthProvider("https://x.supabase.co", "anon").sign_in("ada@example.com", "pw")


def test_verify_rejects_non_authenticated_role(gotrue):
    gotrue.get_claims.return_value = {
        "claims": {"sub": str(uuid.uuid4()), "email": "a@example.com", "role": "anon"}
    }
    with pytest.raises(AuthenticationError):
        ap.SupabaseAuthProvider("https://x.supabase.co", "anon").verify_access_token("t")


def test_verify_valid_claims(gotrue):
    sub = uuid.uuid4()
    gotrue.get_claims.return_value = {
        "claims": {"sub": str(sub), "email": "a@example.com", "role": "authenticated"}
    }
    identity = ap.SupabaseAuthProvider("https://x.supabase.co", "anon").verify_access_token("t")
    assert identity.auth_user_id == sub


def test_unconfigured_supabase_returns_503(client, monkeypatch):
    from app.api import deps
    from app.main import app

    app.dependency_overrides.pop(deps.get_auth_provider)
    monkeypatch.setattr(
        deps, "get_settings", lambda: SimpleNamespace(supabase_url=None, supabase_anon_key=None)
    )
    resp = client.post("/api/v1/auth/login", json={"email": "a@example.com", "password": "x"})
    assert resp.status_code == 503
    assert "SUPABASE_URL" in resp.json()["detail"]
