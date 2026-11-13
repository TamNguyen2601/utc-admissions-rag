"""GIẢ LẬP M1: not UTC data or a validated psychological instrument."""
from uuid import uuid4

import pytest
from app.models.knowledge import Document
from tests.jobs_support import job_client, admin_client, BASE  # noqa: F401
from tests.contract.knowledge_support import create_source, upload, resolve_document


def catalogue(document_id, content_hash, count=3):
    majors = [dict(id=str(uuid4()), code=chr(65 + i), name=f'SYNTHETIC ngành {chr(65 + i)}',
        campus='SYNTHETIC campus', description='SYNTHETIC mô tả ngành, không phải UTC.',
        source_document_id=document_id, source_content_hash=content_hash, source_page=None,
        career_groups=[dict(code=f'group-{i}', label=f'SYNTHETIC nghề {i}',
                            reason='SYNTHETIC mapping theo mô tả nguồn.')]) for i in range(count)]
    questions = []
    for position in range(1, 11):
        scoring = {}
        for i, major in enumerate(majors):
            direction = ('positive' if position == 1 else 'negative') if i == 0 else (
                ('negative' if position == 1 else 'positive') if i == 1 else 'positive')
            if i < 2 and position > 2:
                direction = 'none'
            scoring[major['id']] = dict(direction=direction, reason=f'SYNTHETIC {direction} đặc điểm ngành.')
        questions.append(dict(id=str(uuid4()), position=position,
            text=f'SYNTHETIC câu {position}: Tôi thích làm việc theo phong cách này.', scoring=scoring))
    return dict(majors=majors, questions=questions)


@pytest.fixture
def quiz_client(job_client):
    from app.services.recommendation import RecommendationService
    client = job_client
    source = create_source(client, name='SYNTHETIC catalogue permission', kind='catalog',
        base_url='https://tuyensinh.utc.edu.vn/', allowed_paths=['/'],
        robots_url='https://tuyensinh.utc.edu.vn/robots.txt', terms_url='https://tuyensinh.utc.edu.vn/terms')
    content = '\n'.join(f'SYNTHETIC ngành {chr(65+i)} mã {chr(65+i)}' for i in range(8))
    receipt = upload(client, source['id'], content=content.encode(),
        source_url='https://tuyensinh.utc.edu.vn/synthetic-test-only', publisher='SYNTHETIC test publisher')
    assert receipt.status_code == 202, receipt.text
    doc_id = resolve_document(client, receipt)
    with client.app.state.database.session() as db:
        doc = db.get(Document, doc_id)
        assert doc.state == 'ready'
        payload = catalogue(doc.id, doc.content_hash)
    service = client.app.state.recommendation
    assert isinstance(service, RecommendationService)
    service.import_catalog(payload)
    client.catalogue = payload
    client.catalogue_source = source['id']
    return client


def request_body(client, values=None):
    quiz = client.get(BASE + '/quiz').json()
    return dict(rubric_version=quiz['rubric_version'], answers=[
        dict(question_id=q['id'], value=(values or [3] * 10)[i]) for i, q in enumerate(quiz['questions'])])


CASES = [
    ('S1', [5, 1] + [3]*8, [100, 0, 50], 'insufficient_matches', []),
    ('S2', [1, 5] + [3]*8, [0, 100, 50], 'insufficient_matches', []),
    ('S3', [3]*10, [50, 50, 50], 'ready', ['A', 'B', 'C']),
    ('S4', [4, 2] + [3]*8, [75, 25, 50], 'ready', ['A', 'C', 'B']),
    ('S5', [4, 2, 5] + [3]*7, [75, 25, 55], 'ready', ['A', 'C', 'B']),
    ('S6', [5]*10, [50, 50, 100], 'ready', ['C', 'A', 'B']),
]
