"""Real E5 CPU + SQLite ingestion/retrieval smoke, synthetic Vietnamese only.

Cache-only, no HTTP/Gemini, no writes to the application database. Run from backend:
uv run --locked --offline python tests/smoke/check_knowledge_e5.py --output tests/smoke/knowledge-e5-local.json
"""
import argparse
import json
import os
from pathlib import Path
import platform
import secrets
import sys
from tempfile import TemporaryDirectory
from threading import Lock
import time
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
from sqlalchemy import select
import torch

from app.core.config import BACKEND_DIR, E5_REVISION, Settings
from app.db.base import utc_now
from app.db.session import Database
from app.models.knowledge import DataSource, Document, DocumentChunk
from app.services.chunking import chunk_pages, token_count
from app.services.documents import DocumentService
from app.services.embedding import EmbeddingService, Indexer, QueryTooLong, read_vector
from app.services.extraction import Extractor
from app.services.retrieval import RetrievalService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = dict(fixture='GIẢ LẬP — KHÔNG PHẢI THÔNG TIN UTC', model='intfloat/multilingual-e5-small',
                  revision=E5_REVISION, device='cpu', python=platform.python_version(),
                  torch=torch.__version__, processor=platform.processor(), logical_cpus=os.cpu_count(),
                  torch_threads=torch.get_num_threads(), network=False, threshold=.75)
    # tempfile isolates DB/uploads. Only the existing model cache is read.
    with TemporaryDirectory(prefix='utc-e5-smoke-') as temporary:
        folder = Path(temporary)
        settings = Settings(_env_file=None, jwt_secret=secrets.token_hex(32),
            database_url=f'sqlite:///{(folder / "smoke.db").as_posix()}', upload_dir=folder / 'uploads',
            model_cache_dir=BACKEND_DIR / 'data/models', embedding_revision=E5_REVISION,
            embedding_device='cpu', gemini_api_key=None)
        database = Database(settings)
        database.initialize()
        encoder = EmbeddingService.local(settings)
        start = time.perf_counter()
        model = encoder.model
        report['model_load_seconds'] = round(time.perf_counter() - start, 4)
        assert model.device.type == next(model.parameters()).device.type == 'cpu'
        assert model.get_embedding_dimension() == 384 and torch.version.cuda is None
        model.encode = Mock(wraps=model.encode)
        documents = DocumentService(database, settings.upload_dir, Lock(), Indexer(database, encoder),
                                    extractor=Extractor(settings))
        r = RetrievalService(database, encoder, documents._profile(), documents.publish_lock, .75)
        with database.session() as db:
            source = DataSource(name='GIẢ LẬP local E5 smoke', kind='utc',
                base_url='https://tuyensinh.utc.edu.vn/', allowed_paths_json=['/'], enabled=True,
                permission_status='allowed', reuse_basis='SYNTHETIC TEST ONLY', checked_at=utc_now(),
                robots_url='https://tuyensinh.utc.edu.vn/robots.txt', terms_url='https://tuyensinh.utc.edu.vn/terms')
            db.add(source); db.commit()
        payload = SimpleNamespace(title='GIẢ LẬP local smoke', year=2026, campus='HN', major_code=None, method=None)
        def ingest(text, path='/engineering', metadata=payload):
            return documents.process_web(source.id, 'https://tuyensinh.utc.edu.vn' + path,
                text.encode('utf-8'), 'text/plain', metadata)
        engineering = ('GIẢ LẬP — KHÔNG PHẢI THÔNG TIN UTC. Chương trình kỹ thuật phần mềm '
                       'học lập trình, cấu trúc dữ liệu, phát triển ứng dụng và kiểm thử phần mềm.')
        start = time.perf_counter()
        first = ingest(engineering)
        assert first.outcome == 'new', first
        assert model.encode.call_args.args[0][0].startswith('passage: ')
        report['first_ingestion_seconds'] = round(time.perf_counter() - start, 4)
        assert ingest('GIẢ LẬP: Chương trình nấu ăn học chế biến thực phẩm và kỹ năng nhà bếp.', '/cooking').outcome == 'new'
        assert ingest('GIẢ LẬP: Chương trình kế toán học báo cáo tài chính và nghiệp vụ kế toán.', '/finance').outcome == 'new'
        question = 'Chương trình kỹ thuật phần mềm học lập trình và phát triển ứng dụng gì?'
        latencies, hits = [], []
        for _ in range(10):
            start = time.perf_counter()
            hits = r.search(question, {'year': 2026, 'campus': 'HN'})
            latencies.append((time.perf_counter() - start) * 1000)
            assert hits and hits[0]['document_id'] == first.document_id
        assert model.encode.call_args.args[0] == ['query: ' + question]
        assert model.encode.call_args.kwargs['device'] == 'cpu'
        report['warm_retrieval_ms'] = dict(n=10, p50=round(float(np.median(latencies)), 3),
            p95=round(float(np.percentile(latencies, 95)), 3), max=round(max(latencies), 3),
            samples=[round(value, 3) for value in latencies])
        report['synthetic_scores'] = [dict(url=h['url'], cosine=round(h['similarity'], 6)) for h in hits]
        old_hit = hits[0]
        # Boundary checks use the actual pinned tokenizer, not a word-count stand-in.
        pages = [dict(page=2, text=('Lập trình ứng dụng và kiểm thử phần mềm. ' * 180),
                      section='GIẢ LẬP — Điều kiện áp dụng', extraction_kind='native', numeric_eligible=True)]
        chunks = chunk_pages(pages, encoder.tokenizer)
        budgets = [token_count(encoder.tokenizer, 'passage: ' + c['text']) for c in chunks]
        assert len(chunks) > 1 and max(budgets) <= 512
        assert all(len(encoder.tokenizer(c['text'], add_special_tokens=False)['input_ids']) <= 320 for c in chunks)
        vectors = encoder.passages([c['text'] for c in chunks])
        assert vectors.shape == (len(chunks), 384) and vectors.dtype == np.dtype('<f4')
        assert np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-5)
        report['chunk_boundary'] = dict(chunks=len(chunks), max_tokens_including_prefix=max(budgets),
            max_content_tokens=max(len(encoder.tokenizer(c['text'], add_special_tokens=False)['input_ids']) for c in chunks),
            overlap=48, dimension=384, dtype=str(vectors.dtype), blob_bytes=1536)
        try:
            encoder.query('engineering ' * 600)
            raise AssertionError('Oversized query was truncated or accepted')
        except QueryTooLong:
            pass
        before = model.encode.call_count
        assert ingest(engineering).outcome == 'skipped'
        assert model.encode.call_count == before
        # Same content/context from another web origin dedups without encode.
        assert ingest(engineering, '/engineering-copy').document_id == first.document_id
        assert model.encode.call_count == before
        with database.session() as db:
            assert len(db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == first.document_id)).all()) == 1
            chunk = db.get(DocumentChunk, old_hit['chunk_id'])
            assert len(chunk.embedding) == 1536 and np.isfinite(read_vector(chunk.embedding)).all()
            doc = db.get(Document, first.document_id)
            doc.index_profile = doc.index_profile | {'chunking_version': 'synthetic-old'}; db.commit()
        before = model.encode.call_count
        assert ingest(engineering).outcome == 'updated'
        assert model.encode.call_count == before + 1 and not r.available(old_hit)
        current = r.search(question)[0]
        # Failed embedding update retains the current, usable vector/hash.
        wrapped = model.encode.side_effect
        model.encode.side_effect = RuntimeError('SYNTHETIC encoder failure')
        assert ingest(engineering + ' Bản sửa đổi.').outcome == 'error'
        model.encode.side_effect = wrapped
        assert r.available(current)
        documents.set_enabled(first.document_id, False)
        assert first.document_id not in [h['document_id'] for h in r.search(question)]
        # Update shared origin splits disabled document, preserving disabled flag.
        disabled_update = ingest(engineering + ' Kiểm thử dữ liệu bổ sung.')
        assert disabled_update.outcome == 'updated'
        with database.session() as db:
            assert not db.get(Document, disabled_update.document_id).enabled
        # Restart keeps file-backed vectors and disabled state without model reload.
        database.dispose()
        database = Database(settings); database.initialize()
        documents = DocumentService(database, settings.upload_dir, Lock(), Indexer(database, encoder), extractor=Extractor(settings))
        r = RetrievalService(database, encoder, documents._profile(), documents.publish_lock, .75)
        assert disabled_update.document_id not in [h['document_id'] for h in r.search(question)]
        documents.set_enabled(disabled_update.document_id, True)
        assert disabled_update.document_id in [h['document_id'] for h in r.search(question)]
        assert r.source(disabled_update.document_id)['available']
        documents.delete(disabled_update.document_id)
        assert disabled_update.document_id not in [h['document_id'] for h in r.search(question)]
        # The old shared document remains disabled. A distinct new payload at the
        # deleted URL is a new document on a later item, with no tombstone.
        recrawled = ingest(engineering + ' Nội dung mới sau khi xóa.')
        assert recrawled.outcome == 'new' and recrawled.document_id != disabled_update.document_id
        assert not r.search(question, {'year': 2027})
        with database.session() as db:
            db.get(DataSource, source.id).enabled = False; db.commit()
        assert not r.search(question)
        report['checks'] = dict(cpu=True, real_tokenizer_budget=True, prefixes=True, l2_float32_blob=True,
            cosine_top_result=True, unchanged_encode_zero=True, dedup_encode_zero=True, profile_reindex=True,
            failed_update_keeps_index=True, disable_update_restart=True, enable=True, delete=True,
            recrawl=True, context_filter=True, source_filter=True, query_oversize_422=True)
        report['profile'] = documents._profile()
        database.dispose()
    report['status'] = 'PASS'
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(output + '\n', encoding='utf-8')
    # Windows redirected stdout may use cp1252; artifact above remains UTF-8.
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
