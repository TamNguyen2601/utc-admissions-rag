from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from app.api.deps import required_auth
from app.schemas.conversation import (
    ConversationInput, ConversationPage, ConversationReply, ConversationResponse,
    CreateConversation, MessagePage, RenameConversation,
)
from app.services.auth import Identity

router = APIRouter(prefix='/conversations')
Auth = Annotated[Identity, Depends(required_auth)]
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


@router.post('', status_code=201, response_model=ConversationResponse)
def create(payload: CreateConversation, request: Request, identity: Auth):
    return request.app.state.conversations.create(identity.user.id, payload.title)


@router.get('', response_model=ConversationPage)
def list_conversations(request: Request, identity: Auth, page: Page = 1, page_size: PageSize = 20):
    return request.app.state.conversations.list(identity.user.id, page, page_size)


@router.get('/{conversation_id}', response_model=ConversationResponse)
def open_conversation(conversation_id: UUID, request: Request, identity: Auth):
    return request.app.state.conversations.open(str(conversation_id), identity.user.id)


@router.get('/{conversation_id}/messages', response_model=MessagePage)
def messages(conversation_id: UUID, request: Request, identity: Auth,
             page: Page = 1, page_size: PageSize = 20):
    return request.app.state.conversations.messages(str(conversation_id), identity.user.id, page, page_size)


@router.post('/{conversation_id}/messages', response_model=ConversationReply)
async def continue_conversation(conversation_id: UUID, payload: ConversationInput,
                                request: Request, identity: Auth):
    state = request.app.state
    with state.conversations.active(str(conversation_id), identity.user.id):
        return await state.chat.reply(payload, request.state.request_id, identity,
                                      conversation_id=str(conversation_id))


@router.patch('/{conversation_id}', response_model=ConversationResponse)
def rename(conversation_id: UUID, payload: RenameConversation, request: Request, identity: Auth):
    return request.app.state.conversations.rename(str(conversation_id), identity.user.id, payload.title)


@router.delete('/{conversation_id}', status_code=204)
def delete_conversation(conversation_id: UUID, request: Request, identity: Auth):
    request.app.state.conversations.delete(str(conversation_id), identity.user.id)
    return Response(status_code=204)
