"""T007: real SQLite/FastAPI foundation with synthetic, offline fixtures."""

import asyncio
import io
import json
import logging
import secrets
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from uuid import UUID

import httpx
import pytest
from fastapi import Depends, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import Column, Integer, MetaData, Table, func, inspect, select, text
from sqlalchemy.exc import IntegrityError, StatementError

from app.core.config import BACKEND_DIR, ConfigurationError, Settings, get_settings
from app.core.logging import SafeMetadataFormatter, logger
from app.db.base import Base, utc_now
from app.db.session import Database, get_session
from tests.conftest import FixtureBase, FixtureChild, FixtureParent


def assert_envelope(response, status, code):
    assert response.status_code == status
    data = response.json()
    assert set(data) == {"error", "request_id"}
    assert set(data["error"]) == {"code", "message", "details"}
    assert data["error"]["code"] == code
    assert data["error"]["details"] is None
    assert str(UUID(data["request_id"])) == response.headers["x-request-id"]
    return data


def test_settings_optional_gemini_and_fixed_stack(settings):
    assert settings.gemini_api_key is None
    assert settings.embedding_device == "cpu"
    assert settings.embedding_revision == "614241f622f53c4eeff9890bdc4f31cfecc418b3"
    assert settings.chat_deadline_seconds == 60
    assert settings.jwt_expire_minutes == 30
    assert settings.cors_origins == ["http://localhost:5173"]
    assert settings.jwt_secret.get_secret_value() not in repr(settings)


@pytest.mark.parametrize("secret", ["", "short", "a" * 64, "replace-me-" * 8])
def test_invalid_jwt_secret_is_blocked(secret):
    with pytest.raises(ValidationError) as error:
        Settings(jwt_secret=secret, _env_file=None)
    if secret:
        assert secret not in str(error.value)


def test_missing_jwt_fails_without_leaking_environment(monkeypatch):
    monkeypatch.delenv("JWT_SECRET")
    with pytest.raises(ConfigurationError, match="Invalid backend configuration"):
        get_settings()


@pytest.mark.parametrize("field,value", [
    ("database_url", "postgresql://private:credential@cloud/db"),
    ("database_url", "sqlite:///:memory:"),
    ("database_url", "sqlite:///file:remote?mode=memory&uri=true"),
    ("embedding_device", "cuda"), ("embedding_model", "other/model"),
    ("embedding_revision", "main"), ("gemini_model", "fallback-model"),
    ("jwt_algorithm", "none"), ("jwt_expire_minutes", 60),
    ("chat_deadline_seconds", 0), ("chat_deadline_seconds", 61),
    ("retrieval_min_similarity", float("nan")),
    ("ocr_page_timeout_seconds", 61), ("max_document_pages", 201),
    ("cors_origins", ["*"]), ("cors_origins", ["null"]),
    ("cors_origins", ["http://localhost:5173/path"]),
    ("cors_origins", ["https://user:credential@example.test"]),
])
def test_invalid_settings(field, value):
    with pytest.raises(ValidationError):
        Settings(**{field: value}, _env_file=None)


