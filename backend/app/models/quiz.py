"""Source-bound majors and ten active, explicitly directed rubric questions."""
from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, JSON, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, validates
from pydantic import TypeAdapter
from uuid import UUID

from app.db.base import Base, UUIDMixin
from app.schemas.quiz import CareerGroup, ScoringRule


class Major(UUIDMixin, Base):
    __tablename__ = 'majors'
    __table_args__ = (
        UniqueConstraint('code', 'campus'),
        CheckConstraint('active IN (0,1)'),
        CheckConstraint('source_page IS NULL OR source_page >= 1'),
        CheckConstraint('length(source_content_hash) = 64'),
        CheckConstraint('length(trim(code)) > 0 AND length(trim(name)) > 0 AND length(trim(campus)) > 0 AND length(trim(description)) > 0'),
        CheckConstraint("json_valid(career_groups_json) AND json_type(career_groups_json) = 'array'"),
    )
    code: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    campus: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    source_document_id: Mapped[str] = mapped_column(ForeignKey('documents.id', ondelete='CASCADE'), nullable=False)
    source_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_page: Mapped[int | None]
    career_groups_json: Mapped[list] = mapped_column(JSON, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    @validates('career_groups_json')
    def validate_groups(self, key, value):
        return [g.model_dump() for g in TypeAdapter(list[CareerGroup]).validate_python(value)]


class QuizQuestion(UUIDMixin, Base):
    __tablename__ = 'quiz_questions'
    __table_args__ = (
        CheckConstraint('position BETWEEN 1 AND 10'),
        CheckConstraint('active IN (0,1)'),
        CheckConstraint('length(trim(text)) > 0'),
        CheckConstraint("json_valid(scoring_json) AND json_type(scoring_json) = 'object'"),
        Index('uq_active_question_position', 'position', unique=True, sqlite_where=text('active = 1')),
    )
    position: Mapped[int]
    text: Mapped[str] = mapped_column(Text, nullable=False)
    scoring_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    @validates('scoring_json')
    def validate_scoring(self, key, value):
        parsed = TypeAdapter(dict[UUID, ScoringRule]).validate_python(value)
        return {str(mid): rule.model_dump() for mid, rule in parsed.items()}
