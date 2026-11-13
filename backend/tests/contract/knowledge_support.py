"""GIẢ LẬP — KHÔNG PHẢI THÔNG TIN UTC. Indexing is a stub, never E5."""
from fastapi.testclient import TestClient
import pytest

from app.models.identity import Role, User


class IndexerStub:
    profile = {"stub": True, "revision": "synthetic-b1"}

    def __init__(self): self.calls = 0
    def extract(self, data, media_type): return data.decode("utf-8")
    def index(self, text, metadata): self.calls += 1
    def usable(self, document): return document.index_profile == self.profile and bool(document.content_text)


@pytest.fixture
def admin_client(application):
    with TestClient(application) as client:
        credentials = {"email": "admin@example.test", "password": "synthetic-password"}
        client.post("/api/v1/auth/register", json=credentials)
        with application.state.database.session() as db:
            from sqlalchemy import select
            user = db.scalar(select(User).where(User.email_normalized == credentials["email"]))
            user.role = Role.ADMIN; db.commit()
        token = client.post("/api/v1/auth/login", json=credentials).json()["access_token"]
        client.headers["Authorization"] = f"Bearer {token}"
        application.state.documents.indexer = IndexerStub()
        yield client


def source_payload(**changes):
    return dict(name="SYNTHETIC permission", kind="upload", base_url=None, allowed_paths=[], enabled=True,
                permission_status="allowed", robots_url=None, terms_url=None,
                reuse_basis="Synthetic test permission only", checked_at="2026-01-01T00:00:00Z",
                min_interval_seconds=2) | changes


def create_source(client, **changes):
    response = client.post("/api/v1/admin/sources", json=source_payload(**changes))
    assert response.status_code == 201, response.text
    return response.json()


def upload(client, source_id, content=b"SYNTHETIC document, no official facts", **changes):
    data = {"title": "SYNTHETIC", "source_id": source_id, "provenance_note": "Synthetic private note"} | changes
    return client.post("/api/v1/admin/documents/upload", data=data,
                       files={"file": ("../../escape.txt", content, "text/plain")})


def resolve_document(client, receipt):
    from app.models.knowledge import DocumentOrigin
    with client.app.state.database.session() as db:
        return db.get(DocumentOrigin, receipt.json()["origin_id"]).document_id
