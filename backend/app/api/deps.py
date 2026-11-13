from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.models.identity import Role, User
from app.services.auth import Identity, authenticate


def optional_auth(request: Request, db: Annotated[Session, Depends(get_session)]) -> Identity | None:
    headers = request.headers.getlist("authorization")
    if not headers:
        return None
    if len(headers) != 1:
        raise HTTPException(401)
    parts = headers[0].split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(401)
    return authenticate(db, request.app.state.settings, parts[1])


def required_auth(identity: Annotated[Identity | None, Depends(optional_auth)]) -> Identity:
    if identity is None:
        raise HTTPException(401)
    return identity


def require_admin(identity: Annotated[Identity, Depends(required_auth)]) -> Identity:
    if identity.user.role != Role.ADMIN:
        raise HTTPException(403)
    return identity


def require_owner(user: User, owner_id: str | None) -> None:
    if not owner_id or user.id != owner_id:
        raise HTTPException(404)
