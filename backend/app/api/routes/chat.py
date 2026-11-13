from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.deps import optional_auth
from app.schemas.chat import GuestChatInput, Reply
from app.services.auth import Identity

router = APIRouter(prefix='/chat')


@router.post('/guest', response_model=Reply)
async def guest_chat(payload: GuestChatInput, request: Request,
                     identity: Annotated[Identity | None, Depends(optional_auth)]):
    return await request.app.state.chat.reply(payload, request.state.request_id, identity)
