"""T008–T012/Q02: real SQLite, Argon2id, JWT and dependencies; synthetic identities.

Probe routes exist only in this test application. No conversation/Admin module is built.
"""

import secrets
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError

from app.api.deps import optional_auth, require_admin, required_auth, require_owner
from app.cli import create_admin, init_db
from app.core.security import hash_password, verify_password
from app.db.base import utc_now
from app.db.session import Database
from app.models.identity import AuthSession, Role, User
from app.schemas.auth import Credentials
from app.services.auth import register


@pytest.fixture
def setup(application, settings):
    @application.get("/test/optional")
    def optional(identity=Depends(optional_auth)):
        return {"id": identity.user.id if identity else None}

    @application.get("/test/admin")
    def admin(identity=Depends(require_admin)):
        return {"id": identity.user.id}

    @application.get("/test/owner/{owner_id}")
    def owner(owner_id: str, identity=Depends(required_auth)):
        require_owner(identity.user, None if owner_id == "missing" else owner_id)
        return {"id": owner_id}

    with TestClient(application) as client:
        database = application.state.database
        users = []
        headers = []
        tokens = []
        for index, role in enumerate([Role.USER, Role.USER, Role.ADMIN]):
            credentials = Credentials(email=f"synthetic{index}@example.test", password=secrets.token_urlsafe(16))
            with database.session() as db:
                users.append(register(db, credentials, role=role))
            response = client.post("/api/v1/auth/login", json=credentials.model_dump())
            assert response.status_code == 200
            token = response.json()["access_token"]
            tokens.append(token)
            headers.append({"Authorization": f"Bearer {token}"})
        yield SimpleNamespace(client=client, db=database, settings=settings,
                              users=users, headers=headers, tokens=tokens)


def signed(setup, claims):
    return jwt.encode(claims, setup.settings.jwt_secret.get_secret_value(), algorithm="HS256")


def claims_for(setup):
    return jwt.decode(setup.tokens[0], setup.settings.jwt_secret.get_secret_value(),
                      algorithms=["HS256"], audience=setup.settings.jwt_audience,
                      issuer=setup.settings.jwt_issuer)


def assert_unauthorized(response):
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["details"] is None


def test_rbac_and_ownership(setup):
    client = setup.client
    assert client.get("/test/optional").json() == {"id": None}
    for path in ("/test/admin", "/api/v1/auth/me", f"/test/owner/{setup.users[0].id}"):
        assert_unauthorized(client.get(path))
    for index, headers in enumerate(setup.headers):
        assert client.get("/test/admin", headers=headers).status_code == (200 if index == 2 else 403)
        assert client.get("/test/optional", headers=headers).json() == {"id": setup.users[index].id}
        for user in setup.users:
            response = client.get(f"/test/owner/{user.id}", headers=headers)
            assert response.status_code == (200 if user.id == setup.users[index].id else 404)
        assert client.get("/test/owner/missing", headers=headers).status_code == 404


@pytest.mark.parametrize("header", ["Bearer invalid", "Bearer", "", "Basic anything", "Bearer a b"])
def test_invalid_auth_never_becomes_guest(setup, header):
    for path in ("/test/optional", "/test/admin", "/api/v1/auth/me"):
        assert_unauthorized(setup.client.get(path, headers={"Authorization": header}))


def test_duplicate_authorization_headers(setup):
    assert_unauthorized(setup.client.get("/test/optional", headers=[
        ("Authorization", f"Bearer {setup.tokens[0]}"),
        ("Authorization", f"Bearer {setup.tokens[2]}"),
    ]))


@pytest.mark.parametrize("change", [
    {"exp": 1}, {"aud": "wrong"}, {"aud": ["utc-admissions-web"]}, {"iss": "wrong"},
    {"sid": str(uuid4())}, {"sub": str(uuid4())}, {"sub": "invalid"}, {"sid": "invalid"},
    {"iat": 9999999999}, {"iat": "1"}, {"exp": "9999999999"},
    {"iat": 1, "exp": 9999999999},
])
def test_invalid_claims(setup, change):
    token = signed(setup, {**claims_for(setup), **change})
    assert_unauthorized(setup.client.get("/test/optional", headers={"Authorization": f"Bearer {token}"}))


