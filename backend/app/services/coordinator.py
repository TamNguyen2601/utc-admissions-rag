"""One local ingestion slot. No pipeline work while holding the state mutex."""
from collections.abc import Callable
from threading import Event, Lock, Thread

from fastapi import HTTPException

from app.db.base import utc_now
from app.core.logging import logger
from app.models.crawl import CrawlRun
from app.models.knowledge import DataSource
from sqlalchemy import select


class RunInProgress(HTTPException):
    def __init__(self):
        super().__init__(409)


class Coordinator:
    def __init__(self, database, *, now=utc_now):
        self.database = database
        self.now = now
        self._mutex = Lock()
        self.active_run_id: str | None = None
        self._executing: str | None = None
        self._closing = False
        self._idle = Event()
        self._idle.set()

    @staticmethod
    def _log(run, event):
        logger.info('run_changed', extra={'run_event': event, 'run_id': run.id,
            'trigger': run.trigger, 'run_state': run.state,
            'counts': dict(new=run.new_count, updated=run.updated_count,
                           skipped=run.skipped_count, error=run.error_count)})

    def recover_interrupted(self):
        # Startup only, before accepting requests or starting the scheduler.
        with self._mutex, self.database.session() as db:
            interrupted = db.scalars(select(CrawlRun).where(CrawlRun.state.in_(['running', 'stop_requested']))).all()
            for run in interrupted:
                run.state, run.ended_at = 'interrupted', self.now()
            db.commit()
            for run in interrupted:
                self._log(run, 'interrupted')

    def claim(self, trigger: str, source_id: str | None = None, actor_id: str | None = None) -> CrawlRun:
        with self._mutex:
            if self._closing:
                raise HTTPException(503)
            busy = self.active_run_id is not None
            if busy and trigger != "scheduled":
                raise RunInProgress()
            now = self.now()
            run = CrawlRun(source_id=source_id, trigger=trigger, triggered_by=actor_id,
                state="skipped_busy" if busy else "running", created_at=now,
                started_at=None if busy else now, ended_at=now if busy else None)
            with self.database.session() as db:
                db.add(run); db.commit()
            if not busy:
                self.active_run_id = run.id
                self._idle.clear()
            self._log(run, 'skipped_busy' if busy else 'claimed')
            return run

    def start(self, run_id: str, pipeline: Callable[[str], None]):
        """Dispatch only a claimed slot; no executor queue or deferred run."""
        try:
            Thread(target=self.execute, args=(run_id, pipeline), name='ingestion', daemon=False).start()
        except Exception:
            self.finish(run_id, failed=True)
            raise HTTPException(503) from None

    def wait_idle(self, timeout=None):
        return self._idle.wait(timeout)

    def close(self):
        with self._mutex:
            self._closing = True
            active = self.active_run_id
        if active:
            self.request_stop(active, None)
        # Never wait while holding the coordinator or publish mutex.
        self.wait_idle()

    def should_stop(self, run_id: str) -> bool:
        with self.database.session() as db:
            run = db.get(CrawlRun, run_id)
            return run is None or run.state == "stop_requested"

    def request_stop(self, run_id: str, actor_id: str | None):
        with self._mutex, self.database.session() as db:
            run = db.get(CrawlRun, run_id)
            if run is None:
                raise HTTPException(404)
            if run.state == "running" and self.active_run_id == run_id:
                run.state = "stop_requested"
                run.stop_requested_at = self.now()
                run.stop_requested_by = actor_id
                db.commit()
                self._log(run, 'stop_requested')
            return run

    def record_source(self, run_id, source_id, status, message=None):
        # Serialize source completion with stop: a stop cannot race a success timestamp.
        with self._mutex, self.database.session() as db:
            run = db.get(CrawlRun, run_id)
            if status == 'success' and run.state == 'stop_requested':
                status, message = 'stopped', 'STOP_REQUESTED'
            run.source_outcomes_json = [*run.source_outcomes_json,
                dict(source_id=source_id, status=status, message=message)]
            source = db.get(DataSource, source_id)
            if status == 'success' and source is not None:
                source.last_success_at = self.now()
            db.commit()

    def finish(self, run_id: str, *, failed: bool = False):
        with self._mutex:
            try:
                with self.database.session() as db:
                    run = db.get(CrawlRun, run_id)
                    if run is not None and run.state in {"running", "stop_requested"}:
                        if run.state == "stop_requested":
                            run.state = "cancelled"
                        elif failed:
                            run.state = "partial" if run.new_count + run.updated_count + run.skipped_count else "failed"
                            run.source_outcomes_json = [*run.source_outcomes_json,
                                dict(source_id=run.source_id, status='error', message='PIPELINE_FAILED')]
                        elif run.error_count or any(x.get("status") == "error" for x in run.source_outcomes_json):
                            run.state = "partial" if run.new_count + run.updated_count + run.skipped_count else "failed"
                        else:
                            run.state = "succeeded"
                        run.ended_at = self.now()
                        db.commit()
                        self._log(run, 'finished')
            finally:
                if self.active_run_id == run_id:
                    self.active_run_id = None
                    self._executing = None
                    self._idle.set()

    def execute(self, run_id: str, pipeline: Callable[[str], None]):
        # claim() has already returned and released the mutex before dispatch.
        with self._mutex:
            if self.active_run_id != run_id or self._executing == run_id:
                # In particular, skipped_busy is terminal and can never execute.
                return
            self._executing = run_id
        failed = False
        try:
            pipeline(run_id)
        except Exception:
            # Sanitized run state only, never raw upstream exception/paths.
            failed = True
        finally:
            self.finish(run_id, failed=failed)
