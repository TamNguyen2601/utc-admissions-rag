import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.identity import Role


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    email: str = Field(max_length=320)
    password: str = Field(min_length=8, max_length=128, repr=False)

    @field_validator("email")
    @classmethod
    def normalized_email(cls, value: str) -> str:
        value = value.strip().lower()
        local, separator, domain = value.partition("@")
        labels = domain.split(".")
        if (not separator or len(value) > 254 or not 1 <= len(local) <= 64
                or not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+", local)
                or local.startswith(".") or local.endswith(".") or ".." in local
                or len(labels) < 2 or any(not re.fullmatch(
                    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels)):
            raise ValueError("Invalid email")
        return value


class UserResponse(BaseModel):
    id: str
    email: str
    role: Role


class LoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = 1800
    user: UserResponse


def user_response(user) -> UserResponse:
    return UserResponse(id=user.id, email=user.email_normalized, role=user.role)
