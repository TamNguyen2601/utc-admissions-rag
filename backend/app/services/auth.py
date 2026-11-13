from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache

import jwt
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import create_token, decode_token, hash_password, verify_password
from app.db.base import utc_now
from app.models.identity import AuthSession, Role, User
from app.schemas.auth import Credentials, LoginResponse, user_response


@dataclass(frozen=True)
class Identity:
    user: User
    session: AuthSession


@lru_cache(maxsize=1)
def dummy_hash() -> str:
    # Comparable password verification work for nonexistent users.
    import secrets
    return hash_password(secrets.token_urlsafe(32))


def register(db: Session, credentials: Credentials, *, role: Role = Role.USER) -> User:
    user = User(email_normalized=credentials.email,
                password_hash=hash_password(credentials.password), role=role)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409) from None
    return user


def login(db: Session, settings: Settings, credentials: Credentials) -> LoginResponse:
    user = db.scalar(select(User).where(User.email_normalized == credentials.email))
    valid = verify_password(credentials.password, user.password_hash if user else dummy_hash())
    if not valid or user is None or not user.active:
        raise InvalidCredentials()
    now = utc_now().replace(microsecond=0)
    session = AuthSession(user_id=user.id, created_at=now,
                          expires_at=now + timedelta(minutes=settings.jwt_expire_minutes))
    db.add(session)
    db.flush()
    token = create_token(settings, user.id, session.id, now, session.expires_at)
    db.commit()
    return LoginResponse(access_token=token, user=user_response(user))


class InvalidCredentials(HTTPException):
    def __init__(self):
        super().__init__(401)


def authenticate(db: Session, settings: Settings, token: str) -> Identity:
    try:
        claims = decode_token(settings, token)
    except jwt.InvalidTokenError:
        raise HTTPException(401) from None
    session = db.get(AuthSession, claims["sid"])
    now = utc_now()
    if (session is None or session.user_id != claims["sub"] or session.revoked_at is not None
            or session.expires_at <= now
            or int(session.expires_at.timestamp()) != claims["exp"]):
        raise HTTPException(401)
    user = db.get(User, session.user_id)
    if user is None or not user.active:
        raise HTTPException(401)
    return Identity(user=user, session=session)


def logout(db: Session, identity: Identity) -> None:
    identity.session.revoked_at = utc_now()
    db.commit()
