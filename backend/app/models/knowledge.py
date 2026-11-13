"""Knowledge checkpoint B1; no chunks or vector storage until T025."""
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, JSON, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, UTCDateTime, UUIDMixin, utc_now


class DataSource(UUIDMixin, Base):
    __tablename__ = "data_sources"
    __table_args__ = (
        CheckConstraint("kind IN ('utc','topcv','career','upload','catalog')"),
        CheckConstraint("permission_status IN ('unknown','allowed','denied')"),
        CheckConstraint("enabled IN (0,1)"),
        CheckConstraint("min_interval_seconds >= 2"),
        CheckConstraint("enabled = 0 OR permission_status = 'allowed'"),
        CheckConstraint("permission_status != 'allowed' OR (checked_at IS NOT NULL AND reuse_basis IS NOT NULL AND length(trim(reuse_basis)) > 0)"),
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    base_url: Mapped[str | None] = mapped_column(String)
    allowed_paths_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    permission_status: Mapped[str] = mapped_column(String, default="unknown", nullable=False)
    robots_url: Mapped[str | None] = mapped_column(String)
    terms_url: Mapped[str | None] = mapped_column(String)
    reuse_basis: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    min_interval_seconds: Mapped[float] = mapped_column(default=2.0, nullable=False)
    retry_not_before: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class Document(UUIDMixin, CreatedAtMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint("state IN ('pending','ready','quarantined','error')"),
        CheckConstraint("enabled IN (0,1)"),
        CheckConstraint("state != 'quarantined' OR (quality_reason IS NOT NULL AND length(trim(quality_reason)) > 0)"),
        Index("uq_document_content_context", "content_hash", "context_key", unique=True,
              sqlite_where=text("content_hash IS NOT NULL")),
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    provenance_note: Mapped[str | None] = mapped_column(Text)
    content_text: Mapped[str | None] = mapped_column(Text)
    raw_hash: Mapped[str | None] = mapped_column(String(64))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    context_key: Mapped[str] = mapped_column(Text, nullable=False)
    year: Mapped[int | None]
    campus: Mapped[str | None] = mapped_column(String)
    major_code: Mapped[str | None] = mapped_column(String)
    method: Mapped[str | None] = mapped_column(String)
    index_profile: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))
    state: Mapped[str] = mapped_column(String, default="pending", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_update_error: Mapped[str | None] = mapped_column(Text)
    quality_reason: Mapped[str | None] = mapped_column(Text)


class DocumentOrigin(UUIDMixin, Base):
    __tablename__ = "document_origins"
    __table_args__ = (
        CheckConstraint("origin_kind IN ('web','upload')"),
        CheckConstraint("active IN (0,1)"),
        CheckConstraint("provenance_note IS NULL OR length(trim(provenance_note)) BETWEEN 1 AND 2000"),
        CheckConstraint("origin_kind != 'upload' OR canonical_url LIKE 'https://%' OR provenance_note IS NOT NULL"),
        Index("uq_web_origin_url", "source_id", "canonical_url", unique=True,
              sqlite_where=text("origin_kind = 'web'")),
        Index("ix_origin_source_url", "source_id", "canonical_url"),
    )
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False)
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id", ondelete="RESTRICT"), nullable=False)
    origin_kind: Mapped[str] = mapped_column(String, nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    original_url: Mapped[str] = mapped_column(Text, nullable=False)
    provenance_note: Mapped[str | None] = mapped_column(Text)
    publisher: Mapped[str | None] = mapped_column(String)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    retrieved_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
