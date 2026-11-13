"""Private history; citations are snapshots with no knowledge-table foreign keys."""
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, UTCDateTime, UUIDMixin, utc_now


class Conversation(UUIDMixin, CreatedAtMixin, Base):
    __tablename__ = 'conversations'
    __table_args__ = (
        CheckConstraint('length(trim(title)) BETWEEN 1 AND 100', name='ck_conversation_title'),
        CheckConstraint('next_seq >= 1 AND next_seq % 2 = 1', name='ck_conversation_next_seq'),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(100), default='Hội thoại mới', nullable=False)
    next_seq: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)


class Message(UUIDMixin, CreatedAtMixin, Base):
    __tablename__ = 'messages'
    __table_args__ = (
        UniqueConstraint('conversation_id', 'seq', name='uq_message_sequence'),
        UniqueConstraint('turn_id', 'sender', name='uq_message_turn_sender'),
        CheckConstraint('seq >= 1', name='ck_message_sequence'),
        CheckConstraint("sender IN ('user', 'assistant')", name='ck_message_sender'),
        CheckConstraint("(sender = 'user' AND reply_status IS NULL) OR "
                        "(sender = 'assistant' AND reply_status IS NOT NULL AND reply_status IN "
                        "('answered', 'social', 'out_of_scope', 'needs_clarification', "
                        "'insufficient_evidence', 'data_missing', 'conflicting_sources'))",
                        name='ck_message_reply_status'),
    )

    conversation_id: Mapped[str] = mapped_column(
        ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    turn_id: Mapped[str] = mapped_column(String(36), nullable=False)
    sender: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(String, nullable=False)
    reply_status: Mapped[str | None] = mapped_column(String, nullable=True)
    citations_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