@pytest.mark.parametrize("claim", ["sub", "sid", "iat", "exp", "iss", "aud"])
def test_required_claims(setup, claim):
    claims = claims_for(setup)
    del claims[claim]
    assert_unauthorized(setup.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {signed(setup, claims)}"}))


def test_forged_signature_algorithm_and_role(setup):
    claims = claims_for(setup)
    for token in (
        jwt.encode(claims, secrets.token_hex(32), algorithm="HS256"),
        jwt.encode(claims, setup.settings.jwt_secret.get_secret_value(), algorithm="HS384"),
        jwt.encode(claims, "", algorithm="none"),
    ):
        assert_unauthorized(setup.client.get("/test/optional", headers={"Authorization": f"Bearer {token}"}))
    token = signed(setup, {**claims, "role": "ADMIN"})
    assert setup.client.get("/test/admin", headers={"Authorization": f"Bearer {token}"}).status_code == 403


def test_db_role_active_and_session_authoritative(setup):
    with setup.db.session() as db:
        admin = db.get(User, setup.users[2].id)
        admin.role = Role.USER
        db.commit()
    assert setup.client.get("/test/admin", headers=setup.headers[2]).status_code == 403
    with setup.db.session() as db:
        user = db.get(User, setup.users[0].id)
        user.active = False
        db.commit()
    assert_unauthorized(setup.client.get("/api/v1/auth/me", headers=setup.headers[0]))
    with setup.db.session() as db:
        user = db.get(User, setup.users[0].id)
        user.active = True
        session = db.get(AuthSession, claims_for(setup)["sid"])
        session.expires_at = utc_now() - timedelta(seconds=1)
        db.commit()
    assert_unauthorized(setup.client.get("/api/v1/auth/me", headers=setup.headers[0]))


def test_inactive_login_and_logout_only_one_sid(setup):
    credentials = Credentials(email="sessions@example.test", password=secrets.token_urlsafe(16))
    with setup.db.session() as db:
        user = register(db, credentials)
    tokens = [setup.client.post("/api/v1/auth/login", json=credentials.model_dump()).json()["access_token"] for _ in range(2)]
    headers = [{"Authorization": f"Bearer {token}"} for token in tokens]
    assert setup.client.post("/api/v1/auth/logout", headers=headers[0]).status_code == 204
    assert_unauthorized(setup.client.get("/api/v1/auth/me", headers=headers[0]))
    assert setup.client.get("/api/v1/auth/me", headers=headers[1]).status_code == 200
    with setup.db.session() as db:
        db.get(User, user.id).active = False
        db.commit()
    assert_unauthorized(setup.client.post("/api/v1/auth/login", json=credentials.model_dump()))


def test_session_claims_revoke_persists_and_token_not_stored(setup):
    from app.services.auth import authenticate

    claims = claims_for(setup)
    assert set(claims) == {"sub", "sid", "iat", "exp", "iss", "aud"}
    assert claims["exp"] - claims["iat"] == 1800
    assert claims["sub"] == setup.users[0].id
    assert setup.client.post("/api/v1/auth/logout", headers=setup.headers[0]).status_code == 204
    reopened = Database(setup.settings)
    reopened.initialize()
    try:
        with reopened.session() as db:
            session = db.get(AuthSession, claims["sid"])
            assert session.revoked_at is not None
            assert session.expires_at.tzinfo is not None
            with pytest.raises(Exception) as error:
                authenticate(db, setup.settings, setup.tokens[0])
            assert error.value.status_code == 401
        with reopened.engine.connect() as connection:
            rows = connection.exec_driver_sql("SELECT * FROM auth_sessions").all()
            assert setup.tokens[0] not in str(rows)
    finally:
        reopened.dispose()


def test_database_constraints_hash_and_persistence(settings):
    database = Database(settings)
    database.initialize()
    password = secrets.token_urlsafe(20)
    encoded = hash_password(password)
    assert encoded.startswith("$argon2id$") and password not in encoded
    assert verify_password(password, encoded)
    assert not verify_password("wrong-password", encoded)
    assert not verify_password(password, "invalid-hash")
    with database.session() as db:
        user = register(db, Credentials(email="stored@example.test", password=password))
        user_id = user.id
        for statement, params in [
            ("INSERT INTO users(id,email_normalized,password_hash,role,active,created_at) VALUES(:id,:email,:hash,'USER',1,:now)", {"email": user.email_normalized}),
            ("INSERT INTO users(id,email_normalized,password_hash,role,active,created_at) VALUES(:id,'bad@example.test',:hash,'ROOT',1,:now)", {}),
            ("INSERT INTO auth_sessions(id,user_id,expires_at,created_at) VALUES(:id,'missing',:now,:now)", {}),
        ]:
            with pytest.raises(IntegrityError):
                db.execute(text(statement), {"id": str(uuid4()), "hash": encoded, "now": utc_now().isoformat(), **params})
                db.commit()
            db.rollback()
    database.initialize()
    database.dispose()
    reopened = Database(settings)
    reopened.initialize()
    try:
        with reopened.session() as db:
            assert db.get(User, user_id).password_hash.startswith("$argon2id$")
            assert db.scalar(select(func.count()).select_from(User)) == 1
        assert {c["name"] for c in inspect(reopened.engine).get_columns("auth_sessions")} == {
            "id", "user_id", "expires_at", "revoked_at", "created_at"}
    finally:
        reopened.dispose()


def test_cli_admin_and_no_secret_output(settings, monkeypatch, capsys):
    password = secrets.token_urlsafe(20)
    monkeypatch.setattr("builtins.input", lambda prompt: "  Local.Admin@Example.test  ")
    monkeypatch.setattr(create_admin.getpass, "getpass", lambda prompt: password)
    assert init_db.main() == 0
    assert create_admin.main() == 0
    assert create_admin.main() == 1  # Never promotes/replaces an existing account.
    assert password not in capsys.readouterr().out
    db = Database(settings)
    try:
        with db.session() as session:
            admin = session.scalar(select(User))
            assert admin.role == Role.ADMIN and admin.email_normalized == "local.admin@example.test"
            assert verify_password(password, admin.password_hash)
            assert session.scalar(select(func.count()).select_from(User)) == 1
    finally:
        db.dispose()


def test_cli_invalid_and_insecure_prompt(monkeypatch, capsys):
    import warnings

    monkeypatch.setattr("builtins.input", lambda prompt: "invalid")
    monkeypatch.setattr(create_admin.getpass, "getpass", lambda prompt: "short")
    assert create_admin.main() == 1

    def insecure(prompt):
        warnings.warn("no terminal", create_admin.getpass.GetPassWarning)
        raise AssertionError("Must stop before echo fallback")

    monkeypatch.setattr(create_admin.getpass, "getpass", insecure)
    assert create_admin.main() == 1
    assert "secure password prompt" in capsys.readouterr().out


def test_auth_no_secret_leaks(application, settings, caplog, capsys):
    password = secrets.token_urlsafe(20)
    with TestClient(application) as client:
        credentials = {"email": "private@example.test", "password": password}
        client.post("/api/v1/auth/register", json=credentials)
        token = client.post("/api/v1/auth/login", json=credentials).json()["access_token"]
        for response in (
            client.post("/api/v1/auth/register", json={**credentials, "role": "ADMIN"}),
            client.post("/api/v1/auth/login", json={**credentials, "password": "wrong-password"}),
            client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}broken"}),
        ):
            for secret in (password, token, settings.jwt_secret.get_secret_value()):
                assert secret not in response.text
    logs = caplog.text + capsys.readouterr().err
    for secret in (password, token, settings.jwt_secret.get_secret_value()):
        assert secret not in logs
