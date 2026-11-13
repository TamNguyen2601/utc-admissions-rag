"""Business job identities are independent of document deduplication."""
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UTCDateTime, UUIDMixin, utc_now


class JobPosting(UUIDMixin, Base):
    __tablename__ = 'job_postings'
    __table_args__ = (
        UniqueConstraint('source_id', 'identity_key'),
        CheckConstraint("observed_status IN ('open','closed','unknown')"),
        CheckConstraint("length(trim(title)) > 0 AND length(trim(employer)) > 0 AND length(trim(description)) > 0"),
        CheckConstraint("(external_id IS NOT NULL AND length(trim(external_id)) > 0 AND identity_key = 'ext:' || external_id) OR (external_id IS NULL AND identity_key LIKE 'url:https://%')"),
        Index('ix_jobs_deadline_group', 'deadline_at', 'career_group'),
    )
    source_id: Mapped[str] = mapped_column(ForeignKey('data_sources.id', ondelete='RESTRICT'), nullable=False)
    identity_key: Mapped[str] = mapped_column(Text, nullable=False)
    origin_id: Mapped[str] = mapped_column(ForeignKey('document_origins.id', ondelete='CASCADE'), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String)
    title: Mapped[str] = mapped_column(String, nullable=False)
    employer: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    posted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    deadline_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    observed_status: Mapped[str] = mapped_column(String, default='unknown', nullable=False)
    career_group: Mapped[str | None] = mapped_column(String)
    classification_reason: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
