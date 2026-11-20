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
    implement_days: float | Literal[""] = Field(default="")

class UserDraft(BaseModel):
    profile_id: str = ""
    period_months: float = Field(default=12, ge=0.1, le=120)
    requirements: list[str] = Field(default_factory=list)
    candidates: list[str] = Field(default_factory=list)
    prices: dict[str, DraftPrice] = Field(default_factory=dict)
    algorithm: str = ""
    mode: Literal["min_cost", "max_coverage"] = "min_cost"
    budget: str = "500000"


class AdminProfileUpdate(BaseModel):
    login: str = Field(min_length=3, max_length=64, pattern=r"^\S(?:.*\S)?$")
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str | None = Field(default=None, min_length=8, max_length=128)


class AdminPasswordConfirmation(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)


class AdminUserUpdate(AdminPasswordConfirmation):
    role: Literal["admin", "user"]
    new_password: str | None = Field(default=None, min_length=8, max_length=128)


class AuthUser(BaseModel):
    id: int
    login: str
    role: Literal["admin", "user"]
