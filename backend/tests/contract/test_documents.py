"""B1 contract-stub acceptance; NOT real ingestion, embedding or retrieval."""
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.db.session import Database
from app.models.crawl import CrawlRun, CrawlRunItem
from app.models.knowledge import Document, DocumentOrigin
from tests.contract.knowledge_support import admin_client, create_source, upload, resolve_document


def test_identity_context_notes_and_reopen(admin_client):
    source = create_source(admin_client)
    receipts = [upload(admin_client, source["id"], provenance_note=note,
                       source_url="https://example.org/source?year=2026&utm_source=test")
                for note in ["  Synthetic first note  ", "Synthetic second note", "Synthetic second note"]]
    assert all(r.status_code == 202 for r in receipts)
    ids = [r.json()["origin_id"] for r in receipts]
    assert len(set(ids)) == 3
    assert all(str(UUID(value)) == value for value in ids)
    document_id = resolve_document(admin_client, receipts[0])
    assert all(resolve_document(admin_client, r) == document_id for r in receipts)
    assert admin_client.app.state.documents.indexer.calls == 1
    with admin_client.app.state.database.session() as db:
        first_run = db.get(CrawlRun, receipts[0].json()["run_id"])
        assert first_run.new_count == 1 and first_run.updated_count == 0 and first_run.state == "succeeded"
        assert all(db.get(CrawlRun, r.json()["run_id"]).skipped_count == 1 for r in receipts[1:])
    detail = admin_client.get(f"/api/v1/admin/documents/{document_id}").json()
    assert detail["provenance_note"] == "Synthetic first note"
    assert [o["provenance_note"] for o in detail["origins"]] == ["Synthetic first note", "Synthetic second note", "Synthetic second note"]
    assert all(o["origin_kind"] == "upload" for o in detail["origins"])
    assert all(o["canonical_url"] == "https://example.org/source?year=2026" for o in detail["origins"])
    assert detail["state"] == "ready" and detail["index_profile"]["stub"] is True
    different = upload(admin_client, source["id"], year="2026", campus="Synthetic campus")
    assert different.status_code == 202
    assert resolve_document(admin_client, different) != document_id
    assert admin_client.app.state.documents.indexer.calls == 2
    # New engine, same file: UUID/note survive a database reopen, not an ORM cache.
    reopened = Database(admin_client.app.state.settings); reopened.initialize()
    with reopened.session() as db:
        origins = db.scalars(select(DocumentOrigin).where(DocumentOrigin.document_id == document_id)).all()
        assert {o.id for o in origins} == set(ids)
        assert {o.provenance_note for o in origins} == {"Synthetic first note", "Synthetic second note"}
    reopened.dispose()
    listing = admin_client.get("/api/v1/admin/documents?q=example.org&state=ready&page_size=1").json()
    assert listing["total"] == 1 and "content_text" not in listing["items"][0]


def test_disable_enable_delete_and_reimport(admin_client):
    source = create_source(admin_client)
    first = upload(admin_client, source["id"])
    document_id = resolve_document(admin_client, first)
    path = f"/api/v1/admin/documents/{document_id}"
    origin_id = first.json()["origin_id"]
    assert admin_client.get(path).json()["origins"][0]["canonical_url"] == f"urn:upload:{origin_id}"
    original = admin_client.get(path + "/original")
    assert original.status_code == 200 and original.content.startswith(b"SYNTHETIC")
    assert "escape" not in original.headers["content-disposition"]
    assert admin_client.post(path + "/disable", json={"reason": "Synthetic disable"}).json()["enabled"] is False
    second = upload(admin_client, source["id"], provenance_note="Another supplier")
    assert resolve_document(admin_client, second) == document_id
    assert admin_client.get(path).json()["enabled"] is False
    assert admin_client.post(path + "/enable", json={"reason": "Synthetic enable"}).json()["enabled"] is True
    assert admin_client.delete(path).status_code == 204
    assert admin_client.get(path).status_code == 404
    assert admin_client.post(path + "/enable", json={"reason": "Synthetic"}).status_code == 404
    with admin_client.app.state.database.session() as db:
        assert not db.scalars(select(DocumentOrigin)).all()
        assert all(i.document_id is None for i in db.scalars(select(CrawlRunItem)))
    assert not list(admin_client.app.state.settings.upload_dir.iterdir())
    third = upload(admin_client, source["id"])
    assert third.status_code == 202 and resolve_document(admin_client, third) != document_id


