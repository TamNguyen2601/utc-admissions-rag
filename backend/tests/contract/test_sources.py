"""B1 source API contract, synthetic registry, no live requests."""
import pytest
from fastapi import HTTPException

from tests.contract.knowledge_support import admin_client, create_source, source_payload
from app.services.sources import canonical_url, checked_fetch_url, validate_source_url
from app.models.knowledge import DataSource


def test_source_list_patch_and_strictness(admin_client):
    source = create_source(admin_client)
    assert set(source) == set(source_payload()) | {"id", "retry_not_before", "last_success_at"}
    response = admin_client.get("/api/v1/admin/sources?page_size=1").json()
    assert response == {"items": [source], "total": 1, "page": 1, "page_size": 1}
    path = f"/api/v1/admin/sources/{source['id']}"
    assert admin_client.patch(path, json={"enabled": False, "permission_status": "denied"}).status_code == 200
    assert admin_client.patch(path, json={"enabled": True}).status_code == 422
    assert admin_client.patch(path, json={"unknown": 1}).status_code == 422
    assert admin_client.patch(path, json={"name": None}).status_code == 422
    assert admin_client.get("/api/v1/admin/sources?page=0").status_code == 422


@pytest.mark.parametrize("changes", [
    {"permission_status": "unknown"}, {"permission_status": "denied"}, {"reuse_basis": " "},
    {"checked_at": None}, {"checked_at": "2026-01-01"}, {"min_interval_seconds": 1.9},
    {"base_url": "http://example.org"}, {"base_url": "https://127.0.0.1"},
    {"kind": "utc", "base_url": "https://evil.example.org", "allowed_paths": ["/"]},
    {"kind": "career", "base_url": "https://example.org", "allowed_paths": ["/"]},
    {"kind": "career", "base_url": "https://example.org", "allowed_paths": ["/../private"]},
    {"extra": True}, {"enabled": "true"},
])
def test_source_invalid_input(admin_client, changes):
    assert admin_client.post("/api/v1/admin/sources", json=source_payload(**changes)).status_code == 422


def test_url_scope_tracking_dns_and_redirect_gate(admin_client, monkeypatch):
    source = create_source(admin_client, kind="career", base_url="https://example.org/jobs/",
        allowed_paths=["/jobs"], robots_url="https://example.org/robots.txt", terms_url="https://example.org/terms")
    with admin_client.app.state.database.session() as db:
        model = db.get(DataSource, source["id"])
        url = validate_source_url(model, "HTTPS://EXAMPLE.ORG/jobs/a?year=2026&utm_source=test#frag")
        assert url == "https://example.org/jobs/a?year=2026"
        for url in ["https://evil.example.org/jobs", "https://example.org/jobs-evil", "https://example.org/jobs/%2e%2e/private"]:
            with pytest.raises(HTTPException): validate_source_url(model, url)
        # Career is import-only, never a fetch adapter.
        with pytest.raises(HTTPException): checked_fetch_url(model, "https://example.org/jobs")
        model.kind = "utc"; model.base_url = "https://tuyensinh.utc.edu.vn"; model.allowed_paths_json = ["/"]
        import socket
        monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 443))])
        with pytest.raises(HTTPException): checked_fetch_url(model, "https://tuyensinh.utc.edu.vn/a")
        monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))])
        assert checked_fetch_url(model, "https://tuyensinh.utc.edu.vn/a").endswith("/a")
        with pytest.raises(HTTPException): checked_fetch_url(model, "https://127.0.0.1/private")


@pytest.mark.parametrize("url", ["https://localhost/a", "https://[::1]/", "https://169.254.169.254/", "https://10.0.0.1/",
    "https://user:password@example.org/", "https://example.org:8000/", "https://example.org/a\\b", "https://example.org/%252e%252e/a"])
def test_private_and_ambiguous_urls(url):
    with pytest.raises(ValueError): canonical_url(url)
