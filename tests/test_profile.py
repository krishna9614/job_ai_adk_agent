import pytest
from sqlalchemy import text

from tests.conftest import bearer

PROFILE = "/api/v1/users/me/profile"


@pytest.fixture()
def signup_without_profile(signup, db_session_factory):
    """Sign up, then drop the profile that sign-up seeds from the full name."""

    def _signup(email: str) -> str:
        body = signup(email)
        with db_session_factory() as db:
            db.execute(
                text("DELETE FROM jobai.user_profiles WHERE user_id = :id"), {"id": body["user"]["id"]}
            )
            db.commit()
        return body["session"]["access_token"]

    return _signup


@pytest.fixture()
def token(signup_without_profile):
    return signup_without_profile("ada@example.com")


@pytest.mark.parametrize("method", ["get", "post", "patch"])
@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Bearer not-a-real-token"}, {"Authorization": "Basic abc"}]
)
def test_profile_requires_authentication(client, method, headers):
    kwargs = {"headers": headers}
    if method != "get":
        kwargs["json"] = {"first_name": "Ada"}
    resp = getattr(client, method)(PROFILE, **kwargs)
    assert resp.status_code == 401
    assert client.get("/api/v1/users/me", headers=headers).status_code == 401


def test_create_profile(client, token):
    resp = client.post(
        PROFILE,
        headers=bearer(token),
        json={
            "first_name": "  Ada ",
            "last_name": "Lovelace",
            "country_code": "gb",
            "linkedin_url": "https://www.linkedin.com/in/ada",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["first_name"] == "Ada"
    assert body["country_code"] == "GB"
    assert body["linkedin_url"] == "https://www.linkedin.com/in/ada"
    assert body["middle_name"] is None

    again = client.post(PROFILE, headers=bearer(token), json={"first_name": "Ada"})
    assert again.status_code == 409


def test_create_profile_validation(client, token):
    assert client.post(PROFILE, headers=bearer(token), json={}).status_code == 422
    assert client.post(PROFILE, headers=bearer(token), json={"first_name": "  "}).status_code == 422
    resp = client.post(PROFILE, headers=bearer(token), json={"first_name": "Ada", "user_id": "x"})
    assert resp.status_code == 422


def test_get_profile(client, token):
    assert client.get(PROFILE, headers=bearer(token)).status_code == 404
    client.post(PROFILE, headers=bearer(token), json={"first_name": "Ada", "city": "London"})
    resp = client.get(PROFILE, headers=bearer(token))
    assert resp.status_code == 200
    assert resp.json()["first_name"] == "Ada"
    assert resp.json()["city"] == "London"


def test_update_profile(client, token):
    created = client.post(
        PROFILE, headers=bearer(token), json={"first_name": "Ada", "city": "London"}
    ).json()
    resp = client.patch(
        PROFILE,
        headers=bearer(token),
        json={"professional_headline": "Mathematician", "city": None},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["first_name"] == "Ada"
    assert body["professional_headline"] == "Mathematician"
    assert body["city"] is None
    assert body["updated_at"] >= created["updated_at"]

    assert client.patch(PROFILE, headers=bearer(token), json={}).status_code == 422
    assert client.patch(PROFILE, headers=bearer(token), json={"first_name": None}).status_code == 422


def test_update_missing_profile(client, token):
    assert client.patch(PROFILE, headers=bearer(token), json={"city": "Paris"}).status_code == 404


def test_cross_user_profile_access(client, signup_without_profile):
    ada = signup_without_profile("ada@example.com")
    bob = signup_without_profile("bob@example.com")
    client.post(PROFILE, headers=bearer(ada), json={"first_name": "Ada"})

    # Bob only ever sees his own (non-existent) profile, and cannot alter Ada's.
    assert client.get(PROFILE, headers=bearer(bob)).status_code == 404
    assert client.patch(PROFILE, headers=bearer(bob), json={"first_name": "Mallory"}).status_code == 404
    bob_profile = client.post(PROFILE, headers=bearer(bob), json={"first_name": "Bob"}).json()

    ada_profile = client.get(PROFILE, headers=bearer(ada)).json()
    assert ada_profile["first_name"] == "Ada"
    assert ada_profile["user_id"] != bob_profile["user_id"]
