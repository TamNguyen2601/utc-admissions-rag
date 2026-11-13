"""Jobs/import REST; major filter is explicitly a resolver stub at E1."""
import pytest

from tests.jobs_support import (job_client, admin_client, row, import_rows, results, BASE)  # noqa: F401


def test_empty_is_missing_and_bad_bearer_is_unauthorized(job_client):
    response = job_client.get(BASE + '/jobs').json()
    assert response['status'] == 'data_missing' and response['observed_open_count'] is None
    assert response['items'] == [] and response['total'] == 0
    assert job_client.get(BASE + '/jobs', headers={'Authorization': 'Bearer invalid'}).status_code == 401


@pytest.mark.parametrize('content,filename,media,status', [
    (b'{}', 'x.json', 'application/json', 422),
    (b'[{broken]', 'x.json', 'application/json', 422),
    (b'title,title\na,b', 'x.csv', 'text/csv', 422),
    (b'[]', 'x.txt', 'text/plain', 415),
    (b'x' * (20 * 1024 * 1024 + 1), 'x.json', 'application/json', 413),
])
def test_structure_rejected_without_run(job_client, content, filename, media, status):
    from sqlalchemy import func, select
    from app.models.crawl import CrawlRun
    client = job_client
    response = client.post(BASE + '/admin/jobs/import', files={'file': (filename, content, media)})
    assert response.status_code == status
    with client.app.state.database.session() as db:
        assert db.scalar(select(func.count()).select_from(CrawlRun)) == 0


def test_major_resolver_stub_and_filters(job_client):
    from uuid import uuid4
    from fastapi import HTTPException

    valid, stale, missing = str(uuid4()), str(uuid4()), str(uuid4())

    class ResolverStub:
        def career_groups(self): return {'engineering', 'other'}
        def major_groups(self, major_id):
            if major_id == valid: return {'engineering'}
            if major_id == stale: return None
            raise HTTPException(404)

    client = job_client
    client.app.state.jobs.resolver = ResolverStub()
    r = row(client, career_group='engineering', classification_reason='SYNTHETIC file classification')
    results(client, import_rows(client, [r, r | {'source_url': r['source_url'] + '-null', 'career_group': None}]))
    assert client.get(BASE + '/jobs', params={'major_id': valid}).json()['total'] == 1
    assert client.get(BASE + '/jobs', params={'major_id': stale}).json()['status'] == 'data_missing'
    assert client.get(BASE + '/jobs', params={'major_id': missing}).status_code == 404
    assert client.get(BASE + '/jobs', params={'career_group': 'made-up'}).status_code == 422


def test_status_read_time_deadline_vietnam_and_count_independent_of_status_page(job_client):
    from datetime import datetime, timezone
    client = job_client
    client.app.state.jobs.now = lambda: datetime(2026, 11, 13, 16, 59, 59, tzinfo=timezone.utc)
    common = row(client, collected_at='2026-11-12T00:00:00Z', deadline_at='2026-11-13')
    rows = [common, common | {'source_url': common['source_url'] + '-expired', 'observed_status': 'closed'},
        common | {'source_url': common['source_url'] + '-unknown', 'observed_status': 'unknown'},
        {k: v for k, v in (common | {'source_url': common['source_url'] + '-no-deadline'}).items() if k != 'deadline_at'}]
    results(client, import_rows(client, rows))
    response = client.get(BASE + '/jobs', params={'status': 'expired', 'page_size': 1}).json()
    assert response['status'] == 'ready' and response['total'] == 1 and response['observed_open_count'] == 1
    response = client.get(BASE + '/jobs', params={'status': 'unverified'}).json()
    assert response['total'] == 2 and response['observed_open_count'] == 1
    item = client.get(BASE + '/jobs', params={'status': 'open'}).json()['items'][0]
    assert item['deadline_at'] == '2026-11-13T16:59:59.999999Z'
    client.app.state.jobs.now = lambda: datetime(2026, 11, 13, 17, 0, tzinfo=timezone.utc)
    response = client.get(BASE + '/jobs', params={'status': 'open', 'page': 2}).json()
    assert response['status'] == 'ready' and response['total'] == 0
    assert response['observed_open_count'] == 0 and response['items'] == []


