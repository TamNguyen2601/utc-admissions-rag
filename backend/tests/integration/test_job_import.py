"""E1 SQLite/index integration; synthetic encoder, no live source or catalogue."""

import pytest

from sqlalchemy import select

from app.db.base import utc_now
from app.models.knowledge import DataSource, Document, DocumentChunk, DocumentOrigin
from tests.jobs_support import (job_client, admin_client, row, import_rows, results, stored_jobs, BASE)  # noqa: F401


def test_mixed_six_rows_first_valid_wins_and_identity_conflict(job_client):
    client = job_client
    j = row(client, external_id='J', source_url='https://publisher.example.test/jobs/j')
    k = row(client, external_id='K', source_url='https://publisher.example.test/jobs/k')
    results(client, import_rows(client, [j, k]))
    with client.app.state.database.session() as db:
        before = db.scalar(select(DocumentOrigin).where(DocumentOrigin.canonical_url == k['source_url']))
        snapshot = (before.id, before.document_id, before.retrieved_at)
    n = row(client, external_id='N')
    updated = j | {'observed_status': 'closed'}
    run, items = results(client, import_rows(client, [n, n, n | {'title': 'conflict'},
        updated, updated, k | {'external_id': 'different', 'collected_at': utc_now().isoformat()}]))
    assert (run.new_count, run.updated_count, run.skipped_count, run.error_count) == (1, 1, 2, 2)
    assert [i.outcome for i in items] == ['new', 'skipped', 'error', 'updated', 'skipped', 'error']
    assert [i.reason for i in items] == [None, None, 'conflict', None, None, 'identity_conflict']
    assert [i.item_index for i in items] == list(range(1, 7))
    assert run.state == 'partial' and len(stored_jobs(client)) == 3
    with client.app.state.database.session() as db:
        origin = db.get(DocumentOrigin, snapshot[0])
        assert (origin.id, origin.document_id, origin.retrieved_at) == snapshot


def test_observation_skip_status_update_and_no_encoding(job_client):
    client = job_client
    r = row(client, external_id='A')
    results(client, import_rows(client, [r]))
    initial = stored_jobs(client)[0]
    client.job_model.encode.reset_mock()
    r['collected_at'] = utc_now().isoformat()
    run, _ = results(client, import_rows(client, [r]))
    assert run.skipped_count == 1
    assert stored_jobs(client)[0].updated_at == initial.updated_at
    r['observed_status'] = 'closed'
    run, _ = results(client, import_rows(client, [r]))
    assert run.updated_count == 1
    assert stored_jobs(client)[0].id == initial.id
    assert stored_jobs(client)[0].updated_at > initial.updated_at
    client.job_model.encode.assert_not_called()


def test_same_text_two_urls_share_document_but_count_two_jobs(job_client):
    client = job_client
    a = row(client)
    b = a | {'source_url': 'https://publisher.example.test/jobs/two'}
    run, _ = results(client, import_rows(client, [a, b]))
    jobs = stored_jobs(client)
    assert run.new_count == 2 and len(jobs) == 2
    response = client.get(BASE + '/jobs').json()
    assert response['observed_open_count'] == 2 and response['total'] == 2
    assert len({j['document_id'] for j in response['items']}) == 1
    assert len({j['origin_id'] for j in response['items']}) == 2


def test_invalid_first_does_not_claim_identity(job_client):
    client = job_client
    good = row(client, external_id='A')
    run, items = results(client, import_rows(client, [good | {'collected_at': 'invalid'}, good]))
    assert [i.outcome for i in items] == ['error', 'new']
    assert run.error_count == 1 and len(stored_jobs(client)) == 1


def test_url_key_upgrade_missing_id_and_url_move(job_client):
    client = job_client
    r = row(client)
    results(client, import_rows(client, [r]))
    identity = stored_jobs(client)[0].id
    run, items = results(client, import_rows(client, [r | {'external_id': 'stable'}, r]))
    assert [i.outcome for i in items] == ['updated', 'skipped']
    assert stored_jobs(client)[0].identity_key == 'ext:stable'
    moved = r | {'external_id': 'stable', 'source_url': 'https://publisher.example.test/jobs/moved'}
    run, _ = results(client, import_rows(client, [moved]))
    assert run.updated_count == 1
    assert len(stored_jobs(client)) == 1 and stored_jobs(client)[0].id == identity
    assert client.get(BASE + '/jobs').json()['items'][0]['source_url'] == moved['source_url']


