from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import optional_auth
from app.api.routes.admin import Page, PageSize
from app.schemas.document import PageResponse
from app.schemas.quiz import Major, QuizResponse, RecommendationInput, RecommendationResponse

router = APIRouter(dependencies=[Depends(optional_auth)])


@router.get('/catalog/majors', response_model=PageResponse[Major])
def majors(request: Request, campus: Annotated[str | None, Query(min_length=1, max_length=500)] = None,
           page: Page = 1, page_size: PageSize = 20):
    return request.app.state.recommendation.list_majors(campus=campus, page=page, page_size=page_size)


@router.get('/quiz', response_model=QuizResponse)
def quiz(request: Request):
    return request.app.state.recommendation.quiz()


@router.post('/recommendations', response_model=RecommendationResponse)
def recommend(payload: RecommendationInput, request: Request):
    return request.app.state.recommendation.recommend(payload)
