"""Closed job import snapshots and public DTOs."""
from datetime import date, datetime, time, timezone
import re
import unicodedata
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, field_validator, model_validator

from app.schemas.document import ClosedModel


class JobRow(ClosedModel):
    """external_id asserts a stable ID issued by the publisher; omit if not reliable."""
    title: str
    employer: str
    description: str
    source_url: str
    collected_at: AwareDatetime
    source_id: UUID | None = None
    external_id: str | None = None
    posted_at: AwareDatetime | None = None
    deadline_at: AwareDatetime | None = None
    observed_status: Literal['open', 'closed', 'unknown'] = 'unknown'
    career_group: str | None = None
    classification_reason: str | None = None

    @model_validator(mode='before')
    @classmethod
    def strip_strings(cls, values):
        if isinstance(values, dict):
            return {key: unicodedata.normalize('NFC', value).strip() if isinstance(value, str) else value
                    for key, value in values.items()}
        return values

    @field_validator('title', 'employer', 'description', 'source_url', 'external_id',
                     'career_group', 'classification_reason', mode='before')
    @classmethod
    def normalize_text(cls, value):
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError('Text required')
        value = ' '.join(unicodedata.normalize('NFC', value).split())
        if not value or '\x00' in value:
            raise ValueError('Nonempty text required')
        return value

    @field_validator('deadline_at', mode='before')
    @classmethod
    def date_deadline(cls, value):
        if isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            value = datetime.combine(date.fromisoformat(value), time.max, ZoneInfo('Asia/Ho_Chi_Minh'))
        return value

    @field_validator('collected_at', 'posted_at', 'deadline_at', mode='before')
    @classmethod
    def timestamps(cls, value, info):
        # Numeric epoch values and timezone-free timestamps are not import timestamps.
        if value is not None and not isinstance(value, (str, datetime)):
            raise ValueError('RFC3339 timestamp required')
        if isinstance(value, str):
            date_only = info.field_name == 'deadline_at' and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value)
            if not date_only and not re.fullmatch(
                    r'\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})', value):
                raise ValueError('RFC3339 timestamp required')
        return value

    @field_validator('collected_at', 'posted_at', 'deadline_at')
    @classmethod
    def utc(cls, value):
        return value.astimezone(timezone.utc) if value is not None else None


class JobResponse(ClosedModel):
    id: UUID
    source_id: UUID
    identity_key: str
    document_id: UUID
    origin_id: UUID
    title: str
    employer: str
    description: str
    source_url: str
    source_name: str
    collected_at: datetime
    updated_at: datetime
    posted_at: datetime | None
    deadline_at: datetime | None
    status: Literal['open', 'expired', 'unverified']
    career_group: str | None
    classification_reason: str | None


class JobSource(ClosedModel):
    id: UUID
    name: str


class JobsResponse(ClosedModel):
    status: Literal['ready', 'data_missing']
    items: list[JobResponse]
    total: int
    page: int
    page_size: int
    observed_open_count: int | None
    as_of: datetime
    sources: list[JobSource]
    scope_note: str


class RunAccepted(ClosedModel):
    run_id: UUID
    state: Literal['running']
