"""Deterministic cosine ranking; synthetic vectors with known order."""
import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.knowledge import Document, DocumentChunk, DocumentOrigin, DataSource
from app.services.embedding import vector_blob
from app.services.retrieval import RetrievalService
from tests.knowledge_support import real_indexer, ingestion, ingest


def test_top_five_threshold_and_filters(ingestion, settings):
    knowledge = real_indexer(ingestion, settings)
    source, service, _ = knowledge
    ids = []
    for i in range(8):
        result = ingest(knowledge, f'SYNTHETIC engineering {i}'.encode(),
                        url=f'https://tuyensinh.utc.edu.vn/{i}', year=2026, campus='HN')
        ids.append(result.document_id)
    query = service.indexer.encoder.query('engineering')
    orthogonal = np.zeros(384, dtype=np.float32); orthogonal[10] = 1
    with service.database.session() as db:
        for i, identity in enumerate(ids):
            score = .99 - i * .02
            vector = score * query + np.sqrt(1 - score * score) * orthogonal
            db.scalar(select(DocumentChunk).where(DocumentChunk.document_id == identity)).embedding = vector_blob(vector)
        db.commit()
    r = RetrievalService(service.database, service.indexer.encoder, service._profile(), service.publish_lock, .75)
    assert [h['document_id'] for h in r.search('engineering', {'year': 2026})] == ids[:5]
    r.min_similarity = .96
    assert [h['document_id'] for h in r.search('engineering')] == ids[:2]
    r.min_similarity = .75
    assert not r.search('engineering', {'campus': 'HCM'})
    with pytest.raises(ValueError): r.search('engineering', {'not_context': 1})
    with service.database.session() as db:
        db.get(Document, ids[0]).enabled = False
        doc = db.get(Document, ids[1]); doc.state = 'quarantined'; doc.quality_reason = 'SYNTHETIC'
        db.get(Document, ids[2]).index_profile = {'other': True}
        db.scalar(select(DocumentOrigin).where(DocumentOrigin.document_id == ids[3])).active = False
        db.commit()
    assert [h['document_id'] for h in r.search('engineering')] == ids[4:]
    with service.database.session() as db:
        db.get(DataSource, source.id).enabled = False; db.commit()
    assert not r.search('engineering')


def test_blob_constraints_and_bad_norm_rejected(ingestion, settings):
    knowledge = real_indexer(ingestion, settings)
    _, service, _ = knowledge
    first = ingest(knowledge, b'SYNTHETIC engineering')
    for updates in [dict(embedding=b'bad'), dict(embedding_dim=383),
                    dict(extraction_kind='ocr', numeric_eligible=True), dict(page=0)]:
        with pytest.raises(IntegrityError), service.database.session() as db:
            chunk = db.scalar(select(DocumentChunk))
            for key, value in updates.items(): setattr(chunk, key, value)
            db.commit()
    with service.database.session() as db:
        db.scalar(select(DocumentChunk)).embedding = np.zeros(384, dtype='<f4').tobytes(); db.commit()
    r = RetrievalService(service.database, service.indexer.encoder, service._profile(), service.publish_lock, .75)
    assert not r.search('engineering')
    assert not service.indexer.usable(type('Doc', (), dict(id=first.document_id, index_profile=service._profile()))())


def test_current_state_checked_after_query_encode(ingestion, settings):
    knowledge = real_indexer(ingestion, settings)
    _, service, _ = knowledge
    result = ingest(knowledge, b'SYNTHETIC engineering')
    r = RetrievalService(service.database, service.indexer.encoder, service._profile(), service.publish_lock, .75)
    hit = r.search('engineering')[0]
    model = service.indexer.encoder.model
    def disable_before_result(texts, **kwargs):
        assert not service.publish_lock.locked()
        service.set_enabled(result.document_id, False)
        return model._encode(texts, **kwargs)
    model.encode.side_effect = disable_before_result
    assert not r.search('engineering') and not r.available(hit)


def test_citation_source_revoked_while_other_origin_remains_usable(ingestion, settings):
    from app.db.base import utc_now
    knowledge = real_indexer(ingestion, settings)
    source, service, _ = knowledge
    result = ingest(knowledge, b'SYNTHETIC engineering')
    r = RetrievalService(service.database, service.indexer.encoder, service._profile(), service.publish_lock, .75)
    original_hit = r.search('engineering')[0]
    with service.database.session() as db:
        other = DataSource(name='SYNTHETIC other allowed source', kind='upload', enabled=True,
                           permission_status='allowed', reuse_basis='TEST ONLY', checked_at=utc_now())
        db.add(other); db.flush()
        db.add(DocumentOrigin(document_id=result.document_id, source_id=other.id, origin_kind='web',
                             canonical_url=original_hit['url'], original_url=original_hit['url']))
        db.get(DataSource, source.id).enabled = False; db.commit()
    assert not r.available(original_hit)
    current = r.search('engineering')[0]
    assert current['source_name'] == other.name and r.available(current)
