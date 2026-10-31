from sqlalchemy import text

from tests.conftest import bearer


def test_signup_success(client, db_session_factory):
    resp = client.post(
        "/api/v1/auth/signup", json={"email": "Ada@Example.com", "password": "S3cure-pass!"}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["user"]["email"].lower() == "ada@example.com"
    assert body["user"]["account_status"] == "active"
    assert body["session"]["access_token"]
    assert body["email_confirmation_required"] is False

    with db_session_factory() as db:
        row = db.execute(text("SELECT auth_user_id, email FROM jobai.users")).one()
    assert row.auth_user_id is not None
    assert row.email.lower() == "ada@example.com"


def test_signup_duplicate_email(client, signup, db_session_factory):
    signup("ada@example.com")
    resp = client.post(
        "/api/v1/auth/signup", json={"email": "ADA@example.com", "password": "An0ther-pass!"}
    )
    assert resp.status_code == 409
    with db_session_factory() as db:
        assert db.execute(text("SELECT count(*) FROM jobai.users")).scalar_one() == 1


def test_signup_rejects_short_password(client):
    resp = client.post("/api/v1/auth/signup", json={"email": "a@example.com", "password": "short"})
    assert resp.status_code == 422


def test_login_success(client, signup, db_session_factory):
    created = signup("ada@example.com", "S3cure-pass!")
    resp = client.post(
        "/api/v1/auth/login", json={"email": "ada@example.com", "password": "S3cure-pass!"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["user"]["id"] == created["user"]["id"]
    assert body["user"]["last_login_at"] is not None
    assert body["session"]["access_token"]

    # Re-login is idempotent: still exactly one application user.
    client.post("/api/v1/auth/login", json={"email": "ada@example.com", "password": "S3cure-pass!"})
    with db_session_factory() as db:
        assert db.execute(text("SELECT count(*) FROM jobai.users")).scalar_one() == 1


def test_login_invalid_credentials(client, signup):
    signup("ada@example.com", "S3cure-pass!")
    wrong_pw = client.post(
        "/api/v1/auth/login", json={"email": "ada@example.com", "password": "wrong-password"}
    )
    unknown = client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "S3cure-pass!"}
    )
    assert wrong_pw.status_code == 401
    assert unknown.status_code == 401
    assert wrong_pw.headers["www-authenticate"] == "Bearer"


def test_users_me(client, signup):
    created = signup()
    resp = client.get("/api/v1/users/me", headers=bearer(created["session"]["access_token"]))
    assert resp.status_code == 200
    assert resp.json()["id"] == created["user"]["id"]
