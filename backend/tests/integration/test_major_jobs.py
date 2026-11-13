"""Quiz -> catalogue major -> real career-group filtering, without resolver stubs."""
from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models.knowledge import DataSource, Document, DocumentOrigin
from app.schemas.chat import GuestChatInput
from app.services.scope import classify
from tests.quiz_support import quiz_client, job_client, admin_client, request_body, BASE  # noqa: F401
from tests.jobs_support import row, import_rows, results


def test_quiz_to_major_to_jobs_uses_catalogue_groups_not_null_or_other(quiz_client):
    client = quiz_client
    rows = [row(client, source_url=f'https://publisher.example.test/jobs/{i}',
        career_group=group, classification_reason='SYNTHETIC file mapping' if group else None)
        for i, group in enumerate(['group-0', 'group-0', 'group-1', None])]
    results(client, import_rows(client, rows))
    recommendations = client.post(BASE + '/recommendations', json=request_body(client, [4, 2] + [3]*8)).json()
    major = recommendations['items'][0]['major']
    assert major['code'] == 'A'
    jobs = client.get(BASE + '/jobs', params={'major_id': major['id']}).json()
    assert jobs['status'] == 'ready' and jobs['total'] == jobs['observed_open_count'] == 2
    assert all(item['career_group'] == 'group-0' for item in jobs['items'])
    assert client.get(BASE + '/jobs', params={'career_group': 'group-1'}).json()['total'] == 1
    assert client.get(BASE + '/jobs', params={'major_id': major['id'], 'career_group': 'group-1'}).json()['total'] == 0
    assert client.get(BASE + '/jobs', params={'major_id': str(uuid4())}).status_code == 404
    assert client.get(BASE + '/jobs', params={'career_group': 'invented'}).status_code == 422


@pytest.mark.parametrize('change', ['hash', 'disabled_doc', 'disabled_source', 'inactive_origin', 'delete'])
def test_jobs_and_scope_never_use_stale_major_mapping(quiz_client, change):
    client = quiz_client
    data = client.catalogue
    major = data['majors'][0]
    results(client, import_rows(client, [row(client, career_group='group-0', classification_reason='SYNTHETIC mapping')]))
    assert client.get(BASE + '/jobs', params={'major_id': major['id']}).json()['total'] == 1
    with client.app.state.database.session() as db:
        doc = db.get(Document, major['source_document_id'])
        if change == 'hash': doc.content_hash = 'a'*64
        elif change == 'disabled_doc': doc.enabled = False
        elif change == 'disabled_source': db.get(DataSource, client.catalogue_source).enabled = False
        elif change == 'inactive_origin':
            db.scalar(select(DocumentOrigin).where(DocumentOrigin.document_id == doc.id)).active = False
        else: db.delete(doc)
        db.commit()
    result = client.get(BASE + '/jobs', params={'major_id': major['id']})
    if change == 'delete': assert result.status_code == 404
    else:
        assert result.json()['status'] == 'data_missing' and result.json()['observed_open_count'] is None
        assert result.json()['items'] == []
    assert not client.app.state.recommendation.resolves_scope('nghề SYNTHETIC nghề 0')
    assert client.get(BASE + '/jobs').json()['total'] == 1  # Independent job source remains usable.


def test_scope_catalogue_labels_and_ambiguous_other_school(quiz_client):
    service = quiz_client.app.state.chat
    resolver = service.catalogue_resolver
    assert resolver is not None
    for message, expected in [
        ('SYNTHETIC nghề 0 làm những gì?', 'retrieve'),
        ('ngành SYNTHETIC ngành A ra trường làm gì?', 'retrieve'),
        ('nghề này làm gì?', 'needs_clarification'),
        ('ngành SYNTHETIC ngành A của trường FPT làm gì?', 'out_of_scope'),
    ]:
        assert classify(GuestChatInput(message=message), resolver).status == expected


def test_changed_mapping_requires_reimport_then_jobs_follow_new_groups(quiz_client):
    client = quiz_client
    for i in [0, 1]:
        results(client, import_rows(client, [row(client, career_group=f'group-{i}',
            source_url=f'https://publisher.example.test/jobs/{i}', classification_reason='SYNTHETIC mapping')]))
    data = deepcopy(client.catalogue)
    data['majors'][0]['career_groups'] = deepcopy(data['majors'][1]['career_groups'])
    client.app.state.recommendation.import_catalog(data)
    jobs = client.get(BASE + '/jobs', params={'major_id': data['majors'][0]['id']}).json()
    assert jobs['total'] == 1 and jobs['items'][0]['career_group'] == 'group-1'
