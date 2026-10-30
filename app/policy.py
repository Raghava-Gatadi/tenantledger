from dataclasses import dataclass

from fastapi import Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth import Principal, principal
from app.db import get_db, set_tenant
from app.models import AuditEvent, Expense, Membership


@dataclass(frozen=True)
class Tenant:
    org_id: str
    user: Principal
    role: str


def tenant(org_id: str, user: Principal = Depends(principal), db: Session = Depends(get_db)) -> Tenant:
    membership = db.get(Membership, (org_id, user.user_id))
    if not membership or not membership.active:
        raise HTTPException(404, "Organization not found")
    set_tenant(db, org_id)
    return Tenant(org_id, user, membership.role)


def require_role(ctx: Tenant, *roles: str):
    if ctx.role not in roles:
        raise HTTPException(403, "Your organization role does not allow this action")


def visible_expenses(ctx: Tenant):
    statement = select(Expense).where(Expense.org_id == ctx.org_id)
    if ctx.role == "auditor":
        return statement
    if ctx.role == "approver":
        return statement.where(or_(Expense.owner_id == ctx.user.user_id,
                                   (Expense.approver_id == ctx.user.user_id) & (Expense.status != "draft")))
    return statement.where(Expense.owner_id == ctx.user.user_id)


def expense_for(db: Session, ctx: Tenant, expense_id: str, *, lock=False) -> Expense:
    statement = visible_expenses(ctx).where(Expense.id == expense_id)
    if lock:
        statement = statement.with_for_update()
    expense = db.scalar(statement)
    if not expense:
        raise HTTPException(404, "Expense not found")
    return expense


def own_draft(ctx: Tenant, expense: Expense):
    require_role(ctx, "employee", "approver")
    if expense.owner_id != ctx.user.user_id:
        raise HTTPException(403, "Only the owner can change this expense")
    if expense.status != "draft":
        raise HTTPException(409, "Only draft expenses can be changed")


def audit(db: Session, ctx: Tenant, action: str, object_id: str, **detail):
    db.add(AuditEvent(org_id=ctx.org_id, actor_id=ctx.user.user_id,
                      action=action, object_id=object_id, detail=detail))