@pytest.mark.parametrize("changes", [{"provenance_note": " "}, {"provenance_note": "x" * 2001},
    {"source_url": "http://example.org"}, {"source_url": ""}, {"origin_id": str(uuid4())}, {"year": "bad"},
    {"publisher": " "}, {"published_at": "2026-01-01"}, {"title": " "}])
def test_upload_metadata_validation(admin_client, changes):
    source = create_source(admin_client)
    assert upload(admin_client, source["id"], **changes).status_code == 422


@pytest.mark.parametrize("length", [1, 2000])
def test_note_boundaries_and_nfc(admin_client, length):
    source = create_source(admin_client)
    response = upload(admin_client, source["id"], provenance_note="e\u0301" * length)
    assert response.status_code == 202
    detail = admin_client.get(f"/api/v1/admin/documents/{resolve_document(admin_client, response)}").json()
    assert detail["provenance_note"] == "é" * length


def test_url_without_note_and_missing_provenance(admin_client):
    source = create_source(admin_client)
    data = {"title": "SYNTHETIC", "source_id": source["id"]}
    files = {"file": ("test.txt", b"SYNTHETIC", "text/plain")}
    assert admin_client.post("/api/v1/admin/documents/upload", data=data, files=files).status_code == 422
    response = admin_client.post("/api/v1/admin/documents/upload", data=data | {"source_url": "https://example.org/a"}, files=files)
    assert response.status_code == 202


def test_upload_limits_magic_and_file_names(admin_client):
    source = create_source(admin_client)
    assert upload(admin_client, source["id"], content=b"x" * (20 * 1024 * 1024)).status_code == 202
    assert upload(admin_client, source["id"], content=b"x" * (20 * 1024 * 1024 + 1)).status_code == 413
    assert upload(admin_client, source["id"], content=b"\xff\xfe").status_code == 415
    data = {"source_id": source["id"], "title": "SYNTHETIC", "provenance_note": "SYNTHETIC"}
    for name, content, media in [("a.exe", b"MZ", "application/octet-stream"), ("a.pdf", b"not PDF", "application/pdf"),
                                  ("a.png", b"not PNG", "image/png"), ("a.jpg", b"not JPEG", "image/jpeg")]:
        assert admin_client.post("/api/v1/admin/documents/upload", data=data,
                                 files={"file": (name, content, media)}).status_code == 415
    assert not (admin_client.app.state.settings.upload_dir.parent / "escape.txt").exists()


def test_unknown_source_pending_default_and_public_privacy(admin_client):
    source = create_source(admin_client, enabled=False, permission_status="unknown", reuse_basis=None, checked_at=None)
    assert upload(admin_client, source["id"]).status_code == 422
    assert upload(admin_client, str(uuid4())).status_code == 404
    source = create_source(admin_client)
    admin_client.app.state.documents.indexer = None
    receipt = upload(admin_client, source["id"])
    assert receipt.status_code == 202
    identity = resolve_document(admin_client, receipt)
    path = f"/api/v1/admin/documents/{identity}"
    detail = admin_client.get(path).json()
    assert detail["state"] == "pending" and detail["quality_reason"] == "INDEXER_NOT_IMPLEMENTED"
    assert detail["content_hash"] is None
    assert admin_client.post(path + "/enable", json={"reason": "Synthetic"}).status_code == 409
    response = admin_client.get(f"/api/v1/documents/{identity}/source", headers={"Authorization": ""})
    assert response.status_code == 401
    admin_client.headers.pop("Authorization")
    response = admin_client.get(f"/api/v1/documents/{identity}/source")
    assert response.status_code == 410
    assert "Synthetic private note" not in response.text and "content_text" not in response.text
    assert admin_client.get(f"/api/v1/documents/{uuid4()}/source").status_code == 404


