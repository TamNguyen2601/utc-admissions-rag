"""Admin run contract, including scheduled skipped_busy terminal records."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

RunState = Literal['running', 'stop_requested', 'cancelled', 'succeeded', 'partial',
                   'failed', 'interrupted', 'skipped_busy']


class RunInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_id: UUID | None = None


class RunCounts(BaseModel):
    new: int = Field(ge=0)
    updated: int = Field(ge=0)
    skipped: int = Field(ge=0)
    error: int = Field(ge=0)


class SourceOutcome(BaseModel):
    source_id: UUID | None
    status: Literal['success', 'error', 'stopped', 'skipped']
    message: str | None


class RunResponse(BaseModel):
    id: UUID
    source_id: UUID | None
    trigger: Literal['manual', 'scheduled', 'upload', 'job_import']
    state: RunState
    created_at: datetime
    triggered_by: UUID | None
    started_at: datetime | None
    ended_at: datetime | None
    stop_requested_at: datetime | None
    stop_requested_by: UUID | None
    counts: RunCounts
    source_outcomes: list[SourceOutcome]


class RunItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    item_index: int = Field(ge=1)
    source_id: UUID | None
    canonical_url: str | None
    document_id: UUID | None
    outcome: Literal['new', 'updated', 'skipped', 'error']
    reason: str | None
    started_at: datetime
    ended_at: datetime


def run_response(run):
    fields = {key: getattr(run, key) for key in RunResponse.model_fields
              if key not in {'counts', 'source_outcomes'}}
    return RunResponse(**fields,
        counts=RunCounts(new=run.new_count, updated=run.updated_count,
                         skipped=run.skipped_count, error=run.error_count),
        source_outcomes=run.source_outcomes_json)
