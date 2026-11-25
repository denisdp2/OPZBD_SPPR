from typing import Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    login: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class RegisterRequest(BaseModel):
    login: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)


class DraftPrice(BaseModel):
    capex: Union[float, Literal['']] = Field(default="")
    opex_month: Union[float, Literal['']] = Field(default="")
    implement_days: Union[float, Literal['']] = Field(default="")



class UserDraft(BaseModel):
    profile_id: str = ""
    mandatory: Optional[List[str]] = None
    period_months: float = Field(default=12, ge=0.1, le=120)
    requirements: List[str] = Field(default_factory=list)
    candidates: List[str] = Field(default_factory=list)
    prices: Dict[str, DraftPrice] = Field(default_factory=dict)
    algorithm: str = ""
    mode: Literal["min_cost", "max_coverage", "compromise"] = "min_cost"
    budget: str = "500000"
    use_budget: bool = False


class AdminProfileUpdate(BaseModel):
    login: str = Field(min_length=3, max_length=64, pattern=r"^\S(?:.*\S)?$")
    current_password: str = Field(min_length=1, max_length=128)
    new_password: Optional[str] = Field(default=None, min_length=8, max_length=128)


class AdminPasswordConfirmation(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)


class AdminUserUpdate(AdminPasswordConfirmation):
    role: Literal['admin', 'user']
    new_password: Optional[str] = Field(default=None, min_length=8, max_length=128)


class AuthUser(BaseModel):
    id: int
    login: str
    role: Literal['admin', 'user']