def test_busy_upload_contract(admin_client):
    source = create_source(admin_client)
    coordinator = admin_client.app.state.coordinator
    active = coordinator.claim("manual")
    try:
        response = upload(admin_client, source["id"])
        assert response.status_code == 409 and response.json()["error"]["code"] == "RUN_IN_PROGRESS"
        with admin_client.app.state.database.session() as db:
            assert db.scalar(select(func.count()).select_from(CrawlRun)) == 1
            assert db.scalar(select(func.count()).select_from(DocumentOrigin)) == 0
    finally: coordinator.finish(active.id)


@pytest.mark.parametrize("role,expected", [(None, 401), ("USER", 403)])
def test_admin_rbac_every_document_and_source_route(admin_client, role, expected):
    source = create_source(admin_client)
    receipt = upload(admin_client, source["id"])
    doc_id = resolve_document(admin_client, receipt)
    admin_client.headers.pop("Authorization")
    if role:
        credentials = {"email": "user@example.test", "password": "synthetic-password"}
        admin_client.post("/api/v1/auth/register", json=credentials)
        token = admin_client.post("/api/v1/auth/login", json=credentials).json()["access_token"]
        admin_client.headers["Authorization"] = f"Bearer {token}"
    for method, path, kwargs in [
        ("get", "/admin/documents", {}), ("get", f"/admin/documents/{doc_id}", {}),
        ("get", f"/admin/documents/{doc_id}/original", {}), ("delete", f"/admin/documents/{doc_id}", {}),
        ("post", f"/admin/documents/{doc_id}/disable", {"json": {"reason": "test"}}),
        ("post", f"/admin/documents/{doc_id}/enable", {"json": {"reason": "test"}}),
        ("post", "/admin/documents/upload", {}), ("get", "/admin/sources", {}),
        ("post", "/admin/sources", {"json": {}}), ("patch", f"/admin/sources/{source['id']}", {"json": {}}),
    ]:
        response = getattr(admin_client, method)("/api/v1" + path, **kwargs)
        assert response.status_code == expected, (path, response.text)
        if expected == 401: assert response.headers["www-authenticate"] == "Bearer"


def test_reason_validation_pagination_and_source_revocation(admin_client):
    source = create_source(admin_client)
    receipt = upload(admin_client, source["id"])
    doc_id = resolve_document(admin_client, receipt)
    path = f"/api/v1/admin/documents/{doc_id}"
    for body in [{"reason": " "}, {"reason": "x" * 501}, {"reason": "ok", "enabled": True}, {}]:
        assert admin_client.post(path + "/disable", json=body).status_code == 422
    for query in ["page=0", "page_size=101", "state=disabled"]:
        assert admin_client.get("/api/v1/admin/documents?" + query).status_code == 422
    assert admin_client.post(path + "/disable", json={"reason": "x" * 500}).status_code == 200
    assert admin_client.patch(f"/api/v1/admin/sources/{source['id']}",
                              json={"enabled": False, "permission_status": "denied"}).status_code == 200
    assert admin_client.post(path + "/enable", json={"reason": "test"}).status_code == 409
    assert upload(admin_client, source["id"]).status_code == 422


def test_duplicate_form_fields_rejected(admin_client):
    source = create_source(admin_client)
    # httpx multipart accepts repeated textual parts using file tuples.
    response = admin_client.post("/api/v1/admin/documents/upload", files=[
        ("file", ("test.txt", b"SYNTHETIC", "text/plain")), ("title", (None, "first")),
        ("title", (None, "second")), ("source_id", (None, source["id"])),
        ("provenance_note", (None, "SYNTHETIC"))])
    assert response.status_code == 422


def reprocess(client, receipt, content):
    """Exercise the same T017 service boundary as a future origin update, not a crawler."""
    from app.services.documents import file_path
    service = client.app.state.documents
    origin_id = receipt.json()["origin_id"]
    document_id = resolve_document(client, receipt)
    file_path(service.upload_dir, origin_id, "text/plain").write_bytes(content)
    coordinator = client.app.state.coordinator
    run = coordinator.claim("manual")
    coordinator.execute(run.id, lambda run_id: service.process_upload(run_id, origin_id, document_id, "text/plain"))
    with client.app.state.database.session() as db:
        item = db.scalar(select(CrawlRunItem).where(CrawlRunItem.run_id == run.id))
        return item


