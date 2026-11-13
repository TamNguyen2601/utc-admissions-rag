"""Bounded UTF-8 file parsing; validation errors in rows do not reject the file."""
import csv
import io
import json
from pathlib import Path

from fastapi import HTTPException
from pydantic import ValidationError

from app.models.crawl import CrawlRun
from app.models.knowledge import DataSource
from app.schemas.career import JobRow
from app.services.documents import IngestionOutcome, MAX_UPLOAD

MAX_ROWS = 5000
REQUIRED = {'title', 'employer', 'description', 'source_url', 'collected_at'}


def parse_import(data, filename, media_type):
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413)
    suffix = Path(filename or '').suffix.lower()
    types = {'.csv': {'text/csv', 'application/csv', 'application/vnd.ms-excel'},
             '.json': {'application/json'}}
    if suffix not in types or media_type not in types[suffix]:
        raise HTTPException(415)

    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result

    def invalid_constant(_value):
        raise ValueError('Invalid JSON constant')

    try:
        text = data.decode('utf-8-sig')
        if suffix == '.json':
            rows = json.loads(text, object_pairs_hook=object_pairs, parse_constant=invalid_constant)
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ValueError
        else:
            # csv's default 128 KiB field limit must not impose an undocumented limit.
            # This process-wide setting is constant and never lowered by another request.
            csv.field_size_limit(MAX_UPLOAD)
            reader = csv.DictReader(io.StringIO(text, newline=''), strict=True)
            fields = reader.fieldnames
            if (not fields or len(fields) != len(set(fields)) or not REQUIRED <= set(fields)
                    or set(fields) - set(JobRow.model_fields)):
                raise ValueError
            rows = []
            for raw in reader:
                if None in raw or any(value is None for value in raw.values()):
                    raise ValueError
                # Empty optional CSV cells are null/default, as absent JSON fields are.
                rows.append({key: value for key, value in raw.items() if value != '' or key in REQUIRED})
                if len(rows) > MAX_ROWS:
                    raise ValueError
        if len(rows) > MAX_ROWS:
            raise ValueError
        return rows
    except (UnicodeError, ValueError, csv.Error, RecursionError):
        raise HTTPException(422) from None


class JobImportAdapter:
    def __init__(self, jobs):
        self.jobs = jobs

    def run(self, run_id, rows, default_source_id=None, *, record_sources=True):
        from app.services.jobs import JobRowError
        jobs, seen, sources = self.jobs, {}, {}
        with jobs.database.session() as db:
            run = db.get(CrawlRun, run_id)
            offset = run.new_count + run.updated_count + run.skipped_count + run.error_count
        for index, raw in enumerate(rows, offset + 1):
            if jobs.coordinator.should_stop(run_id):
                break
            started, source_id, url = jobs.now(), None, None
            try:
                row = JobRow.model_validate(raw)
                source_id = str(row.source_id) if row.source_id else default_source_id
                source_id, url = jobs.validate_row(row, source_id)
                result = jobs.upsert(row, source_id, url, seen)
            except (ValidationError, JobRowError, HTTPException) as exc:
                # Preserve valid source/URL metadata even when another row field is bad.
                source_id, url = jobs.log_metadata(raw, default_source_id)
                reason = exc.reason if isinstance(exc, JobRowError) else 'INVALID_ROW'
                result = IngestionOutcome('error', None, reason)
            except Exception:
                # Stage/SQL failures roll back the current row only, never prior rows.
                result = IngestionOutcome('error', None, 'PROCESSING_FAILED')
            jobs.documents.record_item(run_id, index, source_id, url, result, started)
            if source_id:
                sources[source_id] = sources.get(source_id, False) or result.outcome == 'error'
        if record_sources:
            for identity, error in sources.items():
                stopped = jobs.coordinator.should_stop(run_id)
                jobs.coordinator.record_source(run_id, identity,
                    'stopped' if stopped else 'error' if error else 'success',
                    'STOP_REQUESTED' if stopped else 'ROW_ERRORS' if error else None)
