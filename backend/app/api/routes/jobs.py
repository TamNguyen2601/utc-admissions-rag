from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import optional_auth
from app.api.routes.admin import Page, PageSize
from app.schemas.career import JobsResponse

router = APIRouter(dependencies=[Depends(optional_auth)])


@router.get('/jobs', response_model=JobsResponse)
def jobs(request: Request, major_id: UUID | None = None,
         career_group: Annotated[str | None, Query(min_length=1, max_length=500)] = None,
         status: Literal['open', 'expired', 'unverified'] | None = None,
         page: Page = 1, page_size: PageSize = 20):
    return request.app.state.jobs.list_jobs(major_id=str(major_id) if major_id else None,
        career_group=career_group, status=status, page=page, page_size=page_size)
