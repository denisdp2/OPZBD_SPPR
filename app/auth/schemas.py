from typing import Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    login: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class AuthUser(BaseModel):
    id: int
    login: str
    role: Literal["admin", "user"]
