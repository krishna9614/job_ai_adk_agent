import pytest

from tests.conftest import bearer

PROFILE = "/api/v1/users/me/profile"


@pytest.fixture()
def token(signup):
    return signup("ada@example.com")["session"]["access_token"]


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


def test_cross_user_profile_access(client, signup):
    ada = signup("ada@example.com")["session"]["access_token"]
    bob = signup("bob@example.com")["session"]["access_token"]
    client.post(PROFILE, headers=bearer(ada), json={"first_name": "Ada"})

    # Bob only ever sees his own (non-existent) profile, and cannot alter Ada's.
    assert client.get(PROFILE, headers=bearer(bob)).status_code == 404
    assert client.patch(PROFILE, headers=bearer(bob), json={"first_name": "Mallory"}).status_code == 404
    bob_profile = client.post(PROFILE, headers=bearer(bob), json={"first_name": "Bob"}).json()

    ada_profile = client.get(PROFILE, headers=bearer(ada)).json()
    assert ada_profile["first_name"] == "Ada"
    assert ada_profile["user_id"] != bob_profile["user_id"]
