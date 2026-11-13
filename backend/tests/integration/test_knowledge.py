"""Checkpoint C: SYNTHETIC text and encoder; actual SQLite + ingestion/retrieval/API."""
from threading import Lock
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from app.db.session import Database
from app.models.knowledge import DataSource, Document, DocumentOrigin, DocumentChunk
from app.services.documents import DocumentService
from app.services.embedding import Indexer, EmbeddingService
from app.services.extraction import Extractor
from app.services.retrieval import RetrievalService
from tests.knowledge_support import Model, real_indexer, ingestion, ingest
from tests.contract.knowledge_support import admin_client, create_source, upload, resolve_document


@pytest.fixture
def knowledge(ingestion, settings):
    return real_indexer(ingestion, settings)


def retrieval(knowledge, settings):
    _, service, _ = knowledge
    return RetrievalService(service.database, service.indexer.encoder, service._profile(),
                            service.publish_lock, settings.retrieval_min_similarity)


def test_ingest_reindex_restart_disable_enable_delete_dedup(knowledge, settings):
    _, service, _ = knowledge
    first = ingest(knowledge, b'SYNTHETIC engineering', year=2026, campus='HN')
    assert first.outcome == 'new'
    retriever = retrieval(knowledge, settings)
    hit = retriever.search('engineering', {'year': 2026, 'campus': 'HN'})[0]
    old_chunk = hit['chunk_id']
    assert hit['document_id'] == first.document_id and hit['available']
    assert not retriever.search('engineering', {'year': 2027})
    count = service.indexer.encoder.model.encode.call_count
    same = ingest(knowledge, b'SYNTHETIC engineering', year=2026, campus='HN')
    assert same.outcome == 'skipped'
    assert service.indexer.encoder.model.encode.call_count == count
    # Update failure preserves exact old vector/text/hash and usable index.
    with service.database.session() as db:
        old = db.get(DocumentChunk, old_chunk)
        old_blob = old.embedding
    service.indexer.encoder.model.encode.side_effect = RuntimeError('synthetic failure')
    assert ingest(knowledge, b'SYNTHETIC medicine', year=2026, campus='HN').outcome == 'error'
    with service.database.session() as db:
        assert db.get(DocumentChunk, old_chunk).embedding == old_blob
        assert db.get(Document, first.document_id).state == 'ready'
    service.indexer.encoder.model.encode.side_effect = service.indexer.encoder.model._encode
    updated = ingest(knowledge, b'SYNTHETIC engineering engineering', year=2026, campus='HN')
    assert updated.outcome == 'updated' and updated.document_id == first.document_id
    assert not retriever.available(hit)
    service.set_enabled(first.document_id, False)
    assert not retriever.search('engineering')
    assert ingest(knowledge, b'SYNTHETIC engineering updated', year=2026, campus='HN').outcome == 'updated'
    # Reopen a real file DB, not an in-memory replacement.
    service.database.dispose()
    reopened = Database(settings)
    reopened.initialize(); reopened.initialize()
    try:
        documents = DocumentService(reopened, settings.upload_dir, Lock(),
            Indexer(reopened, service.indexer.encoder), extractor=Extractor(settings))
        r = RetrievalService(reopened, service.indexer.encoder, documents._profile(), documents.publish_lock, .75)
        assert not r.search('engineering')
        documents.set_enabled(first.document_id, True)
        assert r.search('engineering')[0]['document_id'] == first.document_id
        documents.delete(first.document_id)
        assert not r.search('engineering') and not r.available(hit)
        with reopened.session() as db:
            assert not db.scalars(select(DocumentChunk)).all()
            assert not db.scalars(select(DocumentOrigin)).all()
    finally:
        reopened.dispose()
    again = ingest(knowledge, b'SYNTHETIC engineering', year=2026, campus='HN')
    assert again.outcome == 'new' and again.document_id != first.document_id


def test_publish_during_disable_delete_source_change_and_rollback(knowledge, settings, monkeypatch):
    source, service, _ = knowledge
    first = ingest(knowledge, b'SYNTHETIC engineering')
    index = service.indexer.index
    def disable_then_stage(text, meta):
        assert not service.publish_lock.locked()
        service.set_enabled(first.document_id, False)
        return index(text, meta)
    monkeypatch.setattr(service.indexer, 'index', disable_then_stage)
    assert ingest(knowledge, b'SYNTHETIC engineering updated').outcome == 'updated'
    assert not retrieval(knowledge, settings).search('engineering')
    monkeypatch.setattr(service.indexer, 'index', index)
    service.set_enabled(first.document_id, True)
    # A failure after replacing chunks in the transaction must roll everything back.
    from sqlalchemy import event
    def reject_insert(mapper, connection, target):
        raise RuntimeError('synthetic DB insert failure')
    event.listen(DocumentChunk, 'before_insert', reject_insert)
    try:
        assert ingest(knowledge, b'SYNTHETIC medicine').outcome == 'error'
    finally:
        event.remove(DocumentChunk, 'before_insert', reject_insert)
    assert retrieval(knowledge, settings).search('engineering')
    def revoke_then_stage(text, meta):
        with service.database.session() as db:
            db.get(DataSource, source.id).enabled = False; db.commit()
        return index(text, meta)
    monkeypatch.setattr(service.indexer, 'index', revoke_then_stage)
    assert ingest(knowledge, b'SYNTHETIC medicine').outcome == 'error'
    assert not retrieval(knowledge, settings).search('engineering')
    with service.database.session() as db:
        db.get(DataSource, source.id).enabled = True; db.commit()
    def delete_then_stage(text, meta):
        service.delete(first.document_id)
        return index(text, meta)
    monkeypatch.setattr(service.indexer, 'index', delete_then_stage)
    assert ingest(knowledge, b'SYNTHETIC removed').reason == 'DOCUMENT_REMOVED'
    assert not retrieval(knowledge, settings).search('engineering')