@pytest.mark.parametrize('changes', [
    {'title': 'SYNTHETIC changed title'}, {'employer': 'SYNTHETIC changed employer'},
    {'description': 'SYNTHETIC changed description'}, {'observed_status': 'closed'},
    {'deadline_at': '2020-01-01'}, {'posted_at': '2020-01-01T07:00:00+07:00'},
    {'career_group': 'file-group', 'classification_reason': 'SYNTHETIC explicit file mapping'},
])
def test_each_business_change_updates_same_job(job_client, changes):
    client, r = job_client, row(job_client, external_id='A')
    results(client, import_rows(client, [r]))
    identity = stored_jobs(client)[0].id
    run, _ = results(client, import_rows(client, [r | changes]))
    assert run.updated_count == 1
    assert len(stored_jobs(client)) == 1 and stored_jobs(client)[0].id == identity


def test_duplicate_does_not_write_observation_and_conflict_preserves_first(job_client):
    client = job_client
    r = row(client, external_id='A')
    changed_observation = r | {'collected_at': utc_now().isoformat()}
    run, items = results(client, import_rows(client,
        [r, changed_observation, changed_observation | {'description': 'conflict'}]))
    assert [i.outcome for i in items] == ['new', 'skipped', 'error']
    assert items[-1].reason == 'conflict'
    item = client.get(BASE + '/jobs').json()['items'][0]
    assert item['collected_at'].replace('Z', '+00:00') == r['collected_at']


def test_normalized_nfc_whitespace_url_and_timezone_skip(job_client):
    import unicodedata
    client = job_client
    r = row(client, external_id='A', title='SYNTHETIC kỹ sư', posted_at='2020-01-01T00:00:00Z')
    results(client, import_rows(client, [r]))
    normalized = r | {'title': '  ' + unicodedata.normalize('NFD', r['title']) + '  ',
        'description': r['description'].replace(' ', '  \n'),
        'posted_at': '2020-01-01T07:00:00+07:00',
        'source_url': r['source_url'] + '?utm_source=test#top'}
    client.job_model.encode.reset_mock()
    run, _ = results(client, import_rows(client, [normalized]))
    assert run.skipped_count == 1
    client.job_model.encode.assert_not_called()


def test_snapshot_optional_omission_clears_fields_without_downgrading_id(job_client):
    client = job_client
    r = row(client, external_id='A', posted_at='2020-01-01T00:00:00Z')
    results(client, import_rows(client, [r]))
    r = {k: v for k, v in r.items() if k not in {'external_id', 'posted_at', 'deadline_at', 'observed_status'}}
    run, _ = results(client, import_rows(client, [r]))
    job = stored_jobs(client)[0]
    assert run.updated_count == 1 and job.identity_key == 'ext:A'
    assert job.posted_at is None and job.deadline_at is None and job.observed_status == 'unknown'


def test_url_destination_owned_by_other_identity_is_not_overwritten(job_client):
    client = job_client
    a = row(client, external_id='A')
    b = row(client, external_id='B', source_url=a['source_url'] + '-b')
    results(client, import_rows(client, [a, b]))
    before = client.get(BASE + '/jobs').json()['items']
    run, items = results(client, import_rows(client, [a | {'source_url': b['source_url']}]))
    assert run.error_count == 1 and items[0].reason == 'identity_conflict'
    assert client.get(BASE + '/jobs').json()['items'] == before


def test_later_id_does_not_upgrade_first_valid_url_row(job_client):
    client, r = job_client, row(job_client)
    run, items = results(client, import_rows(client, [r, r | {'external_id': 'later-id'}]))
    assert [i.outcome for i in items] == ['new', 'error'] and items[1].reason == 'conflict'
    assert stored_jobs(client)[0].external_id is None


def test_staging_failure_keeps_job_origin_document_and_prior_rows(job_client):
    client = job_client
    r = row(client, external_id='A')
    results(client, import_rows(client, [r]))
    before = client.get(BASE + '/jobs').json()['items']
    indexer = client.app.state.documents.indexer
    original = indexer.index
    def fail(text, metadata):
        if 'BROKEN' in text: raise RuntimeError('private secret')
        return original(text, metadata)
    indexer.index = fail
    run, items = results(client, import_rows(client,
        [r | {'source_url': r['source_url'] + '-new', 'external_id': 'N'},
         r | {'description': 'BROKEN'}]))
    assert run.new_count == 1 and run.error_count == 1
    assert items[-1].reason == 'PROCESSING_FAILED'
    assert next(i for i in client.get(BASE + '/jobs').json()['items'] if i['identity_key'] == 'ext:A') == before[0]


