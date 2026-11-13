"""T013/T014 checkpoint only: synthetic local database, no future tables."""
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.db.base import utc_now
from app.db.session import Database
from app.models.knowledge import DataSource, Document, DocumentOrigin
from app.models.crawl import CrawlRun, CrawlRunItem


@pytest.fixture
def knowledge_db(settings):
    db = Database(settings)
    db.initialize()
    yield db
    db.dispose()


def test_document_identity_origins_and_cascade(knowledge_db):
    with knowledge_db.session() as db:
        source = DataSource(name="SYNTHETIC", kind="upload")
        document = Document(title="SYNTHETIC", content_hash="a" * 64, context_key="context")
        db.add_all([source, document]); db.flush()
        ids = [str(uuid4()) for _ in range(3)]
        for index, identity in enumerate(ids):
            db.add(DocumentOrigin(id=identity, source_id=source.id, document_id=document.id,
                origin_kind="web" if index == 0 else "upload", canonical_url="https://example.org/a",
                original_url="https://example.org/a", provenance_note=f"SYNTHETIC {index}"))
        db.commit()
        assert len(db.scalars(select(DocumentOrigin)).all()) == 3
        for entity in [
            Document(title="duplicate", content_hash="a" * 64, context_key="context"),
            DocumentOrigin(source_id=source.id, document_id=document.id, origin_kind="web",
                           canonical_url="https://example.org/a", original_url="https://example.org/a"),
            DocumentOrigin(source_id=source.id, document_id=str(uuid4()), origin_kind="upload",
                           canonical_url="urn:test", original_url="urn:test"),
        ]:
            db.add(entity)
            with pytest.raises(IntegrityError): db.commit()
            db.rollback()
        db.add(Document(title="different context", content_hash="a" * 64, context_key="other"))
        db.commit()
        with pytest.raises(IntegrityError):
            db.execute(delete(DataSource).where(DataSource.id == source.id))
        db.rollback()
        db.delete(document); db.commit()
        assert not db.scalars(select(DocumentOrigin)).all()


def test_run_items_duplicate_urls_and_set_null(knowledge_db):
    with knowledge_db.session() as db:
        now = utc_now()
        run = CrawlRun(trigger="manual", started_at=now)
        doc = Document(title="SYNTHETIC", context_key="unknown")
        db.add_all([run, doc]); db.flush()
        for i in range(1, 4):
            db.add(CrawlRunItem(run_id=run.id, item_index=i, document_id=doc.id,
                canonical_url=None if i == 3 else "https://example.org/a",
                outcome="error", started_at=now, ended_at=now))
        db.commit()
        for index in [0, 1]:
            db.add(CrawlRunItem(run_id=run.id, item_index=index, outcome="error", started_at=now, ended_at=now))
            with pytest.raises(IntegrityError): db.commit()
            db.rollback()
        db.delete(doc); db.commit()
        assert all(item.document_id is None for item in db.scalars(select(CrawlRunItem)))
        db.delete(run); db.commit()
        assert not db.scalars(select(CrawlRunItem)).all()


def test_skipped_busy_constraints(knowledge_db):
    with knowledge_db.session() as db:
        now = utc_now()
        good = dict(trigger="scheduled", state="skipped_busy", created_at=now, ended_at=now)
        db.add(CrawlRun(**good)); db.commit()
        for change in [{"trigger": "manual"}, {"started_at": now}, {"new_count": 1},
                       {"ended_at": None}, {"source_outcomes_json": [{"invalid": True}]}]:
            db.add(CrawlRun(**(good | change)))
            with pytest.raises(IntegrityError): db.commit()
            db.rollback()
        skipped = db.scalar(select(CrawlRun))
        db.add(CrawlRunItem(run_id=skipped.id, item_index=1, outcome="skipped", started_at=now, ended_at=now))
        with pytest.raises(IntegrityError): db.commit()
        db.rollback()


def test_pending_nullable_hashes_and_origin_constraints(knowledge_db):
    with knowledge_db.session() as db:
        source = DataSource(name="SYNTHETIC", kind="upload")
        pending = [Document(title="SYNTHETIC", context_key="unknown") for _ in range(2)]
        db.add_all([source, *pending]); db.commit()
        assert pending[0].id != pending[1].id
        for changes in [{"origin_kind": "invalid"}, {"source_id": str(uuid4())},
                        {"provenance_note": " "}, {"provenance_note": "x" * 2001}, {"provenance_note": None}]:
            values = dict(source_id=source.id, document_id=pending[0].id, origin_kind="upload",
                          canonical_url="urn:upload:synthetic", original_url="urn:upload:synthetic", provenance_note="SYNTHETIC")
            db.add(DocumentOrigin(**(values | changes)))
            with pytest.raises(IntegrityError): db.commit()
            db.rollback()
        for source_values in [dict(enabled=True, permission_status="unknown"),
                              dict(permission_status="allowed", reuse_basis=None), dict(min_interval_seconds=1)]:
            db.add(DataSource(name="SYNTHETIC invalid", kind="upload", **source_values))
            with pytest.raises(IntegrityError): db.commit()
            db.rollback()
