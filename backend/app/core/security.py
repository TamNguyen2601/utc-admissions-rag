"""Argon2id passwords and strictly validated, short-lived HS256 tokens."""

from datetime import datetime
from uuid import UUID

import jwt
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
from pwdlib.hashers.argon2 import Argon2Hasher

from app.core.config import Settings

password_hasher = PasswordHash((Argon2Hasher(),))


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    try:
        return password_hasher.verify(password, encoded)
    except (UnknownHashError, ValueError):
        return False


def create_token(settings: Settings, user_id: str, session_id: str,
                 issued_at: datetime, expires_at: datetime) -> str:
    return jwt.encode(
        {"sub": user_id, "sid": session_id, "iat": int(issued_at.timestamp()),
         "exp": int(expires_at.timestamp()), "iss": settings.jwt_issuer,
         "aud": settings.jwt_audience},
        settings.jwt_secret.get_secret_value(), algorithm="HS256",
    )


def decode_token(settings: Settings, token: str) -> dict:
    claims = jwt.decode(
        token, settings.jwt_secret.get_secret_value(), algorithms=["HS256"],
        issuer=settings.jwt_issuer, audience=settings.jwt_audience,
        options={"require": ["sub", "sid", "iat", "exp", "iss", "aud"], "strict_aud": True},
    )
    try:
        for name in ("sub", "sid"):
            if str(UUID(claims[name])) != claims[name]:
                raise ValueError
        if (type(claims["iat"]) is not int or type(claims["exp"]) is not int
                or claims["exp"] - claims["iat"] != settings.jwt_expire_minutes * 60):
            raise ValueError
    except (TypeError, ValueError, AttributeError):
        raise jwt.InvalidTokenError("Invalid identity claims") from None
    return claims
