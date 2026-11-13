"""Closed guest chat / Reply contract. History is implemented separately (T035+)."""
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.schemas.document import ClosedModel, clean


class Context(ClosedModel):
    year: int | None = Field(default=None, strict=True, ge=1, le=9999)
    campus: str | None = None
    major_code: str | None = None
    method: str | None = None

    @field_validator('campus', 'major_code', 'method')
    @classmethod
    def context_text(cls, value):
        return clean(value, 500) if value is not None else None


class Turn(ClosedModel):
    sender: Literal['user', 'assistant']
    text: str

    @field_validator('text')
    @classmethod
    def text_length(cls, value):
        return clean(value, 4000)


class GuestChatInput(ClosedModel):
    message: str
    context: Context = Field(default_factory=Context)
    turns: list[Turn] = Field(default_factory=list, max_length=10)

    @field_validator('message')
    @classmethod
    def message_length(cls, value):
        return clean(value, 4000)

    @model_validator(mode='after')
    def turn_budget(self):
        if sum(len(turn.text) for turn in self.turns) > 16000:
            raise ValueError('Turn context exceeds budget')
        return self


class Citation(ClosedModel):
    document_id: UUID
    chunk_id: UUID
    content_hash: str
    title: str
    url: str
    source_name: str
    year: int | None
    campus: str | None
    page: int | None
    section: str | None
    available: bool


class Reply(ClosedModel):
    status: Literal['answered', 'social', 'out_of_scope', 'needs_clarification',
                    'insufficient_evidence', 'data_missing', 'conflicting_sources']
    text: str
    citations: list[Citation] = Field(default_factory=list)
    context: Context
    missing_fields: list[str] = Field(default_factory=list)
    request_id: str


class GeminiOutput(ClosedModel):
    answer: str = Field(strict=True, min_length=1)
    evidence_ids: list[str] = Field(min_length=1, max_length=5)

    @field_validator('answer')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Empty answer')
        return value.strip()

    @field_validator('evidence_ids')
    @classmethod
    def unique_ids(cls, values):
        if len(values) != len(set(values)):
            raise ValueError('Duplicate evidence IDs')
        return values
