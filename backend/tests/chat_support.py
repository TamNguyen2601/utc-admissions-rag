"""GIẢ LẬP — KHÔNG PHẢI THÔNG TIN UTC. Temporary SQLite; no demo data/key."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
import pytest

from app.db.base import utc_now
from app.models.knowledge import DataSource
from app.services.embedding import EmbeddingService
from tests.knowledge_support import Model


CONTEXT = dict(year=2026, campus='HN', major_code='7480201', method='THPT')
QUESTION = 'UTC đào tạo công nghệ thông tin thế nào?'
TEXT = ('GIẢ LẬP — KHÔNG PHẢI THÔNG TIN UTC.\nChương trình DEMO2+2\n'
        'Mã ngành: 7480201\nCông nghệ thông tin tập trung phần mềm, thực hành và tư duy hệ thống.')
ANSWER = 'Theo tài liệu tuyển sinh năm 2026, mã ngành 7480201 có mô tả công nghệ thông tin.'


@pytest.fixture
def chat_client(application, monkeypatch):
    from app import main
    monkeypatch.setattr(main.EmbeddingService, 'local',
                        lambda settings: EmbeddingService(settings, model=Model()))
    with TestClient(application, raise_server_exceptions=False) as client:
        with application.state.database.session() as db:
            source = DataSource(name='GIẢ LẬP', kind='utc', base_url='https://tuyensinh.utc.edu.vn/',
                allowed_paths_json=['/'], enabled=True, permission_status='allowed',
                reuse_basis='FIXTURE ONLY', checked_at=utc_now(),
                robots_url='https://tuyensinh.utc.edu.vn/robots.txt',
                terms_url='https://tuyensinh.utc.edu.vn/terms', min_interval_seconds=2)
            db.add(source)
            db.commit()
        application.state.test_source_id = source.id
        application.state.chat.gemini = SimpleNamespace(generate=AsyncMock(return_value=json.dumps(
            dict(answer=ANSWER, evidence_ids=['E1']))))
        yield client


def add_document(client, text=TEXT, *, context=None, url=None, title='GIẢ LẬP Chương trình DEMO2+2'):
    state = client.app.state
    metadata = SimpleNamespace(title=title, **(CONTEXT | (context or {})))
    result = state.documents.process_web(state.test_source_id,
        url or 'https://tuyensinh.utc.edu.vn/synthetic', text.encode('utf-8'), 'text/plain', metadata)
    assert result.outcome in {'new', 'updated', 'skipped'}, result
    return result.document_id


def ask(client, **changes):
    return client.post('/api/v1/chat/guest', json={'message': QUESTION, 'context': CONTEXT} | changes)
