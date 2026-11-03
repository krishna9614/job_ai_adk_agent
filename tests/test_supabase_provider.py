"""SupabaseAuthProvider error mapping with the Supabase client mocked out."""

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from supabase_auth.errors import AuthApiError

from app.core.errors import (
    AuthenticationError,
    AuthProviderUnavailableError,
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


_NETWORK_ERRORS = [
    httpx.ConnectTimeout("_ssl.c:1015: The handshake operation timed out"),
    httpx.ConnectError("[Errno 11001] getaddrinfo failed"),
    httpx.ReadTimeout("timed out"),
]


@pytest.mark.parametrize("error", _NETWORK_ERRORS, ids=lambda e: type(e).__name__)
@pytest.mark.parametrize(
    ("client_method", "call"),
    [
        ("sign_in_with_password", lambda p: p.sign_in("ada@example.com", "S3cure-pass!")),
        ("sign_up", lambda p: p.sign_up("ada@example.com", "S3cure-pass!", full_name="Ada")),
        ("refresh_session", lambda p: p.refresh("refresh")),
        ("reset_password_for_email", lambda p: p.send_password_reset("ada@example.com")),
        ("resend", lambda p: p.resend_signup_confirmation("ada@example.com")),
        ("get_claims", lambda p: p.verify_access_token("token")),
    ],
)
def test_supabase_unreachable_is_503_not_500(gotrue, client_method, call, error):
    getattr(gotrue, client_method).side_effect = error
    with pytest.raises(AuthProviderUnavailableError, match="Couldn't reach"):
        call(ap.SupabaseAuthProvider("https://x.supabase.co", "anon"))


def test_sign_out_unreachable_is_503(gotrue):
    gotrue.admin.sign_out.side_effect = httpx.ConnectTimeout("handshake timed out")
    with pytest.raises(AuthProviderUnavailableError):
        ap.SupabaseAuthProvider("https://x.supabase.co", "anon").sign_out("t", "global")


def test_rest_calls_unreachable_is_503(monkeypatch, gotrue):
    def boom(*_a, **_k):
        raise httpx.ConnectTimeout("handshake timed out")

    monkeypatch.setattr(ap.httpx, "request", boom)
    provider = ap.SupabaseAuthProvider("https://x.supabase.co", "anon")
    with pytest.raises(AuthProviderUnavailableError):
        provider.verify_email_token("h", "recovery")
    with pytest.raises(AuthProviderUnavailableError):
        provider.update_password("t", "N3w-secret!")


def test_login_endpoint_returns_503_json_when_supabase_unreachable(client, gotrue):
    from app.api.deps import get_auth_provider
    from app.main import app

    gotrue.sign_in_with_password.side_effect = httpx.ConnectTimeout("handshake timed out")
    app.dependency_overrides[get_auth_provider] = lambda: ap.SupabaseAuthProvider(
        "https://x.supabase.co", "anon"
    )
    resp = client.post(
        "/api/v1/auth/login", json={"email": "ada@example.com", "password": "S3cure-pass!"}
    )
    assert resp.status_code == 503
    assert resp.json()["code"] == "auth_unavailable"
