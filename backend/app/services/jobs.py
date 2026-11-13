"""Job business upserts, atomic provenance publish and observed job counts."""
from dataclasses import dataclass
import hashlib
import json
from typing import Protocol
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, select

from app.db.base import utc_now
from app.models.career import JobPosting
from app.models.knowledge import DataSource, Document, DocumentChunk, DocumentOrigin
from app.services.documents import IngestionOutcome, normalized_text
from app.services.embedding import read_vector
from app.services.sources import require_usable, validate_source_url

PAYLOAD_FIELDS = ('external_id', 'title', 'employer', 'description', 'posted_at', 'deadline_at',
                  'observed_status', 'career_group', 'classification_reason')
CAREER_CONTEXT = json.dumps(dict(kind='career', year=None, campus=None, major_code=None, method=None),
                            sort_keys=True)
SCOPE_NOTE = ('Số tin đang tuyển quan sát được từ các nguồn và thời điểm đã nêu, không phải số vị trí '
              'hay toàn thị trường. Số đang tuyển dùng cùng bộ lọc ngành/nhóm nghề, độc lập bộ lọc trạng thái và trang.')


class CareerResolver(Protocol):
    """Catalogue seam for T048. None = stale/unusable major; missing major raises 404."""
    def career_groups(self) -> set[str]: ...
    def major_groups(self, major_id: str) -> set[str] | None: ...


class EmptyCareerResolver:
    """E1 has no real catalogue. Do not fabricate majors or group codes."""
    def career_groups(self): return set()
    def major_groups(self, major_id): raise HTTPException(404)


class JobRowError(ValueError):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class StagedJobDocument:
    text: str
    content_hash: str
    profile: dict
    chunks: list | None


def job_status(job, now):
    if job.observed_status == 'closed' or (job.deadline_at is not None and job.deadline_at < now):
        return 'expired'
    if job.observed_status == 'open' and job.deadline_at is not None:
        return 'open'
    return 'unverified'