def test_csv_default_and_row_override_publisher_provenance(job_client):
    import csv
    import io
    from tests.contract.knowledge_support import create_source
    client = job_client
    second = create_source(client, name='SYNTHETIC second publisher', kind='career',
        base_url='https://second.example.test/', allowed_paths=['/'],
        robots_url='https://second.example.test/robots.txt', terms_url='https://second.example.test/terms')
    a = row(client)
    b = a | {'source_id': second['id'], 'source_url': 'https://second.example.test/jobs/a',
             'collected_at': '2020-01-01T01:00:00+07:00'}
    a.pop('source_id')
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=list(b))
    writer.writeheader()
    writer.writerows([a, b])
    response = client.post(BASE + '/admin/jobs/import', data={'source_id': client.job_source},
        files={'file': ('synthetic.csv', stream.getvalue().encode('utf-8-sig'), 'text/csv')})
    run, items = results(client, response)
    assert run.new_count == 2
    data = client.get(BASE + '/jobs').json()
    by_source = {item['source_id']: item for item in data['items']}
    assert by_source[second['id']]['source_name'] == second['name']
    assert by_source[second['id']]['collected_at'] == '2019-12-31T18:00:00Z'
    assert by_source[second['id']]['source_url'] == b['source_url']
    assert by_source[client.job_source]['source_url'] == a['source_url']
    assert data['observed_open_count'] == 2
    assert len({item['document_id'] for item in data['items']}) == 1


@pytest.mark.parametrize('changes', [
    {'source_url': 'http://publisher.example.test/jobs/a'},
    {'source_url': 'https://publisher.example.test/outside/a'},
    {'source_url': 'https://127.0.0.1/jobs/a'},
    {'source_id': None}, {'source_id': 'not-a-uuid'},
    {'collected_at': '2999-01-01T00:00:00Z'}, {'posted_at': '2999-01-01T00:00:00Z'},
    {'deadline_at': '2026-99-99'}, {'collected_at': '2020-01-01T00:00:00'},
    {'collected_at': '1577836800'}, {'posted_at': 1577836800},
    {'observed_status': 'invalid'}, {'external_id': 123}, {'extra': 'bad'},
])
def test_bad_row_quarantined_good_row_still_applies(job_client, changes):
    client = job_client
    run, items = results(client, import_rows(client, [row(client, **changes), row(client)]))
    assert run.error_count == 1 and run.new_count == 1 and run.state == 'partial'
    assert [i.outcome for i in items] == ['error', 'new']
    if 'source_url' in changes:
        assert items[0].canonical_url is None


@pytest.mark.parametrize('field,value', [('enabled', False), ('permission_status', 'unknown'),
    ('permission_status', 'denied')])
def test_source_permission_blocks_import_and_existing_jobs(job_client, field, value):
    from app.models.knowledge import DataSource
    client = job_client
    results(client, import_rows(client, [row(client)]))
    with client.app.state.database.session() as db:
        source = db.get(DataSource, client.job_source)
        source.enabled = False
        setattr(source, field, value)
        db.commit()
    run, items = results(client, import_rows(client, [row(client)]))
    assert run.error_count == 1
    assert client.get(BASE + '/jobs').json()['status'] == 'data_missing'


def test_import_role_busy_and_closed_multipart_schema(job_client):
    from app.models.crawl import CrawlRun
    from sqlalchemy import func, select
    client = job_client
    auth = client.headers.pop('Authorization')
    assert import_rows(client, []).status_code == 401
    credentials = {'email': 'jobs-user@example.test', 'password': 'synthetic-password'}
    client.post(BASE + '/auth/register', json=credentials)
    token = client.post(BASE + '/auth/login', json=credentials).json()['access_token']
    client.headers['Authorization'] = 'Bearer ' + token
    assert import_rows(client, []).status_code == 403
    client.headers['Authorization'] = auth
    assert import_rows(client, [], extra='not-allowed').status_code == 422
    assert import_rows(client, [], source_id=client.job_source, extra='not-allowed').status_code == 422
    assert import_rows(client, [], source_id='invalid').status_code == 422
    coordinator = client.app.state.coordinator
    active = coordinator.claim('manual')
    try:
        response = import_rows(client, [row(client)])
        assert response.status_code == 409 and response.json()['error']['code'] == 'RUN_IN_PROGRESS'
        with client.app.state.database.session() as db:
            assert db.scalar(select(func.count()).select_from(CrawlRun)) == 1
    finally:
        coordinator.finish(active.id)


@pytest.mark.parametrize('params', [{'status': 'invalid'}, {'page': 0}, {'page_size': 101},
                                    {'major_id': 'not-a-uuid'}])
def test_list_input_validation(job_client, params):
    assert job_client.get(BASE + '/jobs', params=params).status_code == 422
