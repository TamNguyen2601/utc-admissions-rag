from datetime import datetime

from sqlalchemy import CheckConstraint, DDL, ForeignKey, JSON, String, Text, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, UTCDateTime, UUIDMixin


class CrawlRun(UUIDMixin, CreatedAtMixin, Base):
    __tablename__ = "crawl_runs"
    __table_args__ = (
        CheckConstraint("trigger IN ('scheduled','manual','upload','job_import')"),
        CheckConstraint("state IN ('running','stop_requested','cancelled','succeeded','partial','failed','interrupted','skipped_busy')"),
        CheckConstraint("new_count >= 0 AND updated_count >= 0 AND skipped_count >= 0 AND error_count >= 0"),
        CheckConstraint("(state = 'skipped_busy' AND trigger = 'scheduled' AND started_at IS NULL AND ended_at IS NOT NULL AND ended_at = created_at AND new_count = 0 AND updated_count = 0 AND skipped_count = 0 AND error_count = 0 AND source_outcomes_json = '[]') OR (state != 'skipped_busy' AND started_at IS NOT NULL)"),
        CheckConstraint("(state IN ('running','stop_requested') AND ended_at IS NULL) OR (state NOT IN ('running','stop_requested') AND ended_at IS NOT NULL)"),
    )
    source_id: Mapped[str | None] = mapped_column(ForeignKey("data_sources.id", ondelete="SET NULL"))
    trigger: Mapped[str] = mapped_column(String, nullable=False)
    triggered_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    state: Mapped[str] = mapped_column(String, default="running", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    stop_requested_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    stop_requested_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    new_count: Mapped[int] = mapped_column(default=0, nullable=False)
    updated_count: Mapped[int] = mapped_column(default=0, nullable=False)
    skipped_count: Mapped[int] = mapped_column(default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(default=0, nullable=False)
    source_outcomes_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)


class CrawlRunItem(UUIDMixin, Base):
    __tablename__ = "crawl_run_items"
    __table_args__ = (
        UniqueConstraint("run_id", "item_index"),
        CheckConstraint("item_index >= 1"),
        CheckConstraint("outcome IN ('new','updated','skipped','error')"),
    )
    run_id: Mapped[str] = mapped_column(ForeignKey("crawl_runs.id", ondelete="CASCADE"), nullable=False)
    item_index: Mapped[int] = mapped_column(nullable=False)
    source_id: Mapped[str | None] = mapped_column(ForeignKey("data_sources.id", ondelete="SET NULL"))
    canonical_url: Mapped[str | None] = mapped_column(Text)
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    outcome: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


# Cross-table invariant: a skipped scheduled run never has items, including direct SQL.
event.listen(CrawlRunItem.__table__, "after_create", DDL("""
CREATE TRIGGER skipped_busy_no_items BEFORE INSERT ON crawl_run_items
WHEN (SELECT state FROM crawl_runs WHERE id = NEW.run_id) = 'skipped_busy'
BEGIN SELECT RAISE(ABORT, 'skipped_busy has no items'); END
"""))
event.listen(CrawlRunItem.__table__, "after_create", DDL("""
CREATE TRIGGER skipped_busy_no_item_move BEFORE UPDATE OF run_id ON crawl_run_items
WHEN (SELECT state FROM crawl_runs WHERE id = NEW.run_id) = 'skipped_busy'
BEGIN SELECT RAISE(ABORT, 'skipped_busy has no items'); END
"""))
event.listen(CrawlRun.__table__, "after_create", DDL("""
CREATE TRIGGER skipped_busy_empty BEFORE UPDATE OF state ON crawl_runs
WHEN NEW.state = 'skipped_busy' AND EXISTS (SELECT 1 FROM crawl_run_items WHERE run_id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'skipped_busy has no items'); END
"""))