def test_disabled_changes_and_disabled_duplicate(admin_client):
    source = create_source(admin_client)
    receipt = upload(admin_client, source["id"])
    doc_id = resolve_document(admin_client, receipt)
    path = f"/api/v1/admin/documents/{doc_id}"
    admin_client.post(path + "/disable", json={"reason": "SYNTHETIC"})
    assert reprocess(admin_client, receipt, b"SYNTHETIC changed content").outcome == "updated"
    changed = admin_client.get(path).json()
    assert changed["enabled"] is False and changed["content_text"] == "SYNTHETIC changed content"
    other = upload(admin_client, source["id"], content=b"SYNTHETIC enabled content")
    other_id = resolve_document(admin_client, other)
    assert other_id != doc_id
    conflict = reprocess(admin_client, receipt, b"SYNTHETIC enabled content")
    assert conflict.outcome == "skipped" and conflict.reason == "DISABLED_DUPLICATE"
    assert resolve_document(admin_client, receipt) == doc_id
    after = admin_client.get(path).json()
    assert after["content_hash"] == changed["content_hash"] and after["enabled"] is False


def test_multiple_origins_split_and_failed_update_keeps_old(admin_client):
    source = create_source(admin_client)
    first = upload(admin_client, source["id"])
    second = upload(admin_client, source["id"], provenance_note="Another supplier")
    old_id = resolve_document(admin_client, first)
    assert resolve_document(admin_client, second) == old_id
    assert reprocess(admin_client, first, b"SYNTHETIC new content").outcome == "updated"
    new_id = resolve_document(admin_client, first)
    assert new_id != old_id and resolve_document(admin_client, second) == old_id
    old_text = admin_client.get(f"/api/v1/admin/documents/{old_id}").json()["content_text"]
    assert "new content" not in old_text
    service = admin_client.app.state.documents
    def fail(*args): raise RuntimeError("private upstream error or path")
    service.indexer.index = fail
    assert reprocess(admin_client, first, b"SYNTHETIC failing update").outcome == "error"
    after = admin_client.get(f"/api/v1/admin/documents/{new_id}").json()
    assert after["state"] == "ready" and after["content_text"] == "SYNTHETIC new content"
    assert after["last_update_error"] == "PROCESSING_FAILED"
    assert "private upstream" not in str(after)


def test_removal_while_staging_does_not_resurrect(admin_client):
    source = create_source(admin_client)
    receipt = upload(admin_client, source["id"])
    doc_id = resolve_document(admin_client, receipt)
    service = admin_client.app.state.documents
    service.indexer.index = lambda *_: service.delete(doc_id)
    item = reprocess(admin_client, receipt, b"SYNTHETIC staged update")
    assert item.outcome == "error" and item.reason == "DOCUMENT_REMOVED" and item.document_id is None
    assert admin_client.get(f"/api/v1/admin/documents/{doc_id}").status_code == 404


def test_permission_rechecked_after_staging(admin_client):
    from app.models.knowledge import DataSource
    source = create_source(admin_client)
    service = admin_client.app.state.documents
    def revoke(*_):
        with admin_client.app.state.knowledge_lock, admin_client.app.state.database.session() as db:
            model = db.get(DataSource, source["id"])
            model.enabled = False; model.permission_status = "denied"; db.commit()
    service.indexer.index = revoke
    receipt = upload(admin_client, source["id"])
    assert receipt.status_code == 202
    doc_id = resolve_document(admin_client, receipt)
    after = admin_client.get(f"/api/v1/admin/documents/{doc_id}").json()
    assert after["state"] == "error" and after["content_hash"] is None
    with admin_client.app.state.database.session() as db:
        run = db.get(CrawlRun, receipt.json()["run_id"])
        assert run.state == "failed" and run.error_count == 1
