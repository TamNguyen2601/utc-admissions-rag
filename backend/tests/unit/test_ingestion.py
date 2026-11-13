"""B2 offline ingestion; fake indexer, never E5 or a live website."""
from sqlalchemy import select
from app.models.knowledge import Document, DocumentOrigin
from tests.ingestion_support import ingestion, ingest


def test_raw_content_profile_context_and_failures(ingestion):
    source, service, _ = ingestion
    first = ingest(ingestion)
    assert first.outcome == "new"
    assert ingest(ingestion).outcome == "skipped"
    assert service.extractor.extract.call_count == 1 and service.indexer.index.call_count == 1
    assert ingest(ingestion, b" SYNTHETIC  content for offline ingestion tests\n").outcome == "skipped"
    assert service.indexer.index.call_count == 1
    service.indexer.profile = {"fake": "changed"}
    assert ingest(ingestion).outcome == "updated"
    assert service.indexer.index.call_count == 2
    service.indexer.index.side_effect = RuntimeError("private upstream/path")
    failed = ingest(ingestion, b"SYNTHETIC replacement")
    assert failed.outcome == "error"
    with service.database.session() as db:
        old = db.get(Document, first.document_id)
        assert old.state == "ready" and "replacement" not in old.content_text
        assert old.last_update_error == "PROCESSING_FAILED"
        assert db.scalar(select(DocumentOrigin)).document_id == old.id


def test_multi_origin_disabled_split_and_duplicate(ingestion):
    _, service, _ = ingestion
    first = ingest(ingestion)
    second = ingest(ingestion, url="https://tuyensinh.utc.edu.vn/b")
    assert second.document_id == first.document_id
    service.set_enabled(first.document_id, False)
    changed = ingest(ingestion, b"SYNTHETIC changed description")
    assert changed.outcome == "updated" and changed.document_id != first.document_id
    with service.database.session() as db:
        assert not db.get(Document, changed.document_id).enabled
        assert not db.get(Document, first.document_id).enabled
        assert len(db.scalars(select(Document)).all()) == 2
    enabled = ingest(ingestion, b"SYNTHETIC enabled different document", url="https://tuyensinh.utc.edu.vn/c")
    conflict = ingest(ingestion, b"SYNTHETIC enabled different document")
    assert conflict.reason == "DISABLED_DUPLICATE"
    assert conflict.document_id == changed.document_id != enabled.document_id


def test_changed_context_does_not_merge(ingestion):
    _, service, _ = ingestion
    first = ingest(ingestion, year=2026)
    second = ingest(ingestion, year=2027, url="https://tuyensinh.utc.edu.vn/b")
    assert first.document_id != second.document_id and service.indexer.index.call_count == 2
    moved = ingest(ingestion, year=2027)
    assert moved.document_id == second.document_id
    assert service.indexer.index.call_count == 2
