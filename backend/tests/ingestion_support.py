"""B2 offline ingestion; fake indexer, never E5 or a live website."""
from threading import Lock
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import select

from app.db.base import utc_now
from app.models.knowledge import DataSource, Document, DocumentOrigin
from app.services.documents import DocumentService
from app.services.extraction import Extractor
from app.services.coordinator import Coordinator


@pytest.fixture
def ingestion(database, settings):
    database.initialize()
    with database.session() as db:
        source = DataSource(name="SYNTHETIC", kind="utc", base_url="https://tuyensinh.utc.edu.vn/",
            allowed_paths_json=["/"], enabled=True, permission_status="allowed", reuse_basis="TEST ONLY",
            checked_at=utc_now(), robots_url="https://tuyensinh.utc.edu.vn/robots.txt",
            terms_url="https://tuyensinh.utc.edu.vn/terms", min_interval_seconds=2)
        db.add(source); db.commit()
    indexer = SimpleNamespace(profile={"fake": "b2"}, index=Mock(), usable=lambda d: bool(d.content_text))
    extractor = Extractor(settings)
    extractor.extract = Mock(wraps=extractor.extract)
    service = DocumentService(database, settings.upload_dir, Lock(), indexer, extractor=extractor)
    return source, service, Coordinator(database)


def ingest(ingestion, data=b"SYNTHETIC content for offline ingestion tests", url="https://tuyensinh.utc.edu.vn/a", **metadata):
    source, service, coordinator = ingestion
    run = coordinator.claim("manual")
    results = []
    coordinator.execute(run.id, lambda _: results.append(service.process_web(source.id, url, data, "text/plain",
        SimpleNamespace(**(dict(title="SYNTHETIC", year=None, campus=None, major_code=None, method=None) | metadata)))))
    assert results, "pipeline raised unexpectedly"
    return results[0]


