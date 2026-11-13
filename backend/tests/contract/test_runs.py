"""Admin run contract; actual auth/SQLite, blocked synthetic pipeline only."""
from threading import Event
from uuid import uuid4

import pytest

from tests.contract.knowledge_support import admin_client, create_source, upload

BASE = '/api/v1/admin/runs'


def test_run_returns_202_before_pipeline_finishes_and_busy(admin_client):
    client = admin_client
    source = create_source(client)
    entered, release = Event(), Event()
    def crawl(run_id, source_ids=None):
        entered.set()
        assert release.wait(10)
    client.app.state.crawl.run = crawl
    try:
        accepted = client.post(BASE, json={})
        assert accepted.status_code == 202
        run_id = accepted.json()['run_id']
        assert entered.wait(3) and not release.is_set()
        assert accepted.json() == {'run_id': run_id, 'state': 'running'}
        assert accepted.headers['location'] == f'{BASE}/{run_id}'
        busy = client.post(BASE, json={})
        assert busy.status_code == 409 and busy.json()['error']['code'] == 'RUN_IN_PROGRESS'
        assert upload(client, source['id']).status_code == 409
        imported = client.post('/api/v1/admin/jobs/import', files={'file': ('x.json', b'[]', 'application/json')})
        assert imported.status_code == 409 and imported.json()['error']['code'] == 'RUN_IN_PROGRESS'
        assert client.get(BASE).json()['total'] == 1
        detail = client.get(f'{BASE}/{run_id}').json()
        assert detail['trigger'] == 'manual' and detail['triggered_by']
        assert detail['counts'] == dict(new=0, updated=0, skipped=0, error=0)
        assert detail['state'] == 'running'
        stopped = client.post(f'{BASE}/{run_id}/stop').json()
        assert stopped['state'] == 'stop_requested' and stopped['stop_requested_by']
        assert client.post(f'{BASE}/{run_id}/stop').json() == stopped
    finally:
        release.set()
        assert client.app.state.coordinator.wait_idle(5)
    assert client.get(f'{BASE}/{run_id}').json()['state'] == 'cancelled'
    rerun = client.post(BASE, json={})
    assert rerun.status_code == 202 and rerun.json()['run_id'] != run_id
    assert client.app.state.coordinator.wait_idle(5)
    assert client.post(f'{BASE}/{run_id}/stop').json()['state'] == 'cancelled'


def test_run_skipped_busy_serialization_and_pagination(admin_client):
    client = admin_client
    coordinator = client.app.state.coordinator
    active = coordinator.claim('upload')
    skipped = coordinator.claim('scheduled')
    try:
        detail = client.get(f'{BASE}/{skipped.id}').json()
        assert detail['state'] == 'skipped_busy' and detail['trigger'] == 'scheduled'
        assert detail['started_at'] is None and detail['created_at'] == detail['ended_at']
        assert detail['counts'] == dict(new=0, updated=0, skipped=0, error=0)
        assert detail['source_outcomes'] == []
        assert client.get(f'{BASE}/{skipped.id}/items').json() == {
            'items': [], 'total': 0, 'page': 1, 'page_size': 20}
        assert client.post(f'{BASE}/{skipped.id}/stop').json() == detail
        assert coordinator.active_run_id == active.id
        page = client.get(BASE, params={'page_size': 1}).json()
        assert page['total'] == 2 and page['items'][0]['id'] == skipped.id
        assert client.get(BASE, params={'page': 2, 'page_size': 1}).json()['items'][0]['id'] == active.id
        assert client.get(BASE, params={'page_size': 101}).status_code == 422
        assert client.get(f'{BASE}/{active.id}/items?page=0').status_code == 422
    finally:
        coordinator.finish(active.id)


@pytest.mark.parametrize('suffix,method', [('', 'post'), ('', 'get'), ('/x', 'get'),
    ('/x/items', 'get'), ('/x/stop', 'post')])
