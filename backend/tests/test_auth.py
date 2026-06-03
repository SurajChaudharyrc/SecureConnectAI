from backend.tests.conftest import register_and_login


def test_register_then_me(client):
    user = register_and_login(client, "alice")
    assert user["username"] == "alice"
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == "alice"


def test_register_duplicate_rejected(client):
    register_and_login(client, "alice")
    r = client.post(
        "/api/auth/register",
        json={
            "username": "alice",
            "email": "alice2@example.com",
            "password": "Password1234",
            "full_name": "Alice",
        },
    )
    assert r.status_code == 409


def test_login_wrong_password(client):
    register_and_login(client, "alice")
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"username": "alice", "password": "wrong"})
    assert r.status_code == 401


def test_logout_invalidates_session(client):
    register_and_login(client, "alice")
    r = client.post("/api/auth/logout")
    assert r.status_code == 200
    # After logout, /me should be 401.
    r2 = client.get("/api/auth/me")
    assert r2.status_code == 401


def test_password_validation_blocks_weak(client):
    r = client.post(
        "/api/auth/register",
        json={
            "username": "weak",
            "email": "w@example.com",
            "password": "short",
            "full_name": "Weak",
        },
    )
    assert r.status_code == 422
