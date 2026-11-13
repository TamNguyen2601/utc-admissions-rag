"""One in-process cron; the ingestion slot, never the scheduler, owns crawl work."""
from zoneinfo import ZoneInfo

from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import HTTPException

from app.core.logging import logger

TIMEZONE = ZoneInfo('Asia/Ho_Chi_Minh')
JOB_ID = 'daily-crawl'


class CrawlScheduler:
    def __init__(self, coordinator, crawl, *, scheduler=None):
        self.coordinator, self.crawl = coordinator, crawl
        self.scheduler = scheduler or AsyncIOScheduler(
            timezone=TIMEZONE, jobstores={'default': MemoryJobStore()})

    def start(self):
        self.scheduler.add_job(self.scheduled, CronTrigger(hour=0, minute=0, second=0, timezone=TIMEZONE),
            id=JOB_ID, replace_existing=True, max_instances=1, coalesce=True, misfire_grace_time=60)
        # MemoryJobStore computes the next future midnight on every startup; no catch-up.
        self.scheduler.start()

    async def scheduled(self):
        try:
            run = self.coordinator.claim('scheduled')
            if run.state != 'skipped_busy':
                self.coordinator.start(run.id, self.crawl.run)
        except HTTPException:
            # Shutdown/start failure is already reflected in the claimed run, if any.
            logger.info('scheduler_unavailable')
        except Exception:
            # Never send raw DB/network exceptions to APScheduler's traceback logger.
            logger.info('scheduler_unavailable')

    def shutdown(self):
        if self.scheduler.running:
            self.scheduler.pause()
            self.scheduler.shutdown(wait=False)