class JobService:
    def __init__(self, database, documents, coordinator, *, resolver=None, now=utc_now):
        self.database, self.documents, self.coordinator = database, documents, coordinator
        self.resolver, self.now = resolver or EmptyCareerResolver(), now

    def import_rows(self, run_id, rows, default_source_id=None):
        from app.services.adapters.job_import import JobImportAdapter
        return JobImportAdapter(self).run(run_id, rows, default_source_id)

    @staticmethod
    def publisher(source):
        require_usable(source)
        if (source.kind not in {'career', 'topcv'} or not source.base_url
                or not source.allowed_paths_json or not source.robots_url or not source.terms_url):
            raise JobRowError('SOURCE_NOT_VERIFIED')

    def validate_row(self, row, source_id):
        if not source_id:
            raise JobRowError('SOURCE_REQUIRED')
        now = self.now()
        if row.collected_at > now or (row.posted_at is not None and row.posted_at > now):
            raise JobRowError('FUTURE_TIMESTAMP')
        with self.database.session() as db:
            source = db.get(DataSource, source_id)
            self.publisher(source)
            return source_id, validate_source_url(source, row.source_url)

    def log_metadata(self, raw, default_source_id):
        """Never put an invalid/missing source into a run item's FK or an invalid URL in its log."""
        try:
            identity = str(UUID(str(raw.get('source_id') or default_source_id)))
            with self.database.session() as db:
                source = db.get(DataSource, identity)
                if source is None:
                    return None, None
                try:
                    return identity, validate_source_url(source, raw.get('source_url', ''))
                except (HTTPException, ValueError, TypeError, AttributeError):
                    return identity, None
        except (ValueError, TypeError, AttributeError):
            return None, None

    @staticmethod
    def resolve(db, source_id, url, external_id):
        origin = db.scalar(select(DocumentOrigin).where(DocumentOrigin.source_id == source_id,
            DocumentOrigin.canonical_url == url, DocumentOrigin.origin_kind == 'web'))
        at_url = db.scalar(select(JobPosting).where(JobPosting.origin_id == origin.id)) if origin else None
        by_id = db.scalar(select(JobPosting).where(JobPosting.source_id == source_id,
            JobPosting.identity_key == 'ext:' + external_id)) if external_id else None
        # Identity checks precede every write, including observation/provenance changes.
        if at_url and external_id and at_url.external_id and external_id != at_url.external_id:
            raise JobRowError('identity_conflict')
        if by_id and at_url and by_id.id != at_url.id:
            raise JobRowError('identity_conflict')
        if by_id and origin and by_id.origin_id != origin.id:
            # An occupied web origin cannot be stolen, even if it has no job yet.
            raise JobRowError('identity_conflict')
        job = by_id or at_url
        if job and job.source_id != source_id:
            raise JobRowError('identity_conflict')
        effective_id = external_id or (job.external_id if job else None)
        key = 'ext:' + effective_id if effective_id else 'url:' + url
        return job, effective_id, key, origin

    @staticmethod
    def payload(row, url, external_id):
        return (url, external_id, *(getattr(row, key) for key in PAYLOAD_FIELDS[1:]))

    @staticmethod
    def stored_payload(db, job):
        origin = db.get(DocumentOrigin, job.origin_id)
        return (origin.canonical_url, *(getattr(job, key) for key in PAYLOAD_FIELDS))

    def _stage(self, row):
        # Plain job data already normalized/validated; it shares the existing Indexer.
        text = normalized_text('\n'.join((row.title, row.employer, row.description)))
        content_hash = hashlib.sha256(text.encode()).hexdigest()
        profile = self.documents._profile()
        with self.database.session() as db:
            duplicate = db.scalar(select(Document).where(Document.content_hash == content_hash,
                                                         Document.context_key == CAREER_CONTEXT))
            reusable = (duplicate is not None and duplicate.state == 'ready'
                        and duplicate.index_profile == profile and self.documents.indexer.usable(duplicate))
        chunks = None
        if not reusable:
            metadata = dict(title=row.title, year=None, campus=None, major_code=None, method=None,
                pages=[dict(text=text, page=None, section=None, extraction_kind='native', numeric_eligible=False)])
            chunks = self.documents.indexer.index(text, metadata)
            if not isinstance(chunks, list) or not chunks:
                raise JobRowError('INDEXING_FAILED')
            for chunk in chunks:
                read_vector(chunk['embedding'])
        return StagedJobDocument(text, content_hash, profile, chunks)

    def upsert(self, row, source_id, url, seen):
        with self.database.session() as db:
            job, effective_id, key, _ = self.resolve(db, source_id, url, row.external_id)
            payload = self.payload(row, url, effective_id)
            if job and job.id in seen:
                if seen[job.id] != payload:
                    raise JobRowError('conflict')
                return IngestionOutcome('skipped', db.get(DocumentOrigin, job.origin_id).document_id)
            baseline = (job.id, self.stored_payload(db, job), job.origin_id) if job else None
            old_origin = db.get(DocumentOrigin, job.origin_id) if job else None
            old_document_id = old_origin.document_id if old_origin else None
        # No SQL mutations, publish lock, or coordinator mutex during embedding.
        staged = self._stage(row)
        with self.documents.publish_lock, self.database.session() as db:
            source = db.get(DataSource, source_id)
            self.publisher(source)
            if validate_source_url(source, row.source_url) != url:
                raise JobRowError('SOURCE_OR_URL_DENIED')
            if baseline and (db.get(JobPosting, baseline[0]) is None
                             or db.get(Document, old_document_id) is None):
                raise JobRowError('DOCUMENT_REMOVED')
            job, effective_id, key, url_origin = self.resolve(db, source_id, url, row.external_id)
            current_baseline = (job.id, self.stored_payload(db, job), job.origin_id) if job else None
            if current_baseline != baseline:
                raise JobRowError('JOB_CHANGED')
            payload = self.payload(row, url, effective_id)
            outcome = 'new' if job is None else 'skipped' if baseline[1] == payload else 'updated'
            origin = db.get(DocumentOrigin, job.origin_id) if job else url_origin
            old_doc = db.get(Document, origin.document_id) if origin else None
            duplicate = db.scalar(select(Document).where(Document.content_hash == staged.content_hash,
                                                         Document.context_key == CAREER_CONTEXT))
            if old_doc and not old_doc.enabled and duplicate and duplicate.id != old_doc.id and duplicate.enabled:
                if job:
                    seen[job.id] = payload
                return IngestionOutcome('skipped', old_doc.id, 'DISABLED_DUPLICATE')
            reusable = (duplicate is not None and duplicate.state == 'ready'
                        and duplicate.index_profile == staged.profile and self.documents.indexer.usable(duplicate))
            if not reusable and staged.chunks is None:
                raise JobRowError('INDEX_CHANGED_DURING_STAGING')
            target = duplicate
            if target is None:
                target = Document(title=row.title, context_key=CAREER_CONTEXT,
                                  enabled=old_doc.enabled if old_doc else True)
                db.add(target)
                db.flush()
            if origin is None:
                origin = DocumentOrigin(source_id=source_id, document_id=target.id, origin_kind='web',
                    canonical_url=url, original_url=row.source_url)
                db.add(origin)
                db.flush()
            if not reusable:
                target.content_text, target.content_hash = staged.text, staged.content_hash
                target.raw_hash = hashlib.sha256(staged.text.encode()).hexdigest()
                target.index_profile, target.state = staged.profile, 'ready'
                target.quality_reason, target.last_update_error = None, None
                target.updated_at = self.now()
                db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == target.id))
                for chunk in staged.chunks:
                    snapshot = dict(origin_id=origin.id, url=url, source_name=source.name,
                        title=row.title, year=None, campus=None, major_code=None, method=None,
                        page=chunk['page'], section=chunk['section'])
                    db.add(DocumentChunk(document_id=target.id, **chunk, source_snapshot_json=snapshot))
            target.last_checked_at = self.now()
            origin.document_id = target.id
            origin.retrieved_at = row.collected_at  # Import time never replaces publication observation time.
            if outcome != 'skipped':
                origin.canonical_url, origin.original_url = url, row.source_url
                origin.publisher, origin.published_at = source.name, row.posted_at
            # Existing inactive origins stay inactive until explicitly restored.
            if job is None:
                job = JobPosting(source_id=source_id, origin_id=origin.id, identity_key=key)
                db.add(job)
            if outcome != 'skipped':
                job.identity_key, job.external_id = key, effective_id
                for field in PAYLOAD_FIELDS[1:]:
                    setattr(job, field, getattr(row, field))
                job.updated_at = self.now()
            db.flush()
            # Detach only this origin; other jobs/origins keep their old document.
            if old_doc and old_doc.id != target.id and not db.scalar(select(DocumentOrigin.id)
                    .where(DocumentOrigin.document_id == old_doc.id).limit(1)):
                db.delete(old_doc)
            db.commit()
            seen[job.id] = payload
            return IngestionOutcome(outcome, target.id)

    def list_jobs(self, *, major_id=None, career_group=None, status=None, page=1, page_size=20):
        now = self.now()
        if career_group is not None and career_group not in self.resolver.career_groups():
            raise HTTPException(422)
        groups = self.resolver.major_groups(major_id) if major_id else None
        stale_major = major_id is not None and groups is None
        with self.database.session() as db:
            rows = db.execute(select(JobPosting, DocumentOrigin, DataSource, Document)
                .join(DocumentOrigin, JobPosting.origin_id == DocumentOrigin.id)
                .join(DataSource, JobPosting.source_id == DataSource.id)
                .join(Document, DocumentOrigin.document_id == Document.id)
                .where(DocumentOrigin.source_id == JobPosting.source_id,
                       DocumentOrigin.origin_kind == 'web', DocumentOrigin.active.is_(True),
                       Document.enabled.is_(True), Document.state == 'ready')
                .order_by(JobPosting.updated_at.desc(), JobPosting.id)).all()
            usable = []
            for job, origin, source, document in rows:
                try:
                    self.publisher(source)
                    validate_source_url(source, origin.canonical_url)
                except (HTTPException, JobRowError):
                    continue
                usable.append((job, origin, source))
            ready = bool(usable) and not stale_major
            filtered = [(j, o, s) for j, o, s in usable if not stale_major
                        and (major_id is None or j.career_group in groups)
                        and (career_group is None or j.career_group == career_group)]
            count = sum(job_status(j, now) == 'open' for j, _, _ in filtered) if ready else None
            matching = [(j, o, s) for j, o, s in filtered if status is None or job_status(j, now) == status]
            items = []
            for job, origin, source in matching[(page - 1) * page_size:page * page_size]:
                items.append(dict(id=job.id, source_id=source.id, identity_key=job.identity_key,
                    document_id=origin.document_id, origin_id=origin.id,
                    **{key: getattr(job, key) for key in PAYLOAD_FIELDS[1:] if key != 'observed_status'},
                    source_url=origin.canonical_url, source_name=source.name, collected_at=origin.retrieved_at,
                    updated_at=job.updated_at, status=job_status(job, now)))
            sources = {s.id: dict(id=s.id, name=s.name) for _, _, s in filtered}
            return dict(status='ready' if ready else 'data_missing', items=items, total=len(matching),
                page=page, page_size=page_size, observed_open_count=count, as_of=now,
                sources=sorted(sources.values(), key=lambda s: (s['name'], s['id'])), scope_note=SCOPE_NOTE)
