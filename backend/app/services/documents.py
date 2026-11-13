"""Document administration and incremental extraction with an injectable index boundary.

Real extraction is injected separately. Indexer contract: profile: dict,
extract(bytes, media_type) -> text; index(text, metadata) -> None; usable(document)
-> bool. B2 uses fake indexing; T025–T029 supply chunks, embedding and retrieval.
"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import unicodedata
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import exists, or_, select

from app.db.base import utc_now
from app.models.crawl import CrawlRun, CrawlRunItem
from app.models.knowledge import DataSource, Document, DocumentOrigin
from app.services.sources import require_usable, validate_source_url
from app.services.extraction import ExtractionError

MAX_UPLOAD = 20 * 1024 * 1024
MEDIA = {"application/pdf": ".pdf", "text/plain": ".txt", "image/png": ".png", "image/jpeg": ".jpg"}


def validate_file(data: bytes, media_type: str, filename: str | None):
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413)
    suffix = Path(filename or "").suffix.lower()
    allowed_suffixes = {".pdf": "application/pdf", ".txt": "text/plain", ".png": "image/png",
                        ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
    if not data or allowed_suffixes.get(suffix) != media_type:
        raise HTTPException(415)
    valid = False
    if media_type == "text/plain":
        try:
            decoded = data.decode("utf-8-sig")
            valid = (bool(decoded.strip()) and not data.startswith((b"%PDF-", b"\x89PNG", b"\xff\xd8"))
                     and not any(ord(c) < 32 and c not in "\n\r\t" for c in decoded))
        except UnicodeDecodeError:
            pass
    elif media_type == "application/pdf":
        valid = data.startswith(b"%PDF-") and b"%%EOF" in data[-1024:]
    elif media_type == "image/png":
        valid = data.startswith(b"\x89PNG\r\n\x1a\n")
    elif media_type == "image/jpeg":
        valid = data.startswith(b"\xff\xd8\xff") and data.endswith(b"\xff\xd9")
    if not valid:
        raise HTTPException(415)


def normalized_text(value: str) -> str:
    value = unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(" ".join(line.split()) for line in value.split("\n")).strip()


def context_key(metadata) -> str:
    # Explicit null distinguishes unknown from every supplied value.
    return json.dumps({"kind": "document", **{key: getattr(metadata, key) for key in
                      ("year", "campus", "major_code", "method")}}, sort_keys=True, ensure_ascii=False)


def metadata(db, document, *, detail=False):
    fields = ("id", "title", "provenance_note", "year", "campus", "major_code", "method", "state",
              "enabled", "content_hash", "index_profile", "quality_reason", "last_update_error",
              "created_at", "updated_at", "last_checked_at")
    result = {key: getattr(document, key) for key in fields}
    origins = db.scalars(select(DocumentOrigin).where(DocumentOrigin.document_id == document.id)
                         .order_by(DocumentOrigin.retrieved_at, DocumentOrigin.id)).all()
    origin_fields = ("id", "source_id", "origin_kind", "canonical_url", "original_url", "provenance_note",
                     "publisher", "published_at", "retrieved_at", "active")
    result["origins"] = [{key: getattr(origin, key) for key in origin_fields} for origin in origins]
    if detail:
        result["content_text"] = document.content_text
    return result


def get_document(db, identity: str):
    document = db.get(Document, identity)
    if document is None:
        raise HTTPException(404)
    return document


def document_query(q=None, state=None, enabled=None):
    query = select(Document)
    if q:
        # SQLAlchemy contains(autoescape) treats search input literally.
        origin_match = exists(select(DocumentOrigin.id).where(DocumentOrigin.document_id == Document.id,
                                     DocumentOrigin.canonical_url.contains(q, autoescape=True)))
        query = query.where(or_(Document.title.contains(q, autoescape=True), origin_match))
    if state is not None: query = query.where(Document.state == state)
    if enabled is not None: query = query.where(Document.enabled == enabled)
    return query.order_by(Document.created_at.desc(), Document.id)


def file_path(upload_dir: Path, origin_id: str, media_type: str) -> Path:
    # UUID assigned by backend; original client filename never enters a local path.
    from uuid import UUID
    return upload_dir / (str(UUID(origin_id)) + MEDIA[media_type])


@dataclass(frozen=True)
class IngestionOutcome:
    outcome: str
    document_id: str | None
    reason: str | None = None


class DocumentService:
    def __init__(self, database, upload_dir, publish_lock, indexer=None, *, extractor=None):
        self.database, self.upload_dir = database, upload_dir
        self.publish_lock, self.indexer = publish_lock, indexer
        self.extractor = extractor

    def accept_upload(self, payload, data: bytes, media_type: str):
        origin_id = str(uuid4())
        path = file_path(self.upload_dir, origin_id, media_type)
        try:
            raw_hash = hashlib.sha256(data).hexdigest()
            self.upload_dir.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            with self.publish_lock, self.database.session() as db:
                source = db.get(DataSource, str(payload.source_id))
                require_usable(source)
                url = validate_source_url(source, payload.source_url) if payload.source_url else f"urn:upload:{origin_id}"
                document = Document(title=payload.title, provenance_note=payload.provenance_note,
                    context_key=context_key(payload), raw_hash=raw_hash,
                    **{key: getattr(payload, key) for key in ("year", "campus", "major_code", "method")})
                db.add(document)
                db.flush()
                origin = DocumentOrigin(id=origin_id, document_id=document.id, source_id=source.id,
                    origin_kind="upload", canonical_url=url, original_url=payload.source_url or url,
                    provenance_note=payload.provenance_note, publisher=payload.publisher,
                    published_at=payload.published_at)
                db.add(origin)
                db.commit()
                return origin_id, document.id
        except Exception:
            path.unlink(missing_ok=True)
            raise

    def process_upload(self, run_id: str, origin_id: str, document_id: str, media_type: str):
        started, source_id, url = utc_now(), None, None
        try:
            with self.database.session() as db:
                origin = db.get(DocumentOrigin, origin_id)
                if origin is None or origin.document_id != document_id:
                    raise HTTPException(404)
                source_id, url = origin.source_id, origin.canonical_url
            data = file_path(self.upload_dir, origin_id, media_type).read_bytes()
            result = self._process_origin(origin_id, document_id, data, media_type)
        except Exception:
            result = self._failure(document_id, "PROCESSING_FAILED")
        self.record_item(run_id, 1, source_id, url, result, started)
        return result

    def process_web(self, source_id, url, data, media_type, payload, *, deadline=None):
        """Process already fetched, authorized bytes; web identity never selects uploads."""
        with self.publish_lock, self.database.session() as db:
            source = db.get(DataSource, source_id)
            url = validate_source_url(source, url)
            origin = db.scalar(select(DocumentOrigin).where(DocumentOrigin.source_id == source_id,
                DocumentOrigin.canonical_url == url, DocumentOrigin.origin_kind == "web"))
            if origin is None:
                doc = Document(title=payload.title, context_key=context_key(payload),
                    **{key: getattr(payload, key) for key in ("year", "campus", "major_code", "method")})
                db.add(doc); db.flush()
                origin = DocumentOrigin(document_id=doc.id, source_id=source_id, origin_kind="web",
                    canonical_url=url, original_url=getattr(payload, "original_url", url),
                    publisher=getattr(payload, "publisher", None), published_at=getattr(payload, "published_at", None))
                db.add(origin); db.flush()
            origin_id, document_id = origin.id, origin.document_id
            db.commit()
        return self._process_origin(origin_id, document_id, data, media_type, payload, deadline=deadline)

    def _profile(self):
        return dict(self.indexer.profile) | (self.extractor.profile if self.extractor else {})

    def _process_origin(self, origin_id, document_id, data, media_type, payload=None, *, deadline=None):
        try:
            with self.database.session() as db:
                current = get_document(db, document_id)
                origin = db.get(DocumentOrigin, origin_id)
                if origin is None or origin.document_id != document_id:
                    raise HTTPException(404)
                require_usable(db.get(DataSource, origin.source_id))
                if self.indexer is None:
                    current.quality_reason = "INDEXER_NOT_IMPLEMENTED"
                    db.commit()
                    return IngestionOutcome("skipped", document_id, "INDEXER_NOT_IMPLEMENTED")
                profile = self._profile()
                staged_metadata = metadata(db, current)
                target_context = context_key(payload) if payload else current.context_key
                if payload:
                    staged_metadata.update({key: getattr(payload, key) for key in
                        ("title", "year", "campus", "major_code", "method")})
                raw_hash = hashlib.sha256(data).hexdigest()
                raw_duplicate = db.scalar(select(Document).where(Document.raw_hash == raw_hash,
                    Document.context_key == target_context, Document.state == "ready"))
                raw_unchanged = raw_duplicate is not None and raw_duplicate.index_profile == profile
                if raw_unchanged:
                    text, content_hash = raw_duplicate.content_text, raw_duplicate.content_hash
            if not raw_unchanged:
                if self.extractor:
                    extracted = self.extractor.extract(data, media_type, metadata=staged_metadata, deadline=deadline)
                    text = normalized_text(extracted.text)
                    staged_metadata["pages"] = extracted.page_metadata()
                else:
                    text = normalized_text(self.indexer.extract(data, media_type))
                if not text:
                    raise ExtractionError("EMPTY_TEXT")
                content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            with self.database.session() as db:
                duplicate = db.scalar(select(Document).where(Document.content_hash == content_hash,
                    Document.context_key == target_context))
                unchanged = duplicate is not None and duplicate.state == "ready" and duplicate.index_profile == profile
                disabled_conflict = not staged_metadata["enabled"] and duplicate is not None and duplicate.id != document_id and duplicate.enabled
            if not unchanged and not disabled_conflict:
                # B2 boundary only. Real chunks/vectors and their publication belong to T025-T027.
                self.indexer.index(text, staged_metadata)
            with self.publish_lock, self.database.session() as db:
                current = db.get(Document, document_id)
                origin = db.get(DocumentOrigin, origin_id)
                if current is None or origin is None or origin.document_id != document_id:
                    return IngestionOutcome("error", None, "DOCUMENT_REMOVED")
                require_usable(db.get(DataSource, origin.source_id))
                duplicate = db.scalar(select(Document).where(Document.content_hash == content_hash,
                    Document.context_key == target_context))
                if not current.enabled and duplicate is not None and duplicate.id != current.id and duplicate.enabled:
                    current.last_checked_at = utc_now()
                    db.commit()
                    return IngestionOutcome("skipped", current.id, "DISABLED_DUPLICATE")
                had_content = current.content_hash is not None
                other_origins = db.scalar(select(exists().where(DocumentOrigin.document_id == current.id,
                                                               DocumentOrigin.id != origin_id)))
                target = duplicate or current
                if duplicate is None and had_content and (other_origins or current.context_key != target_context):
                    target = Document(title=staged_metadata["title"], context_key=target_context,
                        enabled=current.enabled, provenance_note=origin.provenance_note,
                        **{key: staged_metadata[key] for key in ("year", "campus", "major_code", "method")})
                    db.add(target); db.flush()
                if not unchanged:
                    target.content_text, target.content_hash = text, content_hash
                    target.index_profile, target.state = profile, "ready"
                    target.quality_reason, target.last_update_error = None, None
                    target.updated_at = utc_now()
                target.raw_hash, target.last_checked_at = raw_hash, utc_now()
                target.last_update_error = None
                if target.provenance_note is None:
                    target.provenance_note = origin.provenance_note
                origin.document_id, origin.retrieved_at = target.id, utc_now()
                origin.active = True
                db.flush()
                if target.id != current.id and not other_origins:
                    db.delete(current)
                db.commit()
                return IngestionOutcome("skipped" if unchanged else ("updated" if had_content else "new"), target.id)
        except Exception as exc:
            reason = exc.reason if isinstance(exc, ExtractionError) else (
                "DOCUMENT_REMOVED" if isinstance(exc, HTTPException) and exc.status_code == 404 else "PROCESSING_FAILED")
            return self._failure(document_id, reason, quarantined=isinstance(exc, ExtractionError) and exc.quarantined)

    def _failure(self, document_id, reason, *, quarantined=False):
        with self.publish_lock, self.database.session() as db:
            current = db.get(Document, document_id)
            if current is None:
                return IngestionOutcome("error", None, "DOCUMENT_REMOVED")
            if current.state == "ready":
                current.last_update_error = reason
            else:
                current.state = "quarantined" if quarantined else "error"
                current.quality_reason = reason
            current.last_checked_at = utc_now()
            db.commit()
        return IngestionOutcome("error", document_id, reason)

    def record_item(self, run_id, item_index, source_id, url, result, started):
        with self.publish_lock, self.database.session() as db:
            identity = result.document_id if result.document_id and db.get(Document, result.document_id) else None
            db.add(CrawlRunItem(run_id=run_id, item_index=item_index, source_id=source_id, canonical_url=url,
                document_id=identity, outcome=result.outcome, reason=result.reason, started_at=started, ended_at=utc_now()))
            run = db.get(CrawlRun, run_id)
            field = result.outcome + "_count"
            setattr(run, field, getattr(run, field) + 1)
            db.commit()

    def set_enabled(self, identity: str, enabled: bool):
        with self.publish_lock, self.database.session() as db:
            doc = get_document(db, identity)
            if enabled:
                usable_origin = db.scalar(select(DocumentOrigin).join(DataSource).where(
                    DocumentOrigin.document_id == identity, DocumentOrigin.active.is_(True),
                    DataSource.enabled.is_(True), DataSource.permission_status == "allowed"))
                if (doc.state != "ready" or usable_origin is None or self.indexer is None
                        or not self.indexer.usable(doc)):
                    raise HTTPException(409)
            doc.enabled, doc.updated_at = enabled, utc_now()
            db.commit()
            return metadata(db, doc)

    def original(self, db, identity: str):
        get_document(db, identity)
        origins = db.scalars(select(DocumentOrigin).where(DocumentOrigin.document_id == identity))
        for origin in origins:
            if origin.origin_kind != "upload":
                continue
            for media_type in MEDIA:
                path = file_path(self.upload_dir, origin.id, media_type)
                if path.is_file() and not path.is_symlink():
                    return path, media_type
        raise HTTPException(404)

    def delete(self, identity: str):
        with self.publish_lock, self.database.session() as db:
            doc = get_document(db, identity)
            origins = db.scalars(select(DocumentOrigin).where(DocumentOrigin.document_id == identity)).all()
            paths = [file_path(self.upload_dir, origin.id, media) for origin in origins
                     if origin.origin_kind == "upload" for media in MEDIA]
            db.delete(doc)
            db.commit()
            for path in paths:
                path.unlink(missing_ok=True)
