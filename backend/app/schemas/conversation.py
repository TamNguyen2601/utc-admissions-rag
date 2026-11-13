"""Closed history request and response DTOs."""
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator

from app.schemas.chat import Citation, Context, Reply
from app.schemas.document import ClosedModel, clean


class CreateConversation(ClosedModel):
    title: str = 'Hội thoại mới'

    @field_validator('title')
    @classmethod
    def title_length(cls, value):
        return clean(value, 100)


class RenameConversation(CreateConversation):
    title: str


class ConversationInput(ClosedModel):
    message: str
    context: Context = Field(default_factory=Context)

    @field_validator('message')
    @classmethod
    def message_length(cls, value):
        return clean(value, 4000)


class ConversationResponse(ClosedModel):
    id: UUID
    title: str
    created_at: AwareDatetime
    updated_at: AwareDatetime


class ConversationPage(ClosedModel):
    items: list[ConversationResponse]
    total: int
    page: int
    page_size: int


class MessageResponse(ClosedModel):
    id: UUID
    seq: int
    sender: Literal['user', 'assistant']
    content: str
    reply_status: str | None
    citations: list[Citation]
    created_at: AwareDatetime


class MessagePage(ClosedModel):
    items: list[MessageResponse]
    total: int
    page: int
    page_size: int


class ConversationReply(ClosedModel):
    user_message_id: UUID
    assistant_message_id: UUID
    reply: Reply