def test_multi_origin_split_profile_and_disabled_duplicate(knowledge, settings):
    _, service, _ = knowledge
    first = ingest(knowledge, b'SYNTHETIC engineering')
    same = ingest(knowledge, b'SYNTHETIC engineering', url='https://tuyensinh.utc.edu.vn/b')
    assert same.document_id == first.document_id
    service.set_enabled(first.document_id, False)
    split = ingest(knowledge, b'SYNTHETIC engineering split')
    with service.database.session() as db:
        assert not db.get(Document, split.document_id).enabled
    enabled = ingest(knowledge, b'SYNTHETIC medicine', url='https://tuyensinh.utc.edu.vn/c')
    count = service.indexer.encoder.model.encode.call_count
    conflict = ingest(knowledge, b'SYNTHETIC medicine')
    assert conflict.reason == 'DISABLED_DUPLICATE' and conflict.document_id == split.document_id
    assert service.indexer.encoder.model.encode.call_count == count
    # A new active origin may dedup into disabled; it must remain disabled.
    assert ingest(knowledge, b'SYNTHETIC engineering split', url='https://tuyensinh.utc.edu.vn/d').document_id == split.document_id
    with service.database.session() as db:
        assert not db.get(Document, split.document_id).enabled
        doc = db.get(Document, enabled.document_id)
        doc.index_profile = doc.index_profile | {'chunking_version': 'old'}; db.commit()
    r = retrieval(knowledge, settings)
    assert not r.search('medicine')
    count = service.indexer.encoder.model.encode.call_count
    assert ingest(knowledge, b'SYNTHETIC medicine', url='https://tuyensinh.utc.edu.vn/c').outcome == 'updated'
    assert service.indexer.encoder.model.encode.call_count == count + 1
    assert r.search('medicine')


def test_source_api_real_chunks_notes_pages_and_current_permissions(application, settings):
    # Use RBAC setup only; replace its explicit stub with real indexing before upload.
    with TestClient(application) as client:
        from app.db.base import utc_now
        service = application.state.documents
        service.indexer = Indexer(service.database, EmbeddingService(settings, model=Model()))
        with service.database.session() as db:
            source = DataSource(name='SYNTHETIC upload', kind='upload', enabled=True,
                permission_status='allowed', reuse_basis='TEST ONLY', checked_at=utc_now())
            db.add(source); db.commit()
        payload = SimpleNamespace(title='SYNTHETIC', source_id=source.id, source_url=None,
            provenance_note='PRIVATE NOTE MUST STAY PRIVATE', publisher=None, published_at=None,
            year=2026, campus='HN', major_code='test', method='demo')
        origin, pending = service.accept_upload(payload, b'SYNTHETIC engineering', 'text/plain')
        result = service._process_origin(origin, pending, b'SYNTHETIC engineering', 'text/plain')
        assert result.outcome == 'new'
        path = f'/api/v1/documents/{result.document_id}/source'
        response = client.get(path)
        assert response.status_code == 200, response.text
        value = response.json()
        assert set(value) == {'id', 'title', 'origins', 'excerpts', 'available'}
        assert value['origins'] == [{'url': f'urn:upload:{origin}', 'source_name': source.name}]
        assert value['excerpts'][0]['page'] == 1 and 'PRIVATE' not in response.text
        assert client.get(path + '?page=2').json()['excerpts'] == []
        assert client.get(path + '?page=0').status_code == 422
        # Upload a second note; content/context dedup uses zero encodes.
        count = service.indexer.encoder.model.encode.call_count
        payload.provenance_note = 'ANOTHER PRIVATE NOTE'
        origin2, pending2 = service.accept_upload(payload, b'SYNTHETIC engineering', 'text/plain')
        duplicate = service._process_origin(origin2, pending2, b'SYNTHETIC engineering', 'text/plain')
        assert duplicate.document_id == result.document_id and duplicate.outcome == 'skipped'
        assert service.indexer.encoder.model.encode.call_count == count
        with service.database.session() as db:
            chunk = db.scalar(select(DocumentChunk))
            assert chunk.year == 2026 and chunk.campus == 'HN'
            assert chunk.source_snapshot_json['origin_id'] == origin
            assert 'provenance_note' not in chunk.source_snapshot_json
        service.set_enabled(result.document_id, False)
        assert client.get(path).status_code == 410
        service.set_enabled(result.document_id, True)
        assert client.get(path).status_code == 200
        with service.database.session() as db:
            db.get(DataSource, source.id).enabled = False; db.commit()
        assert client.get(path).status_code == 410
        service.delete(result.document_id)
        assert client.get(path).status_code == 404