def test_database_failure_rolls_back_new_document_origin_and_job(job_client, monkeypatch):
    from sqlalchemy import event, func
    client = job_client
    database = client.app.state.database
    def fail_insert(mapper, connection, target): raise RuntimeError('SYNTHETIC constraint failure')
    event.listen(__import__('app.models.career', fromlist=['JobPosting']).JobPosting, 'before_insert', fail_insert)
    try:
        run, _ = results(client, import_rows(client, [row(client)]))
        assert run.error_count == 1
        with database.session() as db:
            for entity in (Document, DocumentOrigin, DocumentChunk):
                assert db.scalar(select(func.count()).select_from(entity)) == 0
    finally:
        event.remove(__import__('app.models.career', fromlist=['JobPosting']).JobPosting, 'before_insert', fail_insert)


def test_disable_update_stays_disabled_and_document_delete_cascades_jobs(job_client):
    from app.models.career import JobPosting
    client = job_client
    r = row(client, external_id='A')
    results(client, import_rows(client, [r]))
    item = client.get(BASE + '/jobs').json()['items'][0]
    with client.app.state.database.session() as db:
        db.get(Document, item['document_id']).enabled = False
        db.commit()
    results(client, import_rows(client, [r | {'description': 'SYNTHETIC new description'}]))
    assert client.get(BASE + '/jobs').json()['status'] == 'data_missing'
    with client.app.state.database.session() as db:
        job = db.get(JobPosting, item['id'])
        origin = db.get(DocumentOrigin, job.origin_id)
        document = db.get(Document, origin.document_id)
        assert document.enabled is False
        db.delete(document)
        db.commit()
        assert db.scalar(select(JobPosting).where(JobPosting.id == item['id'])) is None


def test_unique_business_key_and_origin_cascade(job_client):
    from sqlalchemy.exc import IntegrityError
    from app.models.career import JobPosting
    client = job_client
    results(client, import_rows(client, [row(client, external_id='A')]))
    with client.app.state.database.session() as db:
        job = db.scalar(select(JobPosting))
        duplicate = {column.name: getattr(job, column.name) for column in JobPosting.__table__.columns if column.name != 'id'}
        db.add(JobPosting(**duplicate))
        with pytest.raises(IntegrityError): db.commit()
        db.rollback()
        db.delete(db.get(DocumentOrigin, job.origin_id))
        db.commit()
        assert db.scalar(select(JobPosting)) is None


def test_career_document_public_source_uses_real_index_pipeline(job_client):
    client = job_client
    results(client, import_rows(client, [row(client)]))
    item = client.get(BASE + '/jobs').json()['items'][0]
    response = client.get(BASE + f'/documents/{item["document_id"]}/source')
    assert response.status_code == 200, response.text
    source = response.json()
    assert source['origins'] == [{'url': item['source_url'], 'source_name': item['source_name']}]
    assert any('SYNTHETIC engineering' in excerpt['text'] for excerpt in source['excerpts'])
    with client.app.state.database.session() as db:
        chunks = db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == item['document_id'])).all()
        assert chunks and all(c.numeric_eligible is False for c in chunks)


@pytest.mark.parametrize('action', ['delete', 'revoke'])
def test_recheck_document_and_permission_after_staging(job_client, action):
    from app.models.career import JobPosting
    client = job_client
    r = row(client, external_id='A')
    results(client, import_rows(client, [r]))
    job_id = stored_jobs(client)[0].id
    original = client.app.state.documents.indexer.index
    def stage_then_change(text, metadata):
        chunks = original(text, metadata)
        with client.app.state.database.session() as db:
            if action == 'delete':
                job = db.get(JobPosting, job_id)
                origin = db.get(DocumentOrigin, job.origin_id)
                db.delete(db.get(Document, origin.document_id))
            else:
                db.get(DataSource, client.job_source).enabled = False
            db.commit()
        return chunks
    client.app.state.documents.indexer.index = stage_then_change
    run, items = results(client, import_rows(client, [r | {'description': 'SYNTHETIC changed during stage'}]))
    assert run.error_count == 1
    if action == 'delete':
        assert items[0].reason == 'DOCUMENT_REMOVED' and stored_jobs(client) == []
    else:
        assert stored_jobs(client)[0].description == r['description']
    assert client.get(BASE + '/jobs').json()['status'] == 'data_missing'


def test_sqlite_reopen_retains_jobs_and_provenance(job_client, settings):
    from app.db.session import Database
    from app.services.jobs import JobService
    client = job_client
    results(client, import_rows(client, [row(client)]))
    before = client.app.state.jobs.list_jobs()
    reopened = Database(settings)
    try:
        reopened.initialize()
        service = JobService(reopened, client.app.state.documents, client.app.state.coordinator)
        after = service.list_jobs()
        assert after['items'] == before['items'] and after['observed_open_count'] == 1
    finally:
        reopened.dispose()
