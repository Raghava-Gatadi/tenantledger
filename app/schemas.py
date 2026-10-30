from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Role = Literal["employee", "approver", "admin", "auditor"]
Category = Literal["Travel", "Meals", "Software", "Office", "Other"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ExpenseCreate(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    category: Category
    amount_cents: int = Field(gt=0, le=100_000_000, strict=True)
    note: str = Field(default="", max_length=2000)


class ExpenseEdit(ExpenseCreate):
    version: int = Field(gt=0)


class Submission(StrictModel):
    approver_id: str = Field(min_length=36, max_length=36)
    version: int = Field(gt=0)


class Decision(StrictModel):
    decision: Literal["approved", "rejected"]
    version: int = Field(gt=0)
    reason: str = Field(default="", max_length=500)


class MemberEdit(StrictModel):
    role: Role
    active: bool


class InviteCreate(StrictModel):
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    role: Role


class InviteAccept(StrictModel):
    token: str = Field(min_length=32, max_length=100)


class Assignment(StrictModel):
    approver_id: str = Field(min_length=36, max_length=36)
    version: int = Field(gt=0)