def test_env_file_precedence_and_relative_paths(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    file_secret = secrets.token_hex(32)
    env_file.write_text(
        f"JWT_SECRET={file_secret}\nGEMINI_API_KEY=\n"
        'CORS_ORIGINS=["http://localhost:5173","http://127.0.0.1:5173"]\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("JWT_SECRET")
    config = Settings(_env_file=env_file, model_cache_dir="data/test-models",
                      database_url="sqlite:///./data/relative.db")
    assert config.jwt_secret.get_secret_value() == file_secret
    assert config.gemini_api_key is None
    assert len(config.cors_origins) == 2
    assert config.model_cache_dir == BACKEND_DIR / "data/test-models"
    assert "relative.db" in config.database_url
    env_secret = secrets.token_hex(32)
    monkeypatch.setenv("JWT_SECRET", env_secret)
    assert Settings(_env_file=env_file).jwt_secret.get_secret_value() == env_secret


def test_examples_contain_no_credentials_and_only_frontend_api_url(monkeypatch):
    monkeypatch.delenv("JWT_SECRET")
    with pytest.raises(ValidationError):
        Settings(_env_file=BACKEND_DIR / ".env.example")
    config = Settings(_env_file=BACKEND_DIR / ".env.example", jwt_secret=secrets.token_hex(32))
    assert config.gemini_api_key is None
    assert (BACKEND_DIR.parent / "frontend/.env.example").read_text().strip() == (
        "VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1"
    )


def test_malformed_environment_error_is_sanitized(monkeypatch):
    marker = secrets.token_hex(20)
    monkeypatch.setenv("CORS_ORIGINS", marker)
    with pytest.raises(ConfigurationError) as error:
        get_settings()
    assert marker not in str(error.value)
    assert error.value.__suppress_context__


def test_pragmas_on_each_connection_and_reopen(database, settings):
    with database.engine.connect() as first, database.engine.connect() as second:
        for connection in (first, second):
            assert connection.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
            assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar() == 5000
    database.dispose()
    reopened = Database(settings)
    try:
        with reopened.engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    finally:
        reopened.dispose()


def test_initialize_twice_preserves_data_and_adds_only_missing_tables(database, fake_clock):
    with database.session() as session:
        parent = FixtureParent(label="GIẢ LẬP", created_at=fake_clock())
        session.add(parent)
        session.commit()
        parent_id = parent.id
    metadata = MetaData()
    Table("fixture_added_later", metadata, Column("id", Integer, primary_key=True))
    database.initialize(FixtureBase.metadata)
    database.initialize(metadata)
    database.initialize(metadata)
    with database.session() as session:
        assert session.get(FixtureParent, parent_id).label == "GIẢ LẬP"
    assert "fixture_added_later" in inspect(database.engine).get_table_names()
    # T008 registers identity tables without polluting the separate fixture metadata.
    assert set(Base.metadata.tables) == {"users", "auth_sessions"}
    assert "users" not in inspect(database.engine).get_table_names()


def test_uuid_and_utc_text_roundtrip(database, fake_clock):
    with database.session() as session:
        parent = FixtureParent(label="GIẢ LẬP", created_at=fake_clock().astimezone(
            timezone(timedelta(hours=7))))
        second = FixtureParent(label="GIẢ LẬP 2")
        session.add_all([parent, second])
        session.commit()
        assert str(UUID(parent.id)) == parent.id
        assert parent.id != second.id
        parent_id = parent.id
    with database.session() as session:
        parent = session.get(FixtureParent, parent_id)
        assert parent.created_at == fake_clock()
        assert parent.created_at.tzinfo is timezone.utc
        raw = session.execute(text("SELECT created_at FROM fixture_parents WHERE id=:id"),
                              {"id": parent_id}).scalar_one()
        assert raw.endswith("Z")
    assert utc_now().utcoffset() == timedelta(0)


def test_naive_timestamp_rejected_and_rolled_back(database):
    with pytest.raises(StatementError):
        with database.session() as session:
            session.add(FixtureParent(label="GIẢ LẬP", created_at=datetime(2026, 1, 1)))
            session.commit()
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(FixtureParent)) == 0


def test_foreign_keys_enforced_and_delete_cascades(database):
    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add(FixtureChild(parent_id="missing-fixture-parent"))
            session.commit()
    with database.session() as session:
        parent = FixtureParent(label="GIẢ LẬP")
        session.add(parent)
        session.flush()
        session.add(FixtureChild(parent_id=parent.id))
        session.commit()
        session.delete(parent)
        session.commit()
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(FixtureChild)) == 0


def test_exception_and_uncommitted_success_rollback(database):
    with pytest.raises(RuntimeError, match="synthetic failure"):
        with database.session() as session:
            session.add(FixtureParent(label="GIẢ LẬP"))
            session.flush()
            raise RuntimeError("synthetic failure")
    assert not session.in_transaction()
    with database.session() as session:
        session.add(FixtureParent(label="GIẢ LẬP"))
        session.flush()  # No commit: close must not persist implicitly.
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(FixtureParent)) == 0
    assert database.engine.pool.checkedout() == 0


def test_worker_sessions_are_independent(database):
    barrier = Barrier(2)

    def worker():
        with database.session() as session:
            assert session.scalar(select(func.count()).select_from(FixtureParent)) == 0
            barrier.wait(timeout=5)
            return session

    with ThreadPoolExecutor(max_workers=2) as pool:
        sessions = list(pool.map(lambda _: worker(), range(2)))
    assert sessions[0] is not sessions[1]
    assert database.engine.pool.checkedout() == 0


