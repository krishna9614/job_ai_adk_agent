import pytest
from sqlalchemy import text

from tests.conftest import bearer

AUTH = "/api/v1/auth"
PASSWORD = "S3cure-pass!"
NEW_PASSWORD = "N3w-secret!"


def _profile_names(db_session_factory):
    with db_session_factory() as db:
        return db.execute(
            text("SELECT first_name, middle_name, last_name FROM jobai.user_profiles")
        ).one()


def test_signup_stores_full_name_with_spaces(client, auth_provider, db_session_factory):
    resp = client.post(
        f"{AUTH}/signup",
        json={"full_name": "  Mary   Ann van Dyke ", "email": "mary@example.com", "password": PASSWORD},
    )
    assert resp.status_code == 201, resp.text
    assert tuple(_profile_names(db_session_factory)) == ("Mary", "Ann van", "Dyke")
    assert auth_provider.account("mary@example.com").metadata["full_name"] == "Mary Ann van Dyke"
    token = resp.json()["session"]["access_token"]
    assert client.get("/api/v1/users/me/profile", headers=bearer(token)).json()["last_name"] == "Dyke"


def test_signup_single_word_name(client, db_session_factory):
    resp = client.post(
        f"{AUTH}/signup", json={"full_name": "Cher", "email": "c@example.com", "password": PASSWORD}
    )
    assert resp.status_code == 201
    assert tuple(_profile_names(db_session_factory)) == ("Cher", None, None)


@pytest.mark.parametrize("full_name", [None, "", "   ", "12345", "x" * 201])
def test_signup_rejects_invalid_full_name(client, full_name):
    body = {"email": "a@example.com", "password": PASSWORD}
    if full_name is not None:
        body["full_name"] = full_name
    assert client.post(f"{AUTH}/signup", json=body).status_code == 422


@pytest.mark.parametrize(
    ("password", "missing"),
    [
        ("s3cure-pass!", "uppercase"),
        ("S3CURE-PASS!", "lowercase"),
        ("Secure-pass!", "number"),
        ("S3curepass1", "special"),
        ("S3c-ps!", None),
        ("A" * 40 + "a1!" + "b" * 40, None),
    ],
)
def test_signup_enforces_password_policy(client, password, missing):
    resp = client.post(
        f"{AUTH}/signup", json={"full_name": "Ada L", "email": "a@example.com", "password": password}
    )
    assert resp.status_code == 422
    if missing:
        assert missing in resp.text


def test_refresh_rotates_session_and_logout_revokes(client, signup):
    session = signup()["session"]
    resp = client.post(f"{AUTH}/refresh", json={"refresh_token": session["refresh_token"]})
    assert resp.status_code == 200, resp.text
    fresh = resp.json()["session"]
    assert fresh["access_token"] != session["access_token"]
    # Refresh tokens are single use.
    assert client.post(f"{AUTH}/refresh", json={"refresh_token": session["refresh_token"]}).status_code == 401

    assert client.post(f"{AUTH}/logout", headers=bearer(fresh["access_token"])).status_code == 204
    assert client.get("/api/v1/users/me", headers=bearer(fresh["access_token"])).status_code == 401
    assert client.post(f"{AUTH}/refresh", json={"refresh_token": fresh["refresh_token"]}).status_code == 401


def test_forgot_password_does_not_reveal_registration(client, signup, auth_provider):
    signup("ada@example.com")
    known = client.post(f"{AUTH}/password/forgot", json={"email": "ada@example.com"})
    unknown = client.post(f"{AUTH}/password/forgot", json={"email": "nobody@example.com"})
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert [m.to for m in auth_provider.outbox if m.type == "recovery"] == ["ada@example.com"]
    assert client.post(f"{AUTH}/password/forgot", json={"email": "not-an-email"}).status_code == 422


def _recovery_session(client, auth_provider, email="ada@example.com"):
    client.post(f"{AUTH}/password/forgot", json={"email": email})
    token_hash = auth_provider.last_email("recovery").token_hash
    resp = client.post(f"{AUTH}/password/recovery", json={"token_hash": token_hash})
    assert resp.status_code == 200, resp.text
    return token_hash, resp.json()["session"]["access_token"]


def test_password_reset_flow_revokes_sessions(client, signup, auth_provider):
    old_session = signup()["session"]
    token_hash, recovery = _recovery_session(client, auth_provider)

    resp = client.post(f"{AUTH}/password/reset", headers=bearer(recovery), json={"password": NEW_PASSWORD})
    assert resp.status_code == 200, resp.text

    # Every existing session (and the recovery session) is revoked.
    assert client.get("/api/v1/users/me", headers=bearer(old_session["access_token"])).status_code == 401
    assert client.post(f"{AUTH}/refresh", json={"refresh_token": old_session["refresh_token"]}).status_code == 401
    assert client.post(f"{AUTH}/password/reset", headers=bearer(recovery), json={"password": "An0ther-pw!"}).status_code == 401

    # The link is single use; old password no longer works, new one does.
    used = client.post(f"{AUTH}/password/recovery", json={"token_hash": token_hash})
    assert used.status_code == 400 and used.json()["code"] == "invalid_token"
    assert client.post(f"{AUTH}/login", json={"email": "ada@example.com", "password": PASSWORD}).status_code == 401
    assert client.post(f"{AUTH}/login", json={"email": "ada@example.com", "password": NEW_PASSWORD}).status_code == 200


