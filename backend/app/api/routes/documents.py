from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import ValidationError
from starlette.datastructures import UploadFile
from starlette.responses import FileResponse, JSONResponse, Response

from app.api.deps import optional_auth, require_admin
from app.api.routes.admin import DB, Page, PageSize, paginated
from app.schemas.document import DocumentDetail, DocumentMetadata, PageResponse, ReasonInput, UploadInput
from app.services.documents import MAX_UPLOAD, document_query, get_document, metadata, validate_file
from app.models.knowledge import DataSource
from app.services.sources import require_usable, validate_source_url

router = APIRouter()
admin = APIRouter(prefix="/admin/documents", dependencies=[Depends(require_admin)])


@admin.post("/upload", status_code=202)
async def upload(request: Request, background: BackgroundTasks, identity=Depends(require_admin)):
    # Parse only after RBAC. Reject duplicate/extra fields, including client origin IDs.
    async with request.form(max_files=1, max_fields=20) as form:
        keys = list(form.keys())
        if (set(keys) - (set(UploadInput.model_fields) | {"file"})
                or any(len(form.getlist(key)) != 1 for key in keys)):
            raise HTTPException(422)
        file = form.get("file")
        if not isinstance(file, UploadFile): raise HTTPException(422)
        try:
            payload = UploadInput.model_validate({key: form[key] for key in keys if key != "file"})
        except ValidationError:
            raise HTTPException(422) from None
        data = await file.read(MAX_UPLOAD + 1)
        media = (file.content_type or "").split(";", 1)[0].lower()
        validate_file(data, media, file.filename)
    coordinator = request.app.state.coordinator
    # Reject missing/unusable sources before recording a run (and its source FK).
    with request.app.state.database.session() as db:
        source = db.get(DataSource, str(payload.source_id))
        require_usable(source)
        if payload.source_url: validate_source_url(source, payload.source_url)
    run = coordinator.claim("upload", str(payload.source_id), identity.user.id)
    service = request.app.state.documents
    try:
        origin_id, document_id = service.accept_upload(payload, data, media)
    except Exception:
        coordinator.finish(run.id, failed=True)
        raise
    background.add_task(coordinator.execute, run.id,
        lambda run_id: service.process_upload(run_id, origin_id, document_id, media))
    return JSONResponse(status_code=202, content={"run_id": run.id, "origin_id": origin_id, "document_id": document_id},
                        headers={"Location": f"/api/v1/admin/runs/{run.id}"})


@admin.get("", response_model=PageResponse[DocumentMetadata])
def list_documents(db: DB, q: Annotated[str | None, Query(max_length=500)] = None,
                   state: Literal["pending", "ready", "quarantined", "error"] | None = None,
                   enabled: bool | None = None, page: Page = 1, page_size: PageSize = 20):
    return paginated(db, document_query(q, state, enabled), page, page_size,
                     lambda doc: metadata(db, doc))


@admin.get("/{identity}", response_model=DocumentDetail)
def detail(identity: UUID, db: DB):
    return metadata(db, get_document(db, str(identity)), detail=True)


@admin.get("/{identity}/original")
def original(identity: UUID, request: Request, db: DB):
    path, media = request.app.state.documents.original(db, str(identity))
    return FileResponse(path, media_type=media, filename="document" + path.suffix,
                        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})


@admin.post("/{identity}/disable", response_model=DocumentMetadata)
def disable(identity: UUID, payload: ReasonInput, request: Request):
    return request.app.state.documents.set_enabled(str(identity), False)


@admin.post("/{identity}/enable", response_model=DocumentMetadata)
def enable(identity: UUID, payload: ReasonInput, request: Request):
    return request.app.state.documents.set_enabled(str(identity), True)


@admin.delete("/{identity}", status_code=204)
def delete_document(identity: UUID, request: Request):
    request.app.state.documents.delete(str(identity))
    return Response(status_code=204)


@router.get("/documents/{identity}/source", dependencies=[Depends(optional_auth)])
def public_source(identity: UUID, db: DB, page: Annotated[int | None, Query(ge=1)] = None):
    get_document(db, str(identity))
    # T028 adds permitted excerpts from real chunks. Never publish private metadata
    # or stub text through this public endpoint at checkpoint B1.
    raise HTTPException(410)


router.include_router(admin)
