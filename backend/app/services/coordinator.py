"""One local ingestion slot. No pipeline work while holding the state mutex."""
from collections.abc import Callable
from threading import Lock

from fastapi import HTTPException

from app.db.base import utc_now
from app.models.crawl import CrawlRun


class RunInProgress(HTTPException):
    def __init__(self):
        super().__init__(409)


class Coordinator:
    def __init__(self, database):
        self.database = database
        self._mutex = Lock()
        self.active_run_id: str | None = None

    def claim(self, trigger: str, source_id: str | None = None, actor_id: str | None = None) -> CrawlRun:
        with self._mutex:
            busy = self.active_run_id is not None
            if busy and trigger != "scheduled":
                raise RunInProgress()
            now = utc_now()
            run = CrawlRun(source_id=source_id, trigger=trigger, triggered_by=actor_id,
                state="skipped_busy" if busy else "running", created_at=now,
                started_at=None if busy else now, ended_at=now if busy else None)
            with self.database.session() as db:
                db.add(run); db.commit()
            if not busy:
                self.active_run_id = run.id
            return run

    def should_stop(self, run_id: str) -> bool:
        with self.database.session() as db:
            run = db.get(CrawlRun, run_id)
            return run is None or run.state == "stop_requested"

    def request_stop(self, run_id: str, actor_id: str | None):
        with self._mutex, self.database.session() as db:
            run = db.get(CrawlRun, run_id)
            if run is None:
                raise HTTPException(404)
            if run.state == "running":
                run.state = "stop_requested"
                run.stop_requested_at = utc_now()
                run.stop_requested_by = actor_id
                db.commit()
            return run

    def finish(self, run_id: str, *, failed: bool = False):
        with self._mutex:
            try:
                with self.database.session() as db:
                    run = db.get(CrawlRun, run_id)
                    if run is not None and run.state in {"running", "stop_requested"}:
                        if run.state == "stop_requested":
                            run.state = "cancelled"
                        elif failed:
                            run.state = "failed"
                        elif run.error_count or any(x.get("status") == "error" for x in run.source_outcomes_json):
                            run.state = "partial" if run.new_count + run.updated_count + run.skipped_count else "failed"
                        else:
                            run.state = "succeeded"
                        run.ended_at = utc_now()
                        db.commit()
            finally:
                if self.active_run_id == run_id:
                    self.active_run_id = None

    def execute(self, run_id: str, pipeline: Callable[[str], None]):
        # claim() has already returned and released the mutex before dispatch.
        with self._mutex:
            if self.active_run_id != run_id:
                # In particular, skipped_busy is terminal and can never execute.
                return
        failed = False
        try:
            pipeline(run_id)
        except Exception:
            # Sanitized run state only, never raw upstream exception/paths.
            failed = True
        finally:
            self.finish(run_id, failed=failed)