def test_password_reset_rejects_current_password(client, signup, auth_provider):
    signup()
    _, recovery = _recovery_session(client, auth_provider)
    resp = client.post(f"{AUTH}/password/reset", headers=bearer(recovery), json={"password": PASSWORD})
    assert resp.status_code == 422
    assert resp.json()["code"] == "password_reused"


def test_password_reset_enforces_policy(client, signup, auth_provider):
    signup()
    _, recovery = _recovery_session(client, auth_provider)
    resp = client.post(f"{AUTH}/password/reset", headers=bearer(recovery), json={"password": "weakpassword"})
    assert resp.status_code == 422


def test_password_reset_requires_recovery_session(client, signup):
    token = signup()["session"]["access_token"]
    resp = client.post(f"{AUTH}/password/reset", headers=bearer(token), json={"password": NEW_PASSWORD})
    assert resp.status_code == 403
    assert client.post(f"{AUTH}/password/reset", json={"password": NEW_PASSWORD}).status_code == 401


def test_expired_and_invalid_recovery_links(client, signup, auth_provider):
    signup()
    client.post(f"{AUTH}/password/forgot", json={"email": "ada@example.com"})
    auth_provider.expire_email_tokens()
    expired = client.post(
        f"{AUTH}/password/recovery", json={"token_hash": auth_provider.last_email("recovery").token_hash}
    )
    assert expired.status_code == 400 and expired.json()["code"] == "invalid_token"
    assert client.post(f"{AUTH}/password/recovery", json={"token_hash": "bogus"}).status_code == 400
    assert client.post(f"{AUTH}/password/recovery", json={"token_hash": ""}).status_code == 422


def test_email_confirmation_and_resend(client, auth_provider, db_session_factory):
    auth_provider.confirm_email = True
    resp = client.post(
        f"{AUTH}/signup", json={"full_name": "Ada Lovelace", "email": "ada@example.com", "password": PASSWORD}
    )
    assert resp.status_code == 201
    assert resp.json()["email_confirmation_required"] is True
    assert resp.json()["session"] is None
    assert client.post(f"{AUTH}/login", json={"email": "ada@example.com", "password": PASSWORD}).status_code == 403

    first = auth_provider.last_email("signup").token_hash
    resent = client.post(f"{AUTH}/verification/resend", json={"email": "ada@example.com"})
    unknown = client.post(f"{AUTH}/verification/resend", json={"email": "nobody@example.com"})
    assert resent.status_code == unknown.status_code == 202
    assert resent.json() == unknown.json()
    second = auth_provider.last_email("signup").token_hash
    assert second != first

    confirmed = client.post(f"{AUTH}/email/confirm", json={"token_hash": second, "type": "signup"})
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["confirmation_pending"] is False
    assert body["user"]["email_verified_at"] is not None
    assert body["session"]["access_token"]
    again = client.post(f"{AUTH}/email/confirm", json={"token_hash": second, "type": "signup"})
    assert again.status_code == 400

    with db_session_factory() as db:
        assert db.execute(text("SELECT email_verified_at FROM jobai.users")).scalar_one() is not None
    assert client.post(f"{AUTH}/login", json={"email": "ada@example.com", "password": PASSWORD}).status_code == 200


def test_change_email(client, signup, auth_provider, db_session_factory):
    signup("bob@example.com")
    token = signup("ada@example.com")["session"]["access_token"]
    change = "/api/v1/users/me/email-change"

    assert client.post(change, json={"email": "new@example.com"}).status_code == 401
    assert client.post(change, headers=bearer(token), json={"email": "ADA@example.com"}).status_code == 422
    assert client.post(change, headers=bearer(token), json={"email": "bob@example.com"}).status_code == 409

    resp = client.post(change, headers=bearer(token), json={"email": "new@example.com"})
    assert resp.status_code == 202, resp.text
    mail = auth_provider.last_email("email_change")
    assert mail.to == "new@example.com"

    confirmed = client.post(f"{AUTH}/email/confirm", json={"token_hash": mail.token_hash, "type": "email_change"})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["user"]["email"] == "new@example.com"
    with db_session_factory() as db:
        emails = db.execute(text("SELECT email FROM jobai.users ORDER BY email")).scalars().all()
    assert emails == ["bob@example.com", "new@example.com"]
    assert client.post(f"{AUTH}/login", json={"email": "new@example.com", "password": PASSWORD}).status_code == 200


def test_confirm_rejects_unknown_type(client):
    resp = client.post(f"{AUTH}/email/confirm", json={"token_hash": "abc", "type": "recovery"})
    assert resp.status_code == 422
