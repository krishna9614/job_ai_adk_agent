import pytest

from tests.conftest import bearer

ME = "/api/v1/users/me"


@pytest.fixture()
def token(signup):
    return signup("ada@example.com")["session"]["access_token"]


@pytest.fixture()
def other_token(signup):
    return signup("grace@example.com", full_name="Grace Hopper")["session"]["access_token"]


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/preferences"), ("patch", "/preferences"), ("patch", "/onboarding"),
        ("get", "/experience"), ("put", "/experience"), ("get", "/skills"), ("put", "/skills"),
        ("get", "/education"), ("put", "/education"), ("get", "/certifications"),
        ("put", "/certifications"), ("get", "/languages"), ("put", "/languages"),
    ],
)
def test_setup_endpoints_require_authentication(client, method, path):
    kwargs = {} if method == "get" else {"json": {"items": []}}
    resp = getattr(client, method)(ME + path, headers={"Authorization": "Bearer nope"}, **kwargs)
    assert resp.status_code == 401


def test_profile_setup_fields(client, token):
    resp = client.patch(
        ME + "/profile",
        headers=bearer(token),
        json={
            "portfolio_url": "https://ada.dev",
            "total_experience_years": 3,
            "career_gap": "under_6_months",
            "work_authorization_status": "citizen",
            "work_authorization_country": "in",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["portfolio_url"] == "https://ada.dev/"
    assert body["total_experience_years"] == 3.0
    assert body["work_authorization_country"] == "IN"
    bad = client.patch(ME + "/profile", headers=bearer(token), json={"career_gap": "forever"})
    assert bad.status_code == 422


def test_preferences_default_then_upsert(client, token):
    empty = client.get(ME + "/preferences", headers=bearer(token)).json()
    assert empty["updated_at"] is None and empty["preferred_job_titles"] == []
    assert empty["recruiter_visibility"] is False

    resp = client.patch(
        ME + "/preferences",
        headers=bearer(token),
        json={
            "employment_status": "fresher",
            "preferred_job_titles": ["Designer", "designer", "Researcher"],
            "preferred_work_types": ["remote", "hybrid"],
            "minimum_salary": 1200000,
            "maximum_salary": 1800000,
            "salary_currency": "inr",
            "salary_period": "yearly",
            "notice_period_days": 30,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["preferred_job_titles"] == ["Designer", "Researcher"]
    assert body["salary_currency"] == "INR"
    assert body["updated_at"] is not None

    resp = client.patch(
        ME + "/preferences",
        headers=bearer(token),
        json={"willing_to_relocate": True, "recruiter_visibility": True, "daily_job_match_digest": True},
    )
    body = resp.json()
    assert body["employment_status"] == "fresher"  # untouched by the partial update
    assert body["recruiter_visibility"] is True and body["willing_to_relocate"] is True


def test_salary_bounds_compare_exactly(client, token):
    base = {"salary_currency": "USD", "salary_period": "hourly"}
    assert client.patch(ME + "/preferences", headers=bearer(token), json={**base, "minimum_salary": 20, "maximum_salary": 25.10}).status_code == 200
    resp = client.patch(ME + "/preferences", headers=bearer(token), json={"minimum_salary": 25.1})
    assert resp.status_code == 200, resp.text
    assert resp.json()["minimum_salary"] == 25.1


@pytest.mark.parametrize(
    "payload",
    [
        {"minimum_salary": 1.234, "salary_currency": "USD", "salary_period": "yearly"},
        {"minimum_salary": 10, "maximum_salary": 5, "salary_currency": "USD", "salary_period": "yearly"},
        {"minimum_salary": 10},
        {"employment_status": "retired"},
        {"preferred_work_types": ["moon"]},
        {"recruiter_visibility": None},
        {},
    ],
)
def test_preferences_validation(client, token, payload):
    assert client.patch(ME + "/preferences", headers=bearer(token), json=payload).status_code == 422


EXP = {
    "company_name": "Acme",
    "job_title": "Designer",
    "employment_type": "full_time",
    "location_city": "Pune",
    "location_country": "IN",
    "start_date": "2022-01-01",
    "is_current": True,
    "description": "Owned the design system",
}


def test_experience_replace_keeps_ids_and_order(client, token):
    first = client.put(
        ME + "/experience",
        headers=bearer(token),
        json={"items": [EXP, {**EXP, "company_name": "Old Co", "is_current": False, "end_date": "2021-12-01", "start_date": "2019-06-01"}]},
    )
    assert first.status_code == 200, first.text
    acme, old = first.json()
    assert [acme["company_name"], old["company_name"]] == ["Acme", "Old Co"]

    second = client.put(
        ME + "/experience",
        headers=bearer(token),
        json={"items": [{**EXP, "id": acme["id"], "job_title": "Lead Designer"}]},
    )
    assert second.status_code == 200
    rows = client.get(ME + "/experience", headers=bearer(token)).json()
    assert len(rows) == 1 and rows[0]["id"] == acme["id"] and rows[0]["job_title"] == "Lead Designer"


@pytest.mark.parametrize(
    "item",
    [
        {**EXP, "end_date": "2023-01-01"},  # current role with an end date
        {**EXP, "is_current": False, "end_date": "2020-01-01"},  # ends before it starts
        {**EXP, "start_date": None},
        {**EXP, "company_name": "  "},
        {**EXP, "employment_type": "gig"},
    ],
)
def test_experience_validation(client, token, item):
    assert client.put(ME + "/experience", headers=bearer(token), json={"items": [item]}).status_code == 422


def test_cannot_touch_another_users_rows(client, token, other_token):
    acme = client.put(ME + "/experience", headers=bearer(token), json={"items": [EXP]}).json()[0]
    resp = client.put(
        ME + "/experience", headers=bearer(other_token), json={"items": [{**EXP, "id": acme["id"]}]}
    )
    assert resp.status_code == 404
    assert client.get(ME + "/experience", headers=bearer(other_token)).json() == []
    assert client.get(ME + "/experience", headers=bearer(token)).json()[0]["job_title"] == "Designer"


def test_skills_use_shared_catalogue(client, token, other_token):
    resp = client.put(
        ME + "/skills",
        headers=bearer(token),
        json={"items": [
            {"name": "Figma", "category": "tool"},
            {"name": "figma", "category": "technical"},
            {"name": "Communication", "category": "soft"},
        ]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == [
        {"name": "Communication", "category": "soft"},
        {"name": "Figma", "category": "tool"},
    ]
    other = client.put(
        ME + "/skills", headers=bearer(other_token), json={"items": [{"name": "FIGMA", "category": "tool"}]}
    )
    assert other.json() == [{"name": "Figma", "category": "tool"}]  # reuses the existing skill

    client.put(ME + "/skills", headers=bearer(token), json={"items": [{"name": "Python", "category": "technical"}]})
    assert [s["name"] for s in client.get(ME + "/skills", headers=bearer(token)).json()] == ["Python"]
    assert [s["name"] for s in client.get(ME + "/skills", headers=bearer(other_token)).json()] == ["Figma"]


def test_education_round_trip(client, token):
    resp = client.put(
        ME + "/education",
        headers=bearer(token),
        json={"items": [
            {"education_level": "bachelors", "degree_name": "B.Des", "institution_name": "NID", "start_year": 2015, "end_year": 2019},
            {"education_level": "masters", "degree_name": "M.Des", "institution_name": "IIT", "start_year": 2024, "end_year": 2026, "is_currently_studying": True},
        ]},
    )
    assert resp.status_code == 200, resp.text
    first, second = resp.json()
    assert first["education_level"] == "bachelors" and first["start_year"] == 2015 and first["end_year"] == 2019
    assert second["is_currently_studying"] is True
    bad = client.put(
        ME + "/education",
        headers=bearer(token),
        json={"items": [{"education_level": "phd-ish", "degree_name": "X", "institution_name": "Y"}]},
    )
    assert bad.status_code == 422


def test_certifications_round_trip(client, token):
    resp = client.put(
        ME + "/certifications",
        headers=bearer(token),
        json={"items": [{
            "certification_name": "AWS Certified Developer",
            "issuing_organization": "Amazon Web Services",
            "issue_date": "2024-03-01",
            "expiry_date": "2027-03-01",
            "credential_id": "ABC-123",
            "credential_url": "https://aws.amazon.com/verification",
        }, {"certification_name": "Google UX Design Certificate"}]},
    )
    assert resp.status_code == 200, resp.text
    assert [c["certification_name"] for c in resp.json()] == ["AWS Certified Developer", "Google UX Design Certificate"]
    bad = client.put(
        ME + "/certifications",
        headers=bearer(token),
        json={"items": [{"certification_name": "X", "issue_date": "2024-01-01", "expiry_date": "2023-01-01"}]},
    )
    assert bad.status_code == 422


def test_languages_round_trip_and_duplicates(client, token):
    resp = client.put(
        ME + "/languages",
        headers=bearer(token),
        json={"items": [
            {"language_name": "English", "proficiency_level": "native"},
            {"language_name": "Hindi", "proficiency_level": "professional"},
        ]},
    )
    assert resp.status_code == 200, resp.text
    english = resp.json()[0]
    # Re-adding a removed language under a new row in the same save must not clash.
    again = client.put(
        ME + "/languages",
        headers=bearer(token),
        json={"items": [{"language_name": "english", "proficiency_level": "intermediate"}]},
    )
    assert again.status_code == 200, again.text
    assert again.json()[0]["id"] != english["id"]
    dup = client.put(
        ME + "/languages",
        headers=bearer(token),
        json={"items": [
            {"language_name": "Telugu", "proficiency_level": "native"},
            {"language_name": "telugu", "proficiency_level": "basic"},
        ]},
    )
    assert dup.status_code == 422


def test_onboarding_progress(client, token):
    resp = client.patch(ME + "/onboarding", headers=bearer(token), json={"onboarding_step": 3})
    assert resp.status_code == 200
    assert resp.json()["onboarding_step"] == 3 and resp.json()["onboarding_status"] == "in_progress"
    done = client.patch(
        ME + "/onboarding", headers=bearer(token), json={"onboarding_step": 6, "onboarding_status": "completed"}
    ).json()
    assert done["onboarding_status"] == "completed"
    back = client.patch(ME + "/onboarding", headers=bearer(token), json={"onboarding_step": 1}).json()
    assert back["onboarding_status"] == "completed" and back["onboarding_step"] == 1
    assert client.patch(ME + "/onboarding", headers=bearer(token), json={"onboarding_step": 7}).status_code == 422
