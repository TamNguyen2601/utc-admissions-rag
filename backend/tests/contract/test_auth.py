"""T012: synthetic auth API contract, no external services."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(application):
    with TestClient(application) as client:
        yield client


def test_register_login_me_logout(client):
    credentials = {"email": "  Student@Example.test  ", "password": "test-password"}
    registered = client.post("/api/v1/auth/register", json=credentials)
    assert registered.status_code == 201
    user = registered.json()
    assert set(user) == {"id", "email", "role"}
    assert user["email"] == "student@example.test"
    assert user["role"] == "USER"
    assert client.post("/api/v1/auth/register", json=credentials).status_code == 409
    login = client.post("/api/v1/auth/login", json=credentials)
    assert login.status_code == 200
    data = login.json()
    assert set(data) == {"access_token", "token_type", "expires_in", "user"}
    assert data["token_type"] == "bearer" and data["expires_in"] == 1800
    assert data["user"] == user
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    assert client.get("/api/v1/auth/me", headers=headers).json() == user
    response = client.post("/api/v1/auth/logout", headers=headers)
    assert response.status_code == 204 and response.content == b""
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


@pytest.mark.parametrize("changes", [
    {"role": "ADMIN"}, {"email": "invalid"}, {"email": "a@@example.test"},
    {"email": "a@-invalid.test"}, {"password": "short"}, {"password": "x" * 129},
    {"password": 12345678}, {"email": None},
])
@pytest.mark.parametrize("action", ["register", "login"])
def test_strict_credentials(client, changes, action):
    response = client.post(f"/api/v1/auth/{action}", json={
        "email": "synthetic@example.test", "password": "test-password", **changes,
    })
    assert response.status_code == 422
    assert response.json()["error"]["details"] is None


def test_invalid_credentials_are_generic(client):
    credentials = {"email": "synthetic@example.test", "password": "test-password"}
    missing = client.post("/api/v1/auth/login", json=credentials)
    client.post("/api/v1/auth/register", json=credentials)
    wrong = client.post("/api/v1/auth/login", json={**credentials, "password": "wrong-password"})
    for response in (missing, wrong):
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert missing.json()["error"] == wrong.json()["error"]


@pytest.mark.parametrize("password", ["x" * 8, "x" * 128])
def test_password_boundaries(client, password):
    credentials = {"email": "boundary@example.test", "password": password}
    assert client.post("/api/v1/auth/register", json=credentials).status_code == 201
    assert client.post("/api/v1/auth/login", json=credentials).status_code == 200


@pytest.mark.parametrize("action", ["register", "login"])
def test_invalid_bearer_on_public_auth(client, action):
    response = client.post(f"/api/v1/auth/{action}",
                           headers={"Authorization": "Bearer invalid"},
                           json={"email": "public@example.test", "password": "test-password"})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
