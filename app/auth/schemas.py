from typing import Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    login: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class RegisterRequest(BaseModel):
    login: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)


class DraftPrice(BaseModel):
    capex: float | Literal[""] = Field(default="")
    opex_month: float | Literal[""] = Field(default="")


class UserDraft(BaseModel):
    profile_id: str = ""
    period_months: float = Field(default=12, ge=0.1, le=120)
    requirements: list[str] = Field(default_factory=list)
    candidates: list[str] = Field(default_factory=list)
    prices: dict[str, DraftPrice] = Field(default_factory=dict)
    algorithm: str = ""
    mode: Literal["min_cost", "max_coverage"] = "min_cost"
    budget: str = "500000"


class AuthUser(BaseModel):
    id: int
    login: str
    role: Literal["admin", "user"]
