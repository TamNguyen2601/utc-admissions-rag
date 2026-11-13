"""Synthetic single-process contention with Events; no sleeps/network."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from sqlalchemy import func, select

from app.db.session import Database
from app.models.crawl import CrawlRun
from app.services.coordinator import Coordinator, RunInProgress
from tests.ingestion_support import ingestion


def test_busy_does_not_hold_mutex_or_queue_work(settings):
    db = Database(settings); db.initialize()
    coordinator = Coordinator(db)
    entered, release = Event(), Event()
    run = coordinator.claim("manual")
    def pipeline(_run_id):
        entered.set()
        assert release.wait(5)
    with ThreadPoolExecutor() as pool:
        worker = pool.submit(coordinator.execute, run.id, pipeline)
        assert entered.wait(5)
        try:
            with pytest.raises(RunInProgress): coordinator.claim("upload")
            skipped = pool.submit(coordinator.claim, "scheduled").result(timeout=3)
            assert skipped.state == "skipped_busy" and skipped.started_at is None
            assert skipped.ended_at == skipped.created_at
            assert coordinator.active_run_id == run.id
            with db.session() as session:
                assert session.scalar(select(func.count()).select_from(CrawlRun)) == 2
        finally:
            release.set()
        worker.result(timeout=5)
    assert coordinator.active_run_id is None
    coordinator.execute(skipped.id, lambda _: pytest.fail("A skipped run must never execute"))
    assert Coordinator(db).active_run_id is None
    fresh = coordinator.claim("manual")
    def fail(_): raise RuntimeError("secret error must not escape")
    coordinator.execute(fresh.id, fail)
    assert coordinator.active_run_id is None
    with db.session() as session:
        assert session.get(CrawlRun, fresh.id).state == "failed"
    db.dispose()


def test_source_failure_terminal_state(settings):
    db = Database(settings); db.initialize()
    coordinator = Coordinator(db)
    run = coordinator.claim("manual")
    def pipeline(run_id):
        with db.session() as session:
            current = session.get(CrawlRun, run_id)
            current.source_outcomes_json = [{"source_id": None, "status": "error", "message": "SYNTHETIC"}]
            session.commit()
    coordinator.execute(run.id, pipeline)
    with db.session() as session:
        assert session.get(CrawlRun, run.id).state == "failed"
    assert coordinator.active_run_id is None
    db.dispose()


def test_stop_clears_slot(settings):
    db = Database(settings); db.initialize()
    coordinator = Coordinator(db)
    run = coordinator.claim("upload")
    coordinator.request_stop(run.id, None)
    assert coordinator.should_stop(run.id)
    coordinator.execute(run.id, lambda _: None)
    assert coordinator.active_run_id is None
    with db.session() as session:
        assert session.get(CrawlRun, run.id).state == "cancelled"
    db.dispose()


def test_b2_extraction_does_not_hold_publish_or_coordinator_lock(ingestion):
    from types import SimpleNamespace
    source, documents, coordinator = ingestion
    entered, release = Event(), Event()
    original = documents.extractor.extract
    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)
    documents.extractor.extract = blocked
    run = coordinator.claim("manual")
    payload = SimpleNamespace(title="SYNTHETIC", year=None, campus=None, major_code=None, method=None)
    def pipeline(_):
        result = documents.process_web(source.id, "https://tuyensinh.utc.edu.vn/a",
            b"SYNTHETIC blocked extraction description", "text/plain", payload)
        assert result.outcome == "new"
    with ThreadPoolExecutor() as pool:
        worker = pool.submit(coordinator.execute, run.id, pipeline)
        assert entered.wait(5)
        try:
            assert documents.publish_lock.acquire(blocking=False)
            documents.publish_lock.release()
            skipped = pool.submit(coordinator.claim, "scheduled").result(timeout=3)
            assert skipped.state == "skipped_busy"
            with pytest.raises(RunInProgress): coordinator.claim("manual")
        finally:
            release.set()
        worker.result(timeout=5)
    assert coordinator.active_run_id is None
