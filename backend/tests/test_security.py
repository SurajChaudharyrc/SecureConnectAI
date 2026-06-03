from backend.app.security import (
    CSRF_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    generate_csrf_token,
    generate_session_token,
    hash_password,
    hash_token,
    verify_csrf_token,
    verify_password,
)
from backend.tests.conftest import register_and_login


def test_bcrypt_password_roundtrip():
    h = hash_password("Password1234")
    assert h != "Password1234"
    assert verify_password("Password1234", h) is True
    assert verify_password("Password1235", h) is False


def test_session_token_stored_as_hash_only():
    raw, hashed = generate_session_token()
    assert raw != hashed
    assert hashed == hash_token(raw)
    assert len(hashed) == 64  # sha256 hex


def test_csrf_signed_roundtrip():
    token = generate_csrf_token()
    assert verify_csrf_token(token) is True
    assert verify_csrf_token("tampered") is False


def test_security_headers_present(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert "Content-Security-Policy" in r.headers
    assert r.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


def test_csrf_required_on_state_change(client):
    register_and_login(client, "csrf_user")
    # Strip the CSRF header that register_and_login auto-attached, so the
    # request mimics a hostile cross-origin POST without the double-submit token.
    client.headers.pop("X-CSRF-Token", None)
    r = client.patch("/api/profile", json={"full_name": "Mallory"})
    assert r.status_code == 403


def test_csrf_double_submit_succeeds(client):
    register_and_login(client, "csrf_ok")
    csrf = client.cookies.get(CSRF_COOKIE_NAME)
    r = client.patch(
        "/api/profile",
        json={"full_name": "Updated"},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 200, r.text
    assert r.json()["full_name"] == "Updated"