def test_init_cli_is_idempotent_and_sanitizes_failure(settings, monkeypatch, capsys):
    from app.cli import init_db

    assert init_db.main() == 0
    assert init_db.main() == 0
    assert "existing data preserved" in capsys.readouterr().out
    marker = secrets.token_hex(32)

    def fail(*args):
        raise RuntimeError(f"{marker} C:/private/data.db")

    monkeypatch.setattr(init_db, "get_settings", fail)
    assert init_db.main() == 1
    output = capsys.readouterr().out
    assert marker not in output and "C:/private" not in output


def test_health_without_key_and_no_domain_services(application, fake_ocr, fake_encoder, fake_gemini):
    with TestClient(application) as client:
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "embedding_ready": False,
                                  "ocr_available": False, "gemini_configured": False}
        assert str(UUID(response.headers["x-request-id"]))
        assert set(inspect(application.state.database.engine).get_table_names()) == {"users", "auth_sessions"}
        assert not hasattr(application.state, "scheduler")
    fake_ocr.assert_called_once()
    fake_encoder.encode.assert_not_called()
    fake_gemini.assert_not_called()


def test_health_has_no_secret_when_key_is_present(settings, monkeypatch):
    from app import main

    marker = secrets.token_hex(32)
    settings = Settings(gemini_api_key=marker, _env_file=None)
    monkeypatch.setattr(main, "probe_ocr", lambda _: True)
    with TestClient(main.create_app(settings)) as client:
        response = client.get("/api/v1/health")
        assert response.json()["gemini_configured"] is True
        assert response.json()["ocr_available"] is True
        assert marker not in response.text
        assert settings.jwt_secret.get_secret_value() not in response.text
        assert str(BACKEND_DIR) not in response.text


def test_request_session_cleanup_and_rollback(application):
    seen = []

    @application.get("/_fixture/session")
    def use_session(fail: bool = False, session=Depends(get_session)):
        seen.append(session)
        session.add(FixtureParent(label="GIẢ LẬP"))
        session.flush()
        if fail:
            raise RuntimeError("synthetic failure")
        session.commit()
        return {"ok": True}

    with TestClient(application) as client:
        application.state.database.initialize(FixtureBase.metadata)
        assert client.get("/_fixture/session").status_code == 200
        assert client.get("/_fixture/session?fail=true").status_code == 500
        assert seen[0] is not seen[1]
        with application.state.database.session() as session:
            assert session.scalar(select(func.count()).select_from(FixtureParent)) == 1
        assert application.state.database.engine.pool.checkedout() == 0


@pytest.mark.parametrize("origin,allowed", [
    ("http://localhost:5173", True), ("http://127.0.0.1:5173", False),
    ("https://evil.example", False), ("null", False),
])
def test_cors_allowlist_preflight_and_regular_requests(application, origin, allowed):
    with TestClient(application) as client:
        response = client.options("/api/v1/health", headers={
            "Origin": origin, "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization,Content-Type",
        })
        if allowed:
            assert response.status_code == 200
            assert response.headers["access-control-allow-origin"] == origin
            assert "access-control-allow-credentials" not in response.headers
        else:
            assert_envelope(response, 400, "CORS_REJECTED")
            assert "access-control-allow-origin" not in response.headers
            assert int(response.headers["content-length"]) == len(response.content)
        response = client.get("/api/v1/health", headers={"Origin": origin})
        assert ("access-control-allow-origin" in response.headers) is allowed


