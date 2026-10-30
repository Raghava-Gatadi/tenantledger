import csv
import io
import json
import logging
import re
import secrets
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app import auth
from app.auth import Principal, digest, principal
from app.config import settings
from app.db import SessionLocal, get_db, set_tenant
from app.models import Account, AuditEvent, Expense, Invitation, Membership, Organization, Receipt, now
from app.policy import Tenant, audit, expense_for, own_draft, require_role, tenant, visible_expenses
from app.schemas import (
    Assignment,
    Decision,
    ExpenseCreate,
    ExpenseEdit,
    InviteAccept,
    InviteCreate,
    MemberEdit,
    Submission,
)

logger = logging.getLogger("tenantledger.security")
STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app):
    with SessionLocal() as db:
        bypass = db.execute(text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")).scalar()
        owns = db.execute(text("SELECT count(*) FROM pg_tables WHERE tablename IN ('expenses','receipts','audit_events') AND tableowner = current_user")).scalar()
        if bypass or owns:
            raise RuntimeError("API must use the non-owner ledger_app role without BYPASSRLS")
    yield


app = FastAPI(title="TenantLedger", version="1.0.0", lifespan=lifespan, docs_url=None, redoc_url=None,
              description="Expense approvals with organization-scoped authorization. Use an access token via the Authorization header or sign in through /auth/login.")


class BodyLimit:
    """Bound incoming request bodies before multipart parsing or JSON decoding."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in ("POST", "PUT", "PATCH"):
            return await self.app(scope, receive, send)
        limit = settings().max_receipt_bytes + 65536 if scope["path"].endswith("/receipts") else 32768
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > limit:
                return await JSONResponse({"detail": "Request is too large"}, status_code=413)(scope, receive, send)
            if not message.get("more_body", False):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()
        await self.app(scope, replay, send)


app.add_middleware(BodyLimit)


@app.middleware("http")
async def response_security(request: Request, call_next):
    request_id = str(uuid4())
    response = await call_next(request)
    response.headers.update({
        "X-Request-ID": request_id, "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY", "Cache-Control": "no-store",
        "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    })
    if settings().cookie_secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    if response.status_code in (401, 403, 404):
        logger.warning(json.dumps({"event": "access_denied", "request_id": request_id,
                                   "method": request.method, "path": request.url.path,
                                   "status": response.status_code}))
    return response


app.include_router(auth.router)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(STATIC / "index.html")


@app.get("/docs", include_in_schema=False)
def api_docs():
    return FileResponse(STATIC / "api-docs.html")


@app.get("/health", tags=["operations"])
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "service": "tenantledger"}


@app.get("/api/me", tags=["identity"])
def me(user: Principal = Depends(principal), db: Session = Depends(get_db)):
    memberships = db.execute(select(Organization, Membership).join(Membership).where(
        Membership.user_id == user.user_id, Membership.active.is_(True),
    )).all()
    return {"id": user.user_id, "name": user.name, "email": user.email,
            "csrf_token": user.web_session.csrf_token if user.web_session else None,
            "organizations": [{"id": org.id, "name": org.name, "color": org.color, "role": member.role}
                              for org, member in memberships]}


def expense_json(expense: Expense, db: Session) -> dict:
    owner = db.get(Account, expense.owner_id)
    approver = db.get(Account, expense.approver_id) if expense.approver_id else None
    return {"id": expense.id, "org_id": expense.org_id, "owner_id": expense.owner_id,
            "owner_name": owner.name, "approver_id": expense.approver_id,
            "approver_name": approver.name if approver else None,
            "title": expense.title, "category": expense.category, "amount_cents": expense.amount_cents,
            "currency": expense.currency, "note": expense.note, "status": expense.status,
            "version": expense.version, "created_at": expense.created_at.isoformat(),
            "updated_at": expense.updated_at.isoformat()}


def check_version(expense: Expense, version: int):
    if expense.version != version:
        raise HTTPException(409, "This expense changed; reload before trying again")


def valid_approver(db: Session, ctx: Tenant, approver_id: str, owner_id: str):
    member = db.get(Membership, (ctx.org_id, approver_id))
    account = db.get(Account, approver_id)
    if not member or not member.active or member.role != "approver" or not account or not account.active:
        raise HTTPException(422, "Choose an active approver in this organization")
    if approver_id == owner_id:
        raise HTTPException(403, "You cannot approve your own expense")


@app.get("/api/orgs/{org_id}/expenses", tags=["expenses"])
def list_expenses(ctx: Tenant = Depends(tenant), db: Session = Depends(get_db),
                  status: str | None = None, q: str = Query("", max_length=120),
                  limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    statement = visible_expenses(ctx)
    if q:
        statement = statement.where(Expense.title.icontains(q, autoescape=True))
    if status:
        if status not in ("draft", "submitted", "approved", "rejected"):
            raise HTTPException(422, "Unknown expense status")
        statement = statement.where(Expense.status == status)
    total = db.scalar(select(func.count()).select_from(statement.subquery()))
    expenses = db.scalars(statement.order_by(Expense.created_at.desc(), Expense.id).offset(offset).limit(limit))
    return {"items": [expense_json(e, db) for e in expenses], "total": total, "limit": limit, "offset": offset}


@app.get("/api/orgs/{org_id}/summary", tags=["expenses"])
def summary(ctx: Tenant = Depends(tenant), db: Session = Depends(get_db)):
    visible = visible_expenses(ctx).subquery()
    rows = db.execute(select(visible.c.status, func.count(), func.sum(visible.c.amount_cents)).group_by(visible.c.status))
    result = {status: {"count": 0, "amount_cents": 0} for status in ("draft", "submitted", "approved", "rejected")}
    for status, count, amount in rows:
        result[status] = {"count": count, "amount_cents": amount}
    return result


@app.post("/api/orgs/{org_id}/expenses", status_code=201, tags=["expenses"])
def create_expense(body: ExpenseCreate, ctx: Tenant = Depends(tenant), db: Session = Depends(get_db)):
    require_role(ctx, "employee", "approver")
    expense = Expense(org_id=ctx.org_id, owner_id=ctx.user.user_id, **body.model_dump())
    db.add(expense)
    db.flush()
    audit(db, ctx, "expense.created", expense.id)
    return expense_json(expense, db)


@app.get("/api/orgs/{org_id}/expenses/export", tags=["expenses"])
def export(ctx: Tenant = Depends(tenant), db: Session = Depends(get_db)):
    expenses = db.scalars(visible_expenses(ctx).order_by(Expense.id).limit(1001)).all()
    if len(expenses) > 1000:
        raise HTTPException(422, "Export limit is 1,000 expenses")
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["id", "title", "amount_usd", "status", "category"])
    for e in expenses:
        # Prevent spreadsheet formula execution in user-controlled cells.
        title = "'" + e.title if e.title.startswith(("=", "+", "-", "@", "\t", "\r")) else e.title
        writer.writerow([e.id, title, f"{e.amount_cents / 100:.2f}", e.status, e.category])
    audit(db, ctx, "expenses.exported", ctx.org_id, count=len(expenses))
    return Response(stream.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="expenses.csv"'})


@app.get("/api/orgs/{org_id}/expenses/{expense_id}", tags=["expenses"])
def get_expense(expense_id: str, ctx: Tenant = Depends(tenant), db: Session = Depends(get_db)):
    result = expense_json(expense_for(db, ctx, expense_id), db)
    receipts = db.scalars(select(Receipt).where(Receipt.org_id == ctx.org_id, Receipt.expense_id == expense_id))
    result["receipts"] = [{"id": r.id, "filename": r.filename} for r in receipts]
    return result


@app.patch("/api/orgs/{org_id}/expenses/{expense_id}", tags=["expenses"])
def edit_expense(expense_id: str, body: ExpenseEdit, ctx: Tenant = Depends(tenant), db: Session = Depends(get_db)):
    expense = expense_for(db, ctx, expense_id, lock=True)
    own_draft(ctx, expense)
    check_version(expense, body.version)
    for field, value in body.model_dump(exclude={"version"}).items():
        setattr(expense, field, value)
    expense.version += 1
    audit(db, ctx, "expense.edited", expense.id)
    db.flush()
    return expense_json(expense, db)


@app.post("/api/orgs/{org_id}/expenses/{expense_id}/submit", tags=["expenses"])
def submit_expense(expense_id: str, body: Submission, ctx: Tenant = Depends(tenant), db: Session = Depends(get_db)):
    expense = expense_for(db, ctx, expense_id, lock=True)
    own_draft(ctx, expense)
    check_version(expense, body.version)
    valid_approver(db, ctx, body.approver_id, expense.owner_id)
    expense.approver_id, expense.status = body.approver_id, "submitted"
    expense.version += 1
    audit(db, ctx, "expense.submitted", expense.id, approver_id=body.approver_id)
    db.flush()
    return expense_json(expense, db)


@app.post("/api/orgs/{org_id}/expenses/{expense_id}/decision", tags=["expenses"])
def decide(expense_id: str, body: Decision, ctx: Tenant = Depends(tenant), db: Session = Depends(get_db)):
    require_role(ctx, "approver")
    expense = expense_for(db, ctx, expense_id, lock=True)
    if expense.owner_id == ctx.user.user_id or expense.approver_id != ctx.user.user_id:
        raise HTTPException(403, "Only the assigned approver may decide this expense")
    check_version(expense, body.version)
    if expense.status != "submitted":
        raise HTTPException(409, "Only submitted expenses can be decided")
    if body.decision == "rejected" and not body.reason.strip():
        raise HTTPException(422, "A rejection reason is required")
    expense.status = body.decision
    expense.version += 1
    audit(db, ctx, "expense." + body.decision, expense.id, reason=body.reason)
    db.flush()
    return expense_json(expense, db)


@app.post("/api/orgs/{org_id}/expenses/{expense_id}/assignment", tags=["administration"])
def assign(expense_id: str, body: Assignment, ctx: Tenant = Depends(tenant), db: Session = Depends(get_db)):
    require_role(ctx, "admin")
    expense = db.scalar(select(Expense).where(Expense.org_id == ctx.org_id, Expense.id == expense_id).with_for_update())
    if not expense:
        raise HTTPException(404, "Expense not found")
    check_version(expense, body.version)
    if expense.status != "submitted":
        raise HTTPException(409, "Only submitted expenses can be reassigned")
    valid_approver(db, ctx, body.approver_id, expense.owner_id)
    expense.approver_id = body.approver_id
    expense.version += 1
    audit(db, ctx, "expense.reassigned", expense.id, approver_id=body.approver_id)
    return {"id": expense.id, "approver_id": expense.approver_id, "version": expense.version}


@app.get("/api/orgs/{org_id}/assignments", tags=["administration"])
def assignments(ctx: Tenant = Depends(tenant), db: Session = Depends(get_db)):
    require_role(ctx, "admin")
    rows = db.scalars(select(Expense).where(Expense.org_id == ctx.org_id, Expense.status == "submitted").limit(100))
    return [{"id": e.id, "owner_id": e.owner_id, "approver_id": e.approver_id, "version": e.version} for e in rows]


@app.get("/api/orgs/{org_id}/approvers", tags=["expenses"])
def approvers(ctx: Tenant = Depends(tenant), db: Session = Depends(get_db)):
    rows = db.scalars(select(Account).join(Membership).where(
        Membership.org_id == ctx.org_id, Membership.active.is_(True), Membership.role == "approver",
        Account.active.is_(True), Account.id != ctx.user.user_id,
    ))
    return [{"id": a.id, "name": a.name} for a in rows]


@app.post("/api/orgs/{org_id}/expenses/{expense_id}/receipts", status_code=201, tags=["receipts"])
def upload_receipt(expense_id: str, file: UploadFile = File(),
                   ctx: Tenant = Depends(tenant), db: Session = Depends(get_db)):
    expense = expense_for(db, ctx, expense_id, lock=True)
    own_draft(ctx, expense)
    count = db.scalar(select(func.count()).select_from(Receipt).where(Receipt.org_id == ctx.org_id, Receipt.expense_id == expense_id))
    if count >= 5:
        raise HTTPException(422, "An expense may have at most five receipts")
    content = file.file.read(settings().max_receipt_bytes + 1)
    if len(content) > settings().max_receipt_bytes:
        raise HTTPException(413, "Receipt must be 2 MB or smaller")
    signatures = [(b"%PDF-", "application/pdf", ".pdf"), (b"\x89PNG\r\n\x1a\n", "image/png", ".png"), (b"\xff\xd8\xff", "image/jpeg", ".jpg")]
    match = next(((mime, ext) for signature, mime, ext in signatures if content.startswith(signature)), None)
    if not match:
        raise HTTPException(415, "Upload a PDF, PNG, or JPEG receipt")
    stem = re.sub(r"[^a-zA-Z0-9_-]", "_", Path(file.filename or "receipt").stem)[:100] or "receipt"
    receipt = Receipt(org_id=ctx.org_id, expense_id=expense.id, filename=stem + match[1], mime_type=match[0], content=content)
    db.add(receipt)
    db.flush()
    audit(db, ctx, "receipt.uploaded", receipt.id, expense_id=expense.id)
    return {"id": receipt.id, "filename": receipt.filename}


@app.get("/api/orgs/{org_id}/expenses/{expense_id}/receipts/{receipt_id}", tags=["receipts"])
def download_receipt(expense_id: str, receipt_id: str, ctx: Tenant = Depends(tenant), db: Session = Depends(get_db)):
    expense_for(db, ctx, expense_id)
    receipt = db.scalar(select(Receipt).where(Receipt.org_id == ctx.org_id, Receipt.expense_id == expense_id, Receipt.id == receipt_id))
    if not receipt:
        raise HTTPException(404, "Receipt not found")
    audit(db, ctx, "receipt.downloaded", receipt.id)
    return Response(receipt.content, media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{receipt.filename}"'})


@app.get("/api/orgs/{org_id}/members", tags=["administration"])
def members(ctx: Tenant = Depends(tenant), db: Session = Depends(get_db)):
    require_role(ctx, "admin", "auditor")
    rows = db.execute(select(Account, Membership).join(Membership).where(Membership.org_id == ctx.org_id).order_by(Account.name))
    return [{"id": a.id, "name": a.name, "email": a.email, "role": m.role, "active": m.active} for a, m in rows]


@app.patch("/api/orgs/{org_id}/members/{user_id}", tags=["administration"])
def edit_member(user_id: str, body: MemberEdit, ctx: Tenant = Depends(tenant), db: Session = Depends(get_db)):
    require_role(ctx, "admin")
    # Serialize administration without granting UPDATE on organization metadata.
    # Hash collisions merely serialize unrelated organizations; they cannot grant access.
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:org, 0))"), {"org": ctx.org_id})
    member = db.get(Membership, (ctx.org_id, user_id))
    if not member:
        raise HTTPException(404, "Member not found")
    if member.role == "admin" and member.active and (not body.active or body.role != "admin"):
        admins = db.scalar(select(func.count()).select_from(Membership).where(
            Membership.org_id == ctx.org_id, Membership.role == "admin", Membership.active.is_(True),
        ))
        if admins <= 1:
            raise HTTPException(409, "An organization must keep at least one active admin")
    previous = {"role": member.role, "active": member.active}
    member.role, member.active = body.role, body.active
    audit(db, ctx, "membership.changed", user_id, before=previous, after=body.model_dump())
    return {"id": user_id, **body.model_dump()}


@app.post("/api/orgs/{org_id}/invitations", status_code=201, tags=["administration"])
def invite(body: InviteCreate, ctx: Tenant = Depends(tenant), db: Session = Depends(get_db)):
    require_role(ctx, "admin")
    raw = secrets.token_urlsafe(32)
    invitation = Invitation(org_id=ctx.org_id, email=body.email.lower(), role=body.role,
                            token_hash=digest(raw), expires_at=now() + timedelta(hours=24))
    db.add(invitation)
    db.flush()
    audit(db, ctx, "invitation.created", invitation.id, role=body.role)
    return {"id": invitation.id, "token": raw, "expires_at": invitation.expires_at.isoformat()}


@app.post("/api/invitations/accept", tags=["administration"])
def accept_invite(body: InviteAccept, user: Principal = Depends(principal), db: Session = Depends(get_db)):
    invitation = db.scalar(select(Invitation).where(Invitation.token_hash == digest(body.token)).with_for_update())
    if not invitation or invitation.used or invitation.expires_at <= now() or invitation.email != user.email.lower():
        raise HTTPException(404, "Invitation not found or no longer valid")
    member = db.get(Membership, (invitation.org_id, user.user_id))
    if member:
        # An old invitation must not undo a later demotion or offboarding decision.
        raise HTTPException(409, "Membership already exists; ask an organization admin to update it")
    db.add(Membership(org_id=invitation.org_id, user_id=user.user_id, role=invitation.role, active=True))
    invitation.used = True
    set_tenant(db, invitation.org_id)
    audit(db, Tenant(invitation.org_id, user, invitation.role), "invitation.accepted", invitation.id)
    return {"org_id": invitation.org_id, "role": invitation.role}


@app.get("/api/orgs/{org_id}/audit", tags=["audit"])
def audit_log(ctx: Tenant = Depends(tenant), db: Session = Depends(get_db),
              limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    require_role(ctx, "admin", "auditor")
    rows = db.scalars(select(AuditEvent).where(AuditEvent.org_id == ctx.org_id)
                      .order_by(AuditEvent.created_at.desc(), AuditEvent.id).offset(offset).limit(limit))
    return [{"id": e.id, "actor_id": e.actor_id, "action": e.action, "object_id": e.object_id,
             "detail": e.detail, "created_at": e.created_at.isoformat()} for e in rows]
