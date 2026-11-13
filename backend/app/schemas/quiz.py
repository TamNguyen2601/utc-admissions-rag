"""Closed catalogue/rubric import and public quiz DTOs. No applicant profile."""
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, field_validator, model_validator

from app.schemas.document import ClosedModel, clean

Text = Annotated[str, StringConstraints(min_length=1, max_length=4000)]
Direction = Literal['positive', 'negative', 'none']
Position = Annotated[int, Field(strict=True, ge=1, le=10)]
Value = Annotated[int, Field(strict=True, ge=1, le=5)]


class CatalogueText(ClosedModel):
    @field_validator('*', mode='before')
    @classmethod
    def normalize(cls, value):
        return clean(value, 4000) if isinstance(value, str) else value


class ScoringRule(CatalogueText):
    direction: Direction
    reason: Text


class CareerGroup(CatalogueText):
    code: Text
    label: Text
    reason: Text


class MajorInput(CatalogueText):
    id: UUID
    code: Text
    name: Text
    campus: Text
    description: Text
    source_document_id: UUID
    source_content_hash: Annotated[str, StringConstraints(pattern=r'^[0-9a-f]{64}$')]
    source_page: Annotated[int, Field(strict=True, ge=1)] | None
    career_groups: list[CareerGroup]

    @model_validator(mode='after')
    def unique_groups(self):
        if len({g.code for g in self.career_groups}) != len(self.career_groups):
            raise ValueError('Duplicate career group')
        return self


class QuestionInput(CatalogueText):
    id: UUID
    position: Position
    text: Text
    scoring: dict[UUID, ScoringRule]

    @field_validator('scoring', mode='before')
    @classmethod
    def unique_major_keys(cls, value):
        if isinstance(value, dict) and len({UUID(str(key)) for key in value}) != len(value):
            raise ValueError('Duplicate scoring identity')
        return value


class CatalogInput(ClosedModel):
    majors: Annotated[list[MajorInput], Field(min_length=3)]
    questions: Annotated[list[QuestionInput], Field(min_length=10, max_length=10)]

    @model_validator(mode='after')
    def complete_rubric(self):
        ids = {m.id for m in self.majors}
        if len(ids) != len(self.majors) or len({(m.code, m.campus) for m in self.majors}) != len(self.majors):
            raise ValueError('Duplicate major')
        if {q.position for q in self.questions} != set(range(1, 11)) or len({q.id for q in self.questions}) != 10:
            raise ValueError('Invalid question identities/positions')
        if any(set(q.scoring) != ids or not any(r.direction != 'none' for r in q.scoring.values())
               for q in self.questions):
            raise ValueError('Incomplete scoring mapping')
        if any(not any(q.scoring[mid].direction != 'none' for q in self.questions) for mid in ids):
            raise ValueError('Zero scoring denominator')
        return self


class MajorSource(ClosedModel):
    document_id: UUID
    title: str
    url: str
    source_name: str
    page: int | None


class Major(ClosedModel):
    id: UUID
    code: str
    name: str
    campus: str
    description: str
    career_groups: list[CareerGroup]
    sources: Annotated[list[MajorSource], Field(min_length=1)]


class Option(ClosedModel):
    value: Value
    label: str


class PublicScoring(ScoringRule):
    major_id: UUID


class Question(ClosedModel):
    id: UUID
    position: Position
    text: str
    options: Annotated[list[Option], Field(min_length=5, max_length=5)]
    scoring: Annotated[list[PublicScoring], Field(min_length=3)]


class ReadyQuiz(ClosedModel):
    status: Literal['ready']
    rubric_version: str
    questions: Annotated[list[Question], Field(min_length=10, max_length=10)]
    scoring_description: str
    missing_fields: Annotated[list[str], Field(max_length=0)]
    message: None


class MissingQuiz(ClosedModel):
    status: Literal['data_missing']
    rubric_version: None
    questions: Annotated[list[Question], Field(max_length=0)]
    scoring_description: None
    missing_fields: Annotated[list[str], Field(min_length=1)]
    message: Text


QuizResponse = Annotated[ReadyQuiz | MissingQuiz, Field(discriminator='status')]


class Answer(ClosedModel):
    question_id: UUID
    value: Value


class RecommendationInput(ClosedModel):
    rubric_version: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    answers: Annotated[list[Answer], Field(min_length=10, max_length=10)]

    @model_validator(mode='after')
    def unique_answers(self):
        if len({a.question_id for a in self.answers}) != 10:
            raise ValueError('Duplicate answers')
        return self


DISCLAIMER = 'Kết quả chỉ mang tính tham khảo, không bảo đảm trúng tuyển.'


class Recommendation(ClosedModel):
    major: Major
    fit_score: Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]
    reasons: Annotated[list[str], Field(min_length=1, max_length=2)]


class RecommendationBase(ClosedModel):
    disclaimer: Literal[DISCLAIMER]


class ReadyRecommendations(RecommendationBase):
    status: Literal['ready']
    rubric_version: str
    items: Annotated[list[Recommendation], Field(min_length=3, max_length=5)]
    missing_fields: Annotated[list[str], Field(max_length=0)]
    message: None


class MissingRecommendations(RecommendationBase):
    status: Literal['data_missing']
    rubric_version: None
    items: Annotated[list[Recommendation], Field(max_length=0)]
    missing_fields: Annotated[list[str], Field(min_length=1)]
    message: Text


class UnmatchedRecommendations(RecommendationBase):
    status: Literal['no_match', 'insufficient_matches']
    rubric_version: str
    items: Annotated[list[Recommendation], Field(max_length=0)]
    missing_fields: Annotated[list[str], Field(max_length=0)]
    message: Text


RecommendationResponse = Annotated[
    ReadyRecommendations | MissingRecommendations | UnmatchedRecommendations, Field(discriminator='status')]
