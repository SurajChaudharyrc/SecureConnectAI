"""Pytest fixtures.

Each test gets its own SQLite file, the limiter is disabled (so test order
doesn't matter), and DeepFace is forced off so the test suite never has to
load TensorFlow.
"""
from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator

import pytest

# Configure environment BEFORE importing the app.
_tmp_dir = tempfile.mkdtemp(prefix="sc_tests_")
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("APP_SECRET", "x" * 64)
os.environ.setdefault("DATABASE_URL", f"sqlite:///{os.path.join(_tmp_dir, 'test.db')}")
os.environ.setdefault("DEEPFACE_ENABLED", "false")
os.environ.setdefault("MAX_UPLOAD_BYTES", str(2 * 1024 * 1024))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from backend.app import db as db_module  # noqa: E402
from backend.app.db import Base, get_db  # noqa: E402
from backend.app.main import app  # noqa: E402
from backend.app.rate_limit import limiter  # noqa: E402


@pytest.fixture()
def fresh_db(tmp_path) -> Iterator[sessionmaker]:
    """Use a fresh SQLite file for this test only."""
    db_path = tmp_path / "test.db"
    test_engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=test_engine)
    TestSession = sessionmaker(bind=test_engine, autoflush=False, autocommit=False, expire_on_commit=False)

    def _override():
        s = TestSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override
    # Also point module-level SessionLocal at this engine, so seed-style helpers
    # share the same store. (Most tests use the dependency override above.)
    original_engine = db_module.engine
    original_local = db_module.SessionLocal
    db_module.engine = test_engine
    db_module.SessionLocal = TestSession

    yield TestSession

    db_module.engine = original_engine
    db_module.SessionLocal = original_local
    app.dependency_overrides.pop(get_db, None)
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture()
def client(fresh_db) -> Iterator[TestClient]:
    # Disable rate limiting for predictable tests.
    limiter.enabled = False
    try:
        with TestClient(app) as c:
            yield c
    finally:
        limiter.enabled = True


def register_and_login(client: TestClient, username: str = "tester", password: str = "Password1234"):
    """Helper: register, return the user dict. Auto-attaches CSRF header so
    subsequent state-changing calls succeed (same as the real frontend)."""
    r = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": password,
            "full_name": "Test User",
        },
    )
    assert r.status_code == 201, r.text
    csrf = client.cookies.get("sc_csrf")
    if csrf:
        client.headers["X-CSRF-Token"] = csrf
    return r.json()
