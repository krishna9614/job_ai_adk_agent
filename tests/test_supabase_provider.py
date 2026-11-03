"""SupabaseAuthProvider error mapping with the Supabase client mocked out."""

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from supabase_auth.errors import AuthApiError

from app.core.errors import (
    AuthenticationError,
    ConflictError,
    ForbiddenError,
    InvalidTokenError,
    PasswordReusedError,
    ValidationFailedError,
)
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


class _Resp:
    def __init__(self, status: int, body: dict):
        self.status_code = status
        self._body = body
        self.is_success = 200 <= status < 300
        self.content = __import__("json").dumps(body).encode()

    def json(self):
        return self._body


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (422, {"error_code": "same_password", "msg": "New password should be different"}, PasswordReusedError),
        (422, {"error_code": "weak_password", "msg": "Password is too weak"}, ValidationFailedError),
        (422, {"error_code": "email_exists", "msg": "exists"}, ConflictError),
        (401, {"error_code": "bad_jwt", "msg": "invalid JWT"}, AuthenticationError),
    ],
)
def test_update_password_error_mapping(monkeypatch, gotrue, status, body, expected):
    monkeypatch.setattr(ap.httpx, "request", lambda *a, **k: _Resp(status, body))
    with pytest.raises(expected):
        ap.SupabaseAuthProvider("https://x.supabase.co", "anon").update_password("t", "N3w-secret!")


@pytest.mark.parametrize("status", [400, 403, 404])
def test_verify_email_token_rejections_are_invalid_token(monkeypatch, gotrue, status):
    monkeypatch.setattr(
        ap.httpx, "request", lambda *a, **k: _Resp(status, {"error_code": "otp_expired", "msg": "expired"})
    )
    with pytest.raises(InvalidTokenError):
        ap.SupabaseAuthProvider("https://x.supabase.co", "anon").verify_email_token("h", "recovery")


def test_verify_email_token_half_confirmed_email_change(monkeypatch, gotrue):
    monkeypatch.setattr(
        ap.httpx, "request", lambda *a, **k: _Resp(200, {"msg": "Confirmation link accepted", "code": 200})
    )
    assert ap.SupabaseAuthProvider("https://x.supabase.co", "anon").verify_email_token("h", "email_change") is None


def test_verify_reads_amr_methods(gotrue):
    gotrue.get_claims.return_value = {
        "claims": {
            "sub": str(uuid.uuid4()),
            "email": "a@example.com",
            "role": "authenticated",
            "amr": [{"method": "otp", "timestamp": 1}],
        }
    }
    identity = ap.SupabaseAuthProvider("https://x.supabase.co", "anon").verify_access_token("t")
    assert identity.auth_methods == ("otp",)
