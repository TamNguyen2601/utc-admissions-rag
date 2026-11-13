"""Admin sources, imports and the single shared crawl run slot."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query, Request
from starlette.datastructures import UploadFile
from starlette.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db.session import get_session
from app.models.knowledge import DataSource
from app.schemas.document import PageResponse, SourceInput, SourceResponse
from app.services.auth import Identity
from app.services.sources import patch_source, save_source, source_response
from app.services.adapters.job_import import parse_import
from app.services.documents import MAX_UPLOAD
from app.schemas.career import RunAccepted
from app.schemas.crawl import RunInput, RunResponse, RunItemResponse, run_response
from app.models.crawl import CrawlRun, CrawlRunItem
from app.services.sources import require_usable

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])
DB = Annotated[Session, Depends(get_session)]
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


def paginated(db, query, page, page_size, serialize):
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    rows = db.scalars(query.offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [serialize(row) for row in rows], "total": total, "page": page, "page_size": page_size}


def get_run(db, identity):
    run = db.get(CrawlRun, str(identity))
    if run is None:
        raise HTTPException(404)
    return run


@router.post('/runs', status_code=202, response_model=RunAccepted)
def start_run(payload: RunInput, request: Request, db: DB, identity=Depends(require_admin)):
    source_id = str(payload.source_id) if payload.source_id else None
    if source_id:
        require_usable(db.get(DataSource, source_id))
    coordinator = request.app.state.coordinator
    crawl = request.app.state.crawl
    run = coordinator.claim('manual', source_id, identity.user.id)
    coordinator.start(run.id, lambda run_id: crawl.run(
        run_id, [source_id] if source_id else None))
    return JSONResponse(status_code=202, content={'run_id': run.id, 'state': 'running'},
                        headers={'Location': f'/api/v1/admin/runs/{run.id}'})


@router.get('/runs', response_model=PageResponse[RunResponse])
def list_runs(db: DB, page: Page = 1, page_size: PageSize = 20):
    return paginated(db, select(CrawlRun).order_by(CrawlRun.created_at.desc(), CrawlRun.id.desc()),
                     page, page_size, run_response)


@router.get('/runs/{identity}', response_model=RunResponse)
def run_detail(identity: UUID, db: DB):
    return run_response(get_run(db, identity))


@router.get('/runs/{identity}/items', response_model=PageResponse[RunItemResponse])
def run_items(identity: UUID, db: DB, page: Page = 1, page_size: PageSize = 20):
    get_run(db, identity)
    return paginated(db, select(CrawlRunItem).where(CrawlRunItem.run_id == str(identity))
                     .order_by(CrawlRunItem.item_index), page, page_size, RunItemResponse.model_validate)


@router.post('/runs/{identity}/stop', response_model=RunResponse)
def stop_run(identity: UUID, request: Request, actor=Depends(require_admin)):
    return run_response(request.app.state.coordinator.request_stop(str(identity), actor.user.id))


@router.get("/sources", response_model=PageResponse[SourceResponse])
def sources(db: DB, page: Page = 1, page_size: PageSize = 20):
    return paginated(db, select(DataSource).order_by(DataSource.name, DataSource.id), page, page_size, source_response)


@router.post("/sources", status_code=201, response_model=SourceResponse)
def create_source(payload: SourceInput, request: Request):
    with request.app.state.knowledge_lock, request.app.state.database.session() as db:
        return source_response(save_source(db, payload))


@router.patch("/sources/{identity}", response_model=SourceResponse)
def update_source(identity: UUID, request: Request, changes: Annotated[dict, Body()]):
    with request.app.state.knowledge_lock, request.app.state.database.session() as db:
        source = db.get(DataSource, str(identity))
        if source is None: raise HTTPException(404)
        return source_response(patch_source(db, source, changes))


@router.post('/jobs/import', status_code=202, response_model=RunAccepted)
async def import_jobs(request: Request, background: BackgroundTasks, identity=Depends(require_admin)):
    # RBAC runs before reading/parsing files. Structural failures never claim a run.
    async with request.form(max_files=1, max_fields=20) as form:
        keys = list(form.keys())
        if set(keys) - {'file', 'source_id'} or any(len(form.getlist(k)) != 1 for k in keys):
            raise HTTPException(422)
        file = form.get('file')
        if not isinstance(file, UploadFile):
            raise HTTPException(422)
        default = form.get('source_id')
        try:
            default = str(UUID(default)) if default is not None else None
        except (ValueError, TypeError, AttributeError):
            raise HTTPException(422) from None
        data = await file.read(MAX_UPLOAD + 1)
        rows = parse_import(data, file.filename, (file.content_type or '').split(';', 1)[0].lower())
    coordinator, service = request.app.state.coordinator, request.app.state.jobs
    run = coordinator.claim('job_import', actor_id=identity.user.id)
    background.add_task(coordinator.execute, run.id, lambda run_id: service.import_rows(run_id, rows, default))
    return JSONResponse(status_code=202, content={'run_id': run.id, 'state': 'running'},
                        headers={'Location': f'/api/v1/admin/runs/{run.id}'})