def test_crawl_counts_with_real_indexer(knowledge, monkeypatch):
    from tests.integration.test_utc_ingestion import test_counts_new_updated_skipped_error
    test_counts_new_updated_skipped_error(knowledge, monkeypatch)
    _, service, _ = knowledge
    with service.database.session() as db:
        assert db.scalars(select(DocumentChunk)).all()


def test_native_ocr_pages_headers_and_context(knowledge, settings):
    from pathlib import Path
    from unittest.mock import Mock
    from tests.unit.test_extraction import tsv
    source, service, _ = knowledge
    fixtures = Path(__file__).parents[1] / 'fixtures/utc'
    service.extractor.runner = Mock(return_value=SimpleNamespace(returncode=0, stdout=tsv(), stderr=''))
    payload = SimpleNamespace(title='SYNTHETIC', year=2026, campus='HN', major_code='demo', method='test')
    native = service.process_web(source.id, 'https://tuyensinh.utc.edu.vn/native',
        (fixtures / 'native.pdf').read_bytes(), 'application/pdf', payload)
    ocr = service.process_web(source.id, 'https://tuyensinh.utc.edu.vn/scan',
        (fixtures / 'scan.pdf').read_bytes(), 'application/pdf', payload)
    assert native.outcome == ocr.outcome == 'new'
    with service.database.session() as db:
        native_chunks = db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == native.document_id)).all()
        assert {c.page for c in native_chunks} == {1, 2}
        ocr_chunks = db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == ocr.document_id)).all()
        assert all(c.extraction_kind == 'ocr' and not c.numeric_eligible for c in ocr_chunks)
    text = ('<main><h1>SYNTHETIC 2026</h1><h2>HN</h2><p>' + 'engineering ' * 700
            + '</p><h2>HCM</h2><p>medicine</p></main>')
    html = service.process_web(source.id, 'https://tuyensinh.utc.edu.vn/html', text.encode(), 'text/html', payload)
    assert html.outcome == 'new'
    with service.database.session() as db:
        chunks = db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == html.document_id)
                            .order_by(DocumentChunk.ordinal)).all()
        assert all(c.section == 'SYNTHETIC 2026 / HN' and c.text.startswith(c.section) for c in chunks[:-1])
        assert chunks[-1].section == 'SYNTHETIC 2026 / HCM'
        assert 'medicine' not in '\n'.join(c.text for c in chunks[:-1])


def test_api_upload_to_retrieval_and_notes_after_reopen(admin_client, settings):
    service = admin_client.app.state.documents
    encoder = EmbeddingService(settings, model=Model())
    service.indexer = Indexer(service.database, encoder)
    service.extractor = Extractor(settings)
    admin_client.app.state.retrieval = RetrievalService(service.database, encoder, service._profile(),
                                                       service.publish_lock, .75)
    source = create_source(admin_client)
    identities, origins = [], []
    for note, year in [('PRIVATE FIRST', 2026), ('PRIVATE SECOND', 2026), ('PRIVATE THIRD', 2027)]:
        receipt = upload(admin_client, source['id'], b'SYNTHETIC engineering', provenance_note=note, year=str(year))
        assert receipt.status_code == 202
        identities.append(resolve_document(admin_client, receipt))
        origins.append(receipt.json()['origin_id'])
    assert identities[0] == identities[1] != identities[2]
    # Two contexts need two encode calls; duplicate upload adds provenance only.
    assert encoder.model.encode.call_count == 2
    r = admin_client.app.state.retrieval
    assert r.search('engineering', {'year': 2026})[0]['document_id'] == identities[0]
    assert r.search('engineering', {'year': 2027})[0]['document_id'] == identities[2]
    path = f'/api/v1/documents/{identities[0]}/source'
    response = admin_client.get(path)
    assert response.status_code == 200 and 'PRIVATE' not in response.text
    # Observe persisted notes in a second engine, not cached ORM objects.
    reopened = Database(settings)
    try:
        reopened.initialize()
        with reopened.session() as db:
            assert [db.get(DocumentOrigin, oid).provenance_note for oid in origins] == [
                'PRIVATE FIRST', 'PRIVATE SECOND', 'PRIVATE THIRD']
    finally:
        reopened.dispose()
    count = encoder.model.encode.call_count
    same = upload(admin_client, source['id'], b' SYNTHETIC  engineering\n', provenance_note='PRIVATE FOURTH', year='2026')
    assert same.status_code == 202 and resolve_document(admin_client, same) == identities[0]
    assert encoder.model.encode.call_count == count