def test_validation_http_and_unexpected_errors_are_sanitized(application):
    marker = secrets.token_hex(32)

    class Input(BaseModel):
        model_config = ConfigDict(extra="forbid")
        count: int

    @application.post("/_fixture/input")
    def validate(body: Input):
        return {"count": body.count}

    @application.get("/_fixture/http/{status}")
    def fail_http(status: int):
        raise HTTPException(status, detail=f"{marker} C:/private/file.db")

    @application.get("/_fixture/error")
    def fail():
        raise RuntimeError(f"{marker} C:/private/file.db")

    with TestClient(application) as client:
        assert client.post("/_fixture/input", json={"count": 1}).json() == {"count": 1}
        responses = [
            (client.post("/_fixture/input", json={"count": marker}), 422, "VALIDATION_ERROR"),
            (client.post("/_fixture/input", json={"count": 1, "secret": marker}), 422, "VALIDATION_ERROR"),
            (client.post("/_fixture/input", content=marker,
                         headers={"Content-Type": "application/json"}), 422, "VALIDATION_ERROR"),
            (client.get("/missing?private=" + marker), 404, "NOT_FOUND"),
            (client.post("/api/v1/health"), 405, "METHOD_NOT_ALLOWED"),
            (client.get("/_fixture/http/401"), 401, "UNAUTHORIZED"),
            (client.get("/_fixture/http/403"), 403, "FORBIDDEN"),
            (client.get("/_fixture/error", headers={"Origin": "http://localhost:5173"}),
             500, "INTERNAL_SERVER_ERROR"),
        ]
        for response, status, code in responses:
            assert_envelope(response, status, code)
            assert marker not in response.text and "C:/private" not in response.text
            assert "Traceback" not in response.text
        assert responses[5][0].headers["www-authenticate"] == "Bearer"
        assert responses[-1][0].headers["access-control-allow-origin"] == "http://localhost:5173"


def test_request_ids_and_logs_do_not_reflect_guest_data(application):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(SafeMetadataFormatter())
    logger.addHandler(handler)
    marker = secrets.token_hex(32)

    @application.get("/_fixture/log-error")
    def fail():
        raise RuntimeError(f"{marker} C:/private/fixture.db")

    try:
        with TestClient(application) as client:
            first = client.get("/missing/" + marker + "?message=" + marker,
                               headers={"X-Request-ID": marker, "Authorization": "Bearer " + marker})
            second = client.post("/api/v1/health", json={"message": marker})
            failed = client.get("/_fixture/log-error")
            assert failed.status_code == 500
        assert first.headers["x-request-id"] != second.headers["x-request-id"]
        assert first.headers["x-request-id"] != marker
        output = stream.getvalue()
        assert marker not in output
        assert "Traceback" not in output and "C:/private" not in output
        records = [json.loads(line) for line in output.splitlines()]
        assert len(records) == 3
        assert all(set(record) == {"event", "request_id", "method", "status", "duration_ms"}
                   for record in records)
        assert logging.getLogger("uvicorn.access").disabled
    finally:
        logger.removeHandler(handler)


def test_log_formatter_drops_exception_message_and_untrusted_metadata():
    marker = secrets.token_hex(32)
    try:
        raise RuntimeError(marker)
    except RuntimeError:
        import sys

        record = logging.LogRecord("utc_admissions", logging.ERROR, marker, 1,
                                   marker, (), sys.exc_info())
    record.request_id = marker
    record.method = marker
    output = SafeMetadataFormatter().format(record)
    assert marker not in output
    assert "Traceback" not in output


@pytest.mark.parametrize("outcome", ["missing", "languages_missing", "timeout", "success"])
def test_ocr_availability_probe_without_ocr_pipeline(settings, monkeypatch, outcome):
    from app.api.routes import health

    monkeypatch.setattr(health.shutil, "which", lambda _: None if outcome == "missing" else "fixture-tesseract")

    def run(command, **kwargs):
        assert command == ["fixture-tesseract", "--list-langs"]
        assert kwargs["timeout"] == 5
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(command, 5)
        return subprocess.CompletedProcess(command, 0, stdout=("eng\nvie\n" if outcome == "success" else "eng\n"))

    monkeypatch.setattr(health.subprocess, "run", run)
    assert health.probe_ocr(settings) is (outcome == "success")


def test_external_network_blocked_and_fake_fixtures_available(
        fixture_data, fake_network, fake_encoder, fake_gemini):
    assert "GIẢ LẬP" in fixture_data["label"]
    with pytest.raises(RuntimeError, match="External network disabled"):
        socket.getaddrinfo("example.invalid", 443)
    with httpx.Client(transport=fake_network) as client:
        assert client.get("https://example.invalid").json()["fixture"] is True
    assert len(fake_encoder.encode("GIẢ LẬP")[0]) == 384
    assert "Synthetic" in asyncio.run(fake_gemini())["text"]
