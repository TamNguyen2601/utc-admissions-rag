from datetime import datetime
import unicodedata
from typing import Generic, Literal, TypeVar
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


def clean(value: str, maximum: int) -> str:
    value = unicodedata.normalize("NFC", value).strip()
    if not 1 <= len(value) <= maximum or "\x00" in value:
        raise ValueError("Invalid text length")
    return value


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class SourceInput(ClosedModel):
    name: str
    kind: Literal["utc", "topcv", "career", "upload", "catalog"]
    base_url: str | None
    allowed_paths: list[str]
    enabled: bool = Field(strict=True)
    permission_status: Literal["unknown", "allowed", "denied"]
    robots_url: str | None
    terms_url: str | None
    reuse_basis: str | None
    checked_at: AwareDatetime | None
    min_interval_seconds: float = Field(ge=2, allow_inf_nan=False)

    @field_validator("name", "reuse_basis")
    @classmethod
    def text_fields(cls, value):
        return clean(value, 2000) if value is not None else None

    @model_validator(mode="after")
    def permission(self):
        from app.services.sources import validate_source
        validate_source(self)
        return self


class UploadInput(ClosedModel):
    title: str
    source_id: UUID
    source_url: str | None = None
    provenance_note: str | None = None
    year: int | None = Field(default=None, ge=1, le=9999)
    campus: str | None = None
    major_code: str | None = None
    method: str | None = None
    publisher: str | None = None
    published_at: AwareDatetime | None = None

    @field_validator("source_url")
    @classmethod
    def source_url_format(cls, value):
        if value is not None:
            from app.services.sources import canonical_url
            canonical_url(value)
        return value

    @field_validator("title", "campus", "major_code", "method", "publisher")
    @classmethod
    def text_fields(cls, value):
        return clean(value, 500) if value is not None else None

    @field_validator("provenance_note")
    @classmethod
    def note(cls, value):
        return clean(value, 2000) if value is not None else None

    @model_validator(mode="after")
    def provenance(self):
        if not self.source_url and not self.provenance_note:
            raise ValueError("Provenance required")
        return self


class ReasonInput(ClosedModel):
    reason: str

    @field_validator("reason")
    @classmethod
    def reason_text(cls, value):
        return clean(value, 500)


class OriginResponse(ClosedModel):
    id: UUID
    source_id: UUID
    origin_kind: Literal["web", "upload"]
    canonical_url: str
    original_url: str
    provenance_note: str | None
    publisher: str | None
    published_at: datetime | None
    retrieved_at: datetime
    active: bool


class DocumentMetadata(ClosedModel):
    id: UUID
    title: str
    provenance_note: str | None
    year: int | None
    campus: str | None
    major_code: str | None
    method: str | None
    state: Literal["pending", "ready", "quarantined", "error"]
    enabled: bool
    content_hash: str | None
    index_profile: dict | None
    quality_reason: str | None
    last_update_error: str | None
    created_at: datetime
    updated_at: datetime
    last_checked_at: datetime | None
    origins: list[OriginResponse]


class DocumentDetail(DocumentMetadata):
    content_text: str | None


class PublicOrigin(ClosedModel):
    url: str
    source_name: str


class SourceExcerpt(ClosedModel):
    chunk_id: UUID
    page: int | None = Field(ge=1)
    section: str | None
    text: str


class PublicSource(ClosedModel):
    id: UUID
    title: str
    origins: list[PublicOrigin]
    excerpts: list[SourceExcerpt]
    available: Literal[True]


class SourceResponse(SourceInput):
    id: UUID
    retry_not_before: datetime | None
    last_success_at: datetime | None


T = TypeVar("T")


class PageResponse(ClosedModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
