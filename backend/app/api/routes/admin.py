"""Admin source registry, checkpoint T018. Run endpoints arrive at T049."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db.session import get_session
from app.models.knowledge import DataSource
from app.schemas.document import PageResponse, SourceInput, SourceResponse
from app.services.auth import Identity
from app.services.sources import patch_source, save_source, source_response

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])
DB = Annotated[Session, Depends(get_session)]
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


def paginated(db, query, page, page_size, serialize):
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    rows = db.scalars(query.offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [serialize(row) for row in rows], "total": total, "page": page, "page_size": page_size}


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
