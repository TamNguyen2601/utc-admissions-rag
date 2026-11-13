"""Offline defaults; all fixtures are synthetic and isolated from demo storage."""

import ipaddress
import json
import secrets
import socket
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import Settings
from app.db.base import CreatedAtMixin, UUIDMixin
from app.db.session import Database


class FixtureBase(DeclarativeBase):
    pass


class FixtureParent(UUIDMixin, CreatedAtMixin, FixtureBase):
    __tablename__ = "fixture_parents"
    label: Mapped[str] = mapped_column(String, nullable=False)


class FixtureChild(UUIDMixin, FixtureBase):
    __tablename__ = "fixture_children"
    parent_id: Mapped[str] = mapped_column(
        ForeignKey("fixture_parents.id", ondelete="CASCADE"), nullable=False
    )


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    # Never read a developer's .env or use their credentials/database in tests.
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)
        monkeypatch.delenv(field, raising=False)
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("JWT_SECRET", secrets.token_hex(32))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'foundation.db').as_posix()}")
    for name in ("DATA_DIR", "UPLOAD_DIR", "IMPORT_DIR", "MODEL_CACHE_DIR"):
        monkeypatch.setenv(name, str(tmp_path / name.lower()))


@pytest.fixture(autouse=True)
def offline_network(monkeypatch):
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def allowed(host):
        if isinstance(host, bytes):
            host = host.decode("ascii")
        if host == "localhost":
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    def guard_connect(sock, address):
        if isinstance(address, tuple) and not allowed(address[0]):
            raise RuntimeError("External network disabled in tests")
        return real_connect(sock, address)

    def guard_connect_ex(sock, address):
        if isinstance(address, tuple) and not allowed(address[0]):
            raise RuntimeError("External network disabled in tests")
        return real_connect_ex(sock, address)

    def guard_dns(host, *args, **kwargs):
        if host is not None and not allowed(host):
            raise RuntimeError("External network disabled in tests")
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guard_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guard_connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", guard_dns)


@pytest.fixture
def fixture_data():
    return json.loads((Path(__file__).parent / "fixtures/foundation.json").read_text(encoding="utf-8"))


@pytest.fixture
def fake_clock(fixture_data):
    return Mock(return_value=datetime.fromisoformat(fixture_data["clock_utc"]))


@pytest.fixture
def fake_network(fixture_data):
    return httpx.MockTransport(lambda request: httpx.Response(200, json=fixture_data["network_response"]))


@pytest.fixture
def fake_encoder():
    # Fixed unit vector only. No model load and no official data.
    return SimpleNamespace(encode=Mock(return_value=[[1.0] + [0.0] * 383]))


@pytest.fixture
def fake_gemini(fixture_data):
    return AsyncMock(return_value=fixture_data["gemini_response"])


@pytest.fixture
def fake_ocr():
    return Mock(return_value=False)


@pytest.fixture
def settings():
    return Settings(_env_file=None)


@pytest.fixture
def database(settings):
    database = Database(settings)
    database.initialize(FixtureBase.metadata)
    try:
        yield database
    finally:
        database.dispose()


@pytest.fixture
def application(settings, fake_ocr, monkeypatch):
    # Import only after the isolated valid environment is in place.
    from app import main

    monkeypatch.setattr(main, "probe_ocr", fake_ocr)
    return main.create_app(settings)
