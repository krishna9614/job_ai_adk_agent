"""Test fixtures.

Database tests run against a dedicated database named by TEST_DATABASE_URL (must contain
"test"). The tables are created from db/jobai_v1_schema.sql, which is idempotent.
Supabase Auth is replaced by tests.fakes.FakeAuthProvider.
"""

import os
from pathlib import Path

import psycopg
import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.orm import sessionmaker

from tests.fakes import FakeAuthProvider

load_dotenv()

SCHEMA_SQL = Path(__file__).resolve().parents[1] / "db" / "jobai_v1_schema.sql"


@pytest.fixture(scope="session")
def engine():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")
    parsed = make_url(url)
    if "test" not in (parsed.database or ""):
        pytest.exit(f"Refusing to run tests against non-test database {parsed.database!r}")
    # Settings require DATABASE_URL; point it at the test DB so nothing touches real data.
    os.environ["DATABASE_URL"] = url

    with psycopg.connect(parsed.set(drivername="postgresql").render_as_string(False)) as conn:
        conn.execute(SCHEMA_SQL.read_text())

    eng = create_engine(url)
    yield eng
    eng.dispose()


@pytest.fixture()
def db_session_factory(engine):
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE jobai.users CASCADE"))
    return sessionmaker(bind=engine, autoflush=False)


@pytest.fixture()
def auth_provider():
    return FakeAuthProvider()


@pytest.fixture()
def client(db_session_factory, auth_provider):
    from app.api.deps import get_auth_provider
    from app.db.session import get_db
    from app.main import app

    def _get_db():
        db = db_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_auth_provider] = lambda: auth_provider
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def signup(client):
    def _signup(email: str = "ada@example.com", password: str = "S3cure-pass!") -> dict:
        resp = client.post("/api/v1/auth/signup", json={"email": email, "password": password})
        assert resp.status_code == 201, resp.text
        return resp.json()

    return _signup


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
