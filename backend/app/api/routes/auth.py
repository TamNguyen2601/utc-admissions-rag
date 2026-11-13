from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import optional_auth, required_auth
from app.db.session import get_session
from app.schemas.auth import Credentials, LoginResponse, UserResponse, user_response
from app.services import auth

router = APIRouter(prefix="/auth", tags=["auth"])
DB = Annotated[Session, Depends(get_session)]
Authenticated = Annotated[auth.Identity, Depends(required_auth)]


@router.post("/register", status_code=201, response_model=UserResponse, dependencies=[Depends(optional_auth)])
def register(credentials: Credentials, db: DB):
    return user_response(auth.register(db, credentials))


@router.post("/login", response_model=LoginResponse, dependencies=[Depends(optional_auth)])
def login(credentials: Credentials, request: Request, db: DB):
    return auth.login(db, request.app.state.settings, credentials)


@router.get("/me", response_model=UserResponse)
def me(identity: Authenticated):
    return user_response(identity.user)


@router.post("/logout", status_code=204)
def logout(identity: Authenticated, db: DB):
    auth.logout(db, identity)
    return Response(status_code=204)