def test_runs_require_admin(admin_client, suffix, method):
    client = admin_client
    client.headers.pop('Authorization')
    assert getattr(client, method)(BASE + suffix).status_code == 401
    credentials = dict(email='run-user@example.test', password='synthetic-password')
    client.post('/api/v1/auth/register', json=credentials)
    token = client.post('/api/v1/auth/login', json=credentials).json()['access_token']
    client.headers['Authorization'] = f'Bearer {token}'
    assert getattr(client, method)(BASE + suffix).status_code == 403


def test_runs_validation_and_missing_resources(admin_client):
    client = admin_client
    for payload in ({'trigger': 'scheduled'}, {'source_id': 'bad'}):
        assert client.post(BASE, json=payload).status_code == 422
    assert client.post(BASE, json={'source_id': str(uuid4())}).status_code == 404
    assert client.get(BASE).json()['total'] == 0
    source = create_source(client, enabled=False, permission_status='unknown', reuse_basis=None, checked_at=None)
    assert client.post(BASE, json={'source_id': source['id']}).status_code == 422
    for suffix, method in [('', 'get'), ('/items', 'get'), ('/stop', 'post')]:
        assert getattr(client, method)(f'{BASE}/{uuid4()}{suffix}').status_code == 404
        assert getattr(client, method)(f'{BASE}/bad{suffix}').status_code == 422


def test_selected_source_and_paginated_item_contract(admin_client):
    from app.db.base import utc_now
    from app.services.documents import IngestionOutcome
    client = admin_client
    source = create_source(client)
    seen = []
    def pipeline(run_id, source_ids=None):
        seen.append(source_ids)
        for index in (1, 2):
            client.app.state.documents.record_item(run_id, index, source['id'], None,
                IngestionOutcome('skipped', None, 'SYNTHETIC_CONTRACT_STUB'), utc_now())
    client.app.state.crawl.run = pipeline
    receipt = client.post(BASE, json={'source_id': source['id']})
    assert receipt.status_code == 202
    assert client.app.state.coordinator.wait_idle(5)
    run_id = receipt.json()['run_id']
    assert seen == [[source['id']]]
    detail = client.get(f'{BASE}/{run_id}').json()
    assert detail['source_id'] == source['id'] and detail['counts']['skipped'] == 2
    assert detail['state'] == 'succeeded'
    for page in (1, 2):
        response = client.get(f'{BASE}/{run_id}/items', params={'page': page, 'page_size': 1}).json()
        assert response['total'] == 2 and response['page'] == page
        assert response['items'][0] == dict(item_index=page, source_id=source['id'], canonical_url=None,
            document_id=None, outcome='skipped', reason='SYNTHETIC_CONTRACT_STUB',
            started_at=response['items'][0]['started_at'], ended_at=response['items'][0]['ended_at'])


@pytest.mark.parametrize('trigger', ['upload', 'job_import', 'scheduled'])
def test_manual_rejects_other_ingestion_trigger_in_same_slot(admin_client, trigger):
    client = admin_client
    coordinator = client.app.state.coordinator
    active = coordinator.claim(trigger)
    try:
        busy = client.post(BASE, json={})
        assert busy.status_code == 409 and busy.json()['error']['code'] == 'RUN_IN_PROGRESS'
        assert client.get(BASE).json()['total'] == 1
    finally:
        coordinator.finish(active.id)


@pytest.mark.parametrize('stop', [False, True])
def test_lifespan_recovers_unfinished_runs_and_starts_one_scheduler(application, settings, stop):
    from fastapi.testclient import TestClient
    from app.db.session import Database
    from app.models.crawl import CrawlRun
    from app.services.coordinator import Coordinator
    database = Database(settings)
    database.initialize()
    coordinator = Coordinator(database)
    active = coordinator.claim('manual')
    if stop:
        coordinator.request_stop(active.id, None)
    skipped = coordinator.claim('scheduled')
    database.dispose()
    with TestClient(application):
        with application.state.database.session() as db:
            assert db.get(CrawlRun, active.id).state == 'interrupted'
            assert db.get(CrawlRun, active.id).ended_at is not None
            assert db.get(CrawlRun, skipped.id).state == 'skipped_busy'
        assert application.state.coordinator.active_run_id is None
        assert application.state.scheduler.scheduler.running
        assert len(application.state.scheduler.scheduler.get_jobs()) == 1
    assert not application.state.scheduler.scheduler.running
