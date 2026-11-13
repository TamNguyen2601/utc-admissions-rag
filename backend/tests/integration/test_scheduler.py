"""Checkpoint F: real APScheduler decisions, SQLite/ingestion/chunking; fake time/HTTP/E5.

TickScheduler disables wall timers only. BaseScheduler computes due jobs/next_run_time
with the real CronTrigger and MemoryJobStore. TickExecutor invokes the cron callback
inline; production dispatch still runs the actual pipeline in its claimed thread.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import io
import json
import logging
from pathlib import Path
from threading import Event, Lock
from types import SimpleNamespace

from apscheduler.executors.base import BaseExecutor
from apscheduler.schedulers.base import BaseScheduler
from apscheduler.jobstores.memory import MemoryJobStore
from fastapi import HTTPException
import pytest
from sqlalchemy import func, select

from app.db.session import Database
from app.core.logging import logger, SafeMetadataFormatter
from app.models.crawl import CrawlRun, CrawlRunItem
from app.models.knowledge import DataSource, Document, DocumentChunk, DocumentOrigin
from app.services.coordinator import Coordinator, RunInProgress
from app.services.crawl import CrawlService, SafeFetcher, FetchResult
from app.services.documents import DocumentService
from app.services.embedding import Indexer
from app.services.extraction import Extractor
from app.services.jobs import JobService
from app.services.scheduler import CrawlScheduler, JOB_ID, TIMEZONE
from tests.knowledge_support import ingestion, real_indexer


class Clock:
    value = datetime(2026, 11, 13, 10, tzinfo=TIMEZONE)
    elapsed = 0

    def now(self):
        return self.value.astimezone(timezone.utc)

    def sleep(self, seconds):
        self.elapsed += seconds

    def monotonic(self):
        return self.elapsed

    def midnight(self, day):
        self.value = datetime(2026, 11, day, tzinfo=TIMEZONE)


class TickExecutor(BaseExecutor):
    def _do_submit_job(self, job, run_times):
        for _ in run_times:
            asyncio.run(job.func())
        self._run_job_success(job.id, [])


class TickScheduler(BaseScheduler):
    def _create_default_executor(self):
        return TickExecutor()

    def wakeup(self):
        pass

    def shutdown(self, wait=True):
        super().shutdown(wait)


@pytest.fixture
def runtime(ingestion, settings, monkeypatch):
    source, documents, coordinator = real_indexer(ingestion, settings)
    clock = Clock()
    class ClockDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock.now().astimezone(tz)
    monkeypatch.setattr('apscheduler.schedulers.base.datetime', ClockDateTime)
    monkeypatch.setattr('app.services.documents.utc_now', clock.now)
    monkeypatch.setattr('app.services.crawl.utc_now', clock.now)
    monkeypatch.setattr('socket.getaddrinfo', lambda *a, **k: [(2, 1, 6, '', ('8.8.8.8', 443))])
    coordinator.now = clock.now
    documents.extractor.monotonic = clock.monotonic
    html = [b'<main><h1>SYNTHETIC engineering</h1><a href="/b">next</a></main>']
    calls = []
    def transport(url, **kwargs):
        calls.append(url)
        content = b'User-agent: *\nAllow: /' if url.endswith('/robots.txt') else (
            b'<main><h1>SYNTHETIC medicine second item</h1></main>' if url.endswith('/b') else html[0])
        return FetchResult(url, content, {'Content-Type': 'text/plain' if url.endswith('/robots.txt') else
            'application/pdf' if content.startswith(b'%PDF') else 'text/html'})
    fetcher = SafeFetcher(transport=transport, now=clock.now, monotonic=clock.monotonic, sleep=clock.sleep)
    jobs = JobService(documents.database, documents, coordinator, now=clock.now)
    crawl = CrawlService(documents.database, documents, coordinator, fetcher=fetcher, jobs=jobs)
    scheduler = CrawlScheduler(coordinator, crawl,
        scheduler=TickScheduler(timezone=TIMEZONE, jobstores={'default': MemoryJobStore()}))
    scheduler.start()
    env = SimpleNamespace(source=source, documents=documents, coordinator=coordinator, clock=clock,
        crawl=crawl, scheduler=scheduler, calls=calls, html=html, jobs=jobs)
    yield env
    scheduler.shutdown()
    coordinator.close()


def runs(env):
    with env.documents.database.session() as db:
        return db.scalars(select(CrawlRun).order_by(CrawlRun.created_at, CrawlRun.id)).all()


def manual(env):
    env.clock.value += timedelta(seconds=1)
    run = env.coordinator.claim('manual')
    env.coordinator.start(run.id, env.crawl.run)
    return run


def tick(env, day):
    env.clock.midnight(day)
    env.scheduler.scheduler._process_jobs()


def assert_idle(env):
    assert env.coordinator.wait_idle(5)
    assert env.coordinator.active_run_id is None


def test_manual_at_ten_does_not_reset_midnight_scheduled_idle(runtime):
    e = runtime
    job = e.scheduler.scheduler.get_job(JOB_ID)
    midnight = datetime(2026, 11, 14, tzinfo=TIMEZONE)
    assert job.next_run_time == midnight
    assert job.max_instances == 1 and job.coalesce and job.misfire_grace_time == 60
    assert str(job.trigger.timezone) == 'Asia/Ho_Chi_Minh'
    first = manual(e)
    assert_idle(e)
    assert job.next_run_time == midnight
    assert runs(e)[0].state == 'succeeded' and runs(e)[0].new_count == 2
    tick(e, 14)
    assert_idle(e)
    records = runs(e)
    assert len(records) == 2 and records[-1].trigger == 'scheduled'
    assert records[-1].skipped_count == 2 and records[-1].state == 'succeeded'
    assert records[-1].id != first.id
    assert job.next_run_time == datetime(2026, 11, 15, tzinfo=TIMEZONE)


@pytest.mark.parametrize('stage', ['network', 'extraction', 'ocr', 'embedding'])
def test_busy_tick_is_logged_before_item_released_and_never_queued(runtime, stage, monkeypatch):
    e = runtime
    entered, release = Event(), Event()
    if stage == 'ocr':
        from tests.unit.test_extraction import tsv
        e.html[0] = (Path(__file__).parents[1] / 'fixtures/utc/scan.pdf').read_bytes()
        e.documents.extractor.runner = lambda *a, **kw: SimpleNamespace(returncode=0, stdout=tsv(), stderr='')
    target, attribute = {'network': (e.crawl.fetcher, 'transport'),
        'extraction': (e.documents.extractor, 'extract'),
        'ocr': (e.documents.extractor, 'runner'),
        'embedding': (e.documents.indexer.encoder.model, 'encode')}[stage]
    original = getattr(target, attribute)
    blocked = False
    def hold(*args, **kwargs):
        nonlocal blocked
        if not blocked:
            blocked = True
            entered.set()
            assert release.wait(10)
        return original(*args, **kwargs)
    monkeypatch.setattr(target, attribute, hold)
    active, maximum = 0, 0
    pipeline = e.crawl.run
    def counted(*args, **kwargs):
        nonlocal active, maximum
        active += 1
        maximum = max(active, maximum)
        try:
            return pipeline(*args, **kwargs)
        finally:
            active -= 1
    monkeypatch.setattr(e.crawl, 'run', counted)
    run = manual(e)
    try:
        assert entered.wait(3)
        for trigger in ('manual', 'upload', 'job_import'):
            with pytest.raises(RunInProgress):
                e.coordinator.claim(trigger)
        tick(e, 14)
        # This assertion is deliberately before release: mutex cannot cover pipeline I/O.
        skipped = [r for r in runs(e) if r.state == 'skipped_busy']
        assert len(skipped) == 1
        skip = skipped[0]
        assert skip.started_at is None and skip.ended_at == skip.created_at == e.clock.now()
        assert (skip.new_count, skip.updated_count, skip.skipped_count, skip.error_count) == (0, 0, 0, 0)
        assert skip.source_outcomes_json == []
        with e.documents.database.session() as db:
            assert db.scalar(select(func.count()).select_from(CrawlRunItem)
                             .where(CrawlRunItem.run_id == skip.id)) == 0
            assert db.get(DataSource, e.source.id).last_success_at is None
        e.coordinator.execute(run.id, lambda _: pytest.fail('duplicate execution'))
        assert e.coordinator.active_run_id == run.id
    finally:
        release.set()
        assert_idle(e)
    assert len(runs(e)) == 2 and maximum == 1
    e.coordinator.execute(skip.id, lambda _: pytest.fail('skipped run cannot execute'))
    e.scheduler.scheduler._process_jobs()  # Still the same midnight; no retry on free slot.
    assert len(runs(e)) == 2
    tick(e, 15)
    assert_idle(e)
    assert len(runs(e)) == 3 and maximum == 1
    assert runs(e)[-1].state == 'succeeded'


@pytest.mark.parametrize('stage', ['network', 'embedding'])
def test_stop_finishes_current_item_preserves_it_then_rerun_starts_from_first(runtime, monkeypatch, stage):
    e = runtime
    entered, release = Event(), Event()
    target, attribute = (e.crawl.fetcher, 'transport') if stage == 'network' else (e.documents.indexer, 'index')
    original = getattr(target, attribute)
    def hold(*args, **kwargs):
        if stage == 'network' and args[0].endswith('/robots.txt'):
            return original(*args, **kwargs)
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)
    monkeypatch.setattr(target, attribute, hold)
    first = manual(e)
    try:
        assert entered.wait(3)
        stopped = e.coordinator.request_stop(first.id, None)
        assert stopped.state == 'stop_requested'
        with pytest.raises(RunInProgress):
            e.coordinator.claim('manual')
    finally:
        release.set()
        assert_idle(e)
    assert runs(e)[0].state == 'cancelled' and runs(e)[0].new_count == 1
    assert not any(url.endswith('/b') for url in e.calls)
    with e.documents.database.session() as db:
        assert db.scalar(select(func.count()).select_from(DocumentChunk)) > 0
        assert db.get(DataSource, e.source.id).last_success_at is None
        item = db.scalar(select(CrawlRunItem).where(CrawlRunItem.run_id == first.id))
        assert item.outcome == 'new' and item.item_index == 1
    e.clock.value += timedelta(seconds=1)
    second = e.coordinator.claim('manual')
    assert second.id != first.id
    assert e.coordinator.request_stop(first.id, None).state == 'cancelled'
    assert e.coordinator.active_run_id == second.id
    e.coordinator.start(second.id, e.crawl.run)
    assert_idle(e)
    assert runs(e)[-1].skipped_count == 1 and runs(e)[-1].new_count == 1
    assert runs(e)[-1].state == 'succeeded'


def test_restart_marks_unfinished_interrupted_keeps_disabled_data_and_skips_no_catchup(runtime, settings):
    e = runtime
    manual(e)
    assert_idle(e)
    with e.documents.database.session() as db:
        doc = db.scalar(select(Document))
        identity, text, content_hash = doc.id, doc.content_text, doc.content_hash
        chunks = [(c.id, c.embedding) for c in db.scalars(select(DocumentChunk)).all()]
        origins = [(o.id, o.document_id) for o in db.scalars(select(DocumentOrigin)).all()]
    e.documents.set_enabled(identity, False)
    e.coordinator.claim('manual')  # Simulated process loss before finishing, no live worker.
    e.coordinator.request_stop(e.coordinator.active_run_id, None)
    tick(e, 14)
    old_skip = next(r.id for r in runs(e) if r.state == 'skipped_busy')
    e.scheduler.shutdown()
    e.documents.database.dispose()
    e.clock.value = datetime(2026, 11, 17, 9, tzinfo=TIMEZONE)
    database = Database(settings)
    database.initialize()
    try:
        coordinator = Coordinator(database, now=e.clock.now)
        coordinator.recover_interrupted()
        documents = DocumentService(database, settings.upload_dir, Lock(),
            Indexer(database, e.documents.indexer.encoder), extractor=Extractor(settings, monotonic=e.clock.monotonic))
        crawl = CrawlService(database, documents, coordinator, fetcher=e.crawl.fetcher)
        scheduler = CrawlScheduler(coordinator, crawl, scheduler=TickScheduler(timezone=TIMEZONE))
        scheduler.start()
        try:
            scheduler.scheduler._process_jobs()
            with database.session() as db:
                assert db.get(Document, identity).content_text == text
                assert db.get(Document, identity).content_hash == content_hash
                assert not db.get(Document, identity).enabled
                assert [(c.id, c.embedding) for c in db.scalars(select(DocumentChunk)).all()] == chunks
                assert [(o.id, o.document_id) for o in db.scalars(select(DocumentOrigin)).all()] == origins
                assert db.get(CrawlRun, old_skip).state == 'skipped_busy'
                assert db.scalar(select(func.count()).select_from(CrawlRun)) == 3
                assert db.scalar(select(func.count()).select_from(CrawlRun).where(CrawlRun.state == 'interrupted')) == 1
            assert coordinator.active_run_id is None
            assert scheduler.scheduler.get_job(JOB_ID).next_run_time == datetime(2026, 11, 18, tzinfo=TIMEZONE)
            e.clock.midnight(18)
            scheduler.scheduler._process_jobs()
            assert coordinator.wait_idle(5)
            with database.session() as db:
                assert db.scalar(select(func.count()).select_from(CrawlRun)) == 4
                assert not db.get(Document, identity).enabled
        finally:
            scheduler.shutdown()
            coordinator.close()
    finally:
        database.dispose()
        # The old process has no worker; release its fixture-only RAM slot.
        e.coordinator.finish(e.coordinator.active_run_id)


def test_failed_update_keeps_good_content_and_slot_can_rerun(runtime):
    e = runtime
    manual(e)
    assert_idle(e)
    with e.documents.database.session() as db:
        old = {d.id: (d.content_text, d.content_hash) for d in db.scalars(select(Document))}
        vectors = {c.id: c.embedding for c in db.scalars(select(DocumentChunk))}
    e.html[0] = b'<main><h1>SYNTHETIC engineering changed</h1></main>'
    e.documents.indexer.encoder.model.encode.side_effect = RuntimeError('private path secret')
    failed = manual(e)
    assert_idle(e)
    with e.documents.database.session() as db:
        assert db.get(CrawlRun, failed.id).state == 'failed'
        assert {d.id: (d.content_text, d.content_hash) for d in db.scalars(select(Document))} == old
        assert {c.id: c.embedding for c in db.scalars(select(DocumentChunk))} == vectors
    e.documents.indexer.encoder.model.encode.side_effect = e.documents.indexer.encoder.model._encode
    manual(e)
    assert_idle(e)
    assert runs(e)[-1].state == 'succeeded'


@pytest.mark.parametrize('fail_utc', [False, True])
def test_multiple_sources_share_item_sequence_and_import_only_never_fetches(runtime, fail_utc):
    e = runtime
    with e.documents.database.session() as db:
        topcv = []
        for identity, path in [('00000000-0000-4000-8000-000000000001', '/first'),
                               ('ffffffff-ffff-4fff-8fff-ffffffffffff', '/last')]:
            source = DataSource(id=identity, name='SYNTHETIC topcv', kind='topcv',
                base_url='https://www.topcv.vn' + path, allowed_paths_json=[path], enabled=True,
                permission_status='allowed', reuse_basis='TEST ONLY', checked_at=e.clock.now(),
                robots_url='https://www.topcv.vn/robots.txt', terms_url='https://www.topcv.vn/terms')
            db.add(source)
            topcv.append(identity)
        others = []
        for kind in ('career', 'upload', 'catalog'):
            source = DataSource(name='SYNTHETIC import only', kind=kind, enabled=True,
                permission_status='allowed', reuse_basis='TEST ONLY', checked_at=e.clock.now())
            db.add(source)
            db.flush()
            others.append(source.id)
        denied = DataSource(name='SYNTHETIC denied', kind='utc', enabled=False, permission_status='denied')
        db.add(denied)
        db.commit()
    original = e.crawl.fetcher.transport
    def transport(url, **kwargs):
        if 'www.topcv.vn' not in url:
            if fail_utc and not url.endswith('/robots.txt'):
                return FetchResult(url, b'denied', {'Content-Type': 'text/html'}, 403)
            return original(url, **kwargs)
        e.calls.append(url)
        if url.endswith('/robots.txt'):
            return FetchResult(url, b'User-agent: *\nAllow: /', {'Content-Type': 'text/plain'})
        posting = {'@type': 'JobPosting', 'title': 'SYNTHETIC engineering job',
            'description': 'SYNTHETIC job description only', 'hiringOrganization': {'name': 'SYNTHETIC'},
            'identifier': {'value': url.rsplit('/', 1)[-1]}, 'url': url, 'validThrough': '2026-12-31'}
        return FetchResult(url, ('<script type="application/ld+json">' + json.dumps(posting) + '</script>').encode(),
                           {'Content-Type': 'text/html'})
    e.crawl.fetcher.transport = transport
    run = manual(e)
    assert_idle(e)
    with e.documents.database.session() as db:
        final = db.get(CrawlRun, run.id)
        items = db.scalars(select(CrawlRunItem).where(CrawlRunItem.run_id == run.id)
                           .order_by(CrawlRunItem.item_index)).all()
        assert [i.item_index for i in items] == list(range(1, len(items) + 1))
        assert final.new_count == (2 if fail_utc else 4) and final.error_count == 0
        assert final.state == ('partial' if fail_utc else 'succeeded')
        outcomes = {o['source_id']: o for o in final.source_outcomes_json}
        assert len(outcomes) == 6 and denied.id not in outcomes
        for identity in others:
            assert outcomes[identity]['status'] == 'skipped' and outcomes[identity]['message'] == 'import-only'
            assert db.get(DataSource, identity).last_success_at is None
        for identity in topcv:
            assert outcomes[identity]['status'] == 'success'
            assert db.get(DataSource, identity).last_success_at == e.clock.now()
        assert outcomes[e.source.id]['status'] == ('error' if fail_utc else 'success')


def test_shutdown_waits_for_current_item_and_rejects_new_runs(runtime, monkeypatch):
    e = runtime
    entered, release, stop_set = Event(), Event(), Event()
    original = e.documents.indexer.index
    def hold(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)
    monkeypatch.setattr(e.documents.indexer, 'index', hold)
    request_stop = e.coordinator.request_stop
    def observed_stop(*args, **kwargs):
        result = request_stop(*args, **kwargs)
        stop_set.set()
        return result
    monkeypatch.setattr(e.coordinator, 'request_stop', observed_stop)
    first = manual(e)
    with ThreadPoolExecutor(max_workers=1) as pool:
        assert entered.wait(3)
        shutdown = pool.submit(e.coordinator.close)
        try:
            assert stop_set.wait(3) and not shutdown.done()
            with pytest.raises(HTTPException) as error:
                e.coordinator.claim('manual')
            assert error.value.status_code == 503
            tick(e, 14)
            assert len(runs(e)) == 1
        finally:
            release.set()
        shutdown.result(timeout=5)
    assert runs(e)[0].state == 'cancelled' and runs(e)[0].new_count == 1
    assert e.coordinator.active_run_id is None


def test_thread_start_failure_finishes_run_and_slot_is_reusable(runtime, monkeypatch):
    e = runtime
    run = e.coordinator.claim('manual')
    class FailedThread:
        def __init__(self, **kwargs):
            pass
        def start(self):
            raise RuntimeError('private startup failure')
    monkeypatch.setattr('app.services.coordinator.Thread', FailedThread)
    with pytest.raises(HTTPException) as error:
        e.coordinator.start(run.id, e.crawl.run)
    assert error.value.status_code == 503
    assert_idle(e)
    assert runs(e)[0].state == 'failed'
    fresh = e.coordinator.claim('manual')
    e.coordinator.execute(fresh.id, lambda _: None)
    assert_idle(e)


def test_source_completion_and_stop_are_serialized(runtime):
    e = runtime
    run = e.coordinator.claim('manual')
    e.coordinator.request_stop(run.id, None)
    e.coordinator.record_source(run.id, e.source.id, 'success')
    e.coordinator.finish(run.id)
    with e.documents.database.session() as db:
        assert db.get(DataSource, e.source.id).last_success_at is None
        assert db.get(CrawlRun, run.id).source_outcomes_json[0]['status'] == 'stopped'


def test_run_logging_is_metadata_only_even_on_failure(runtime, caplog):
    e = runtime
    caplog.set_level(logging.INFO, logger=logger.name)
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(SafeMetadataFormatter())
    logger.addHandler(handler)
    try:
        run = e.coordinator.claim('manual')
        skipped = e.coordinator.claim('scheduled')
        def fail(_):
            raise RuntimeError('PRIVATE_MARKER C:/private?api_key=secret')
        e.coordinator.execute(run.id, fail)
    finally:
        logger.removeHandler(handler)
    records = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [r['event'] for r in records] == ['run_claimed', 'run_skipped_busy', 'run_finished']
    assert records[1]['state'] == 'skipped_busy' and records[-1]['state'] == 'failed'
    assert all(r['run_id'] in {run.id, skipped.id} for r in records)
    assert 'PRIVATE_MARKER' not in output.getvalue() and 'api_key' not in output.getvalue()
