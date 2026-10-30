import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id() -> str:
    return str(uuid.uuid4())


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(254), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    color: Mapped[str] = mapped_column(String(20), default="teal")


class Membership(Base):
    __tablename__ = "memberships"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (CheckConstraint("role IN ('employee','approver','admin','auditor')"),)


class Expense(Base):
    __tablename__ = "expenses"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    owner_id: Mapped[str] = mapped_column(String(36))
    approver_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    title: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(30))
    amount_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="draft")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    __table_args__ = (
        UniqueConstraint("org_id", "id"),
        ForeignKeyConstraint(["org_id", "owner_id"], ["memberships.org_id", "memberships.user_id"]),
        ForeignKeyConstraint(["org_id", "approver_id"], ["memberships.org_id", "memberships.user_id"]),
        CheckConstraint("amount_cents > 0 AND amount_cents <= 100000000"),
        CheckConstraint("status IN ('draft','submitted','approved','rejected')"),
        CheckConstraint("approver_id IS NULL OR approver_id <> owner_id"),
        CheckConstraint("currency = 'USD'"),
        Index("ix_expense_org_status", "org_id", "status"),
    )


class Receipt(Base):
    __tablename__ = "receipts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(String(36), index=True)
    expense_id: Mapped[str] = mapped_column(String(36))
    filename: Mapped[str] = mapped_column(String(160))
    mime_type: Mapped[str] = mapped_column(String(80))
    content: Mapped[bytes] = mapped_column(LargeBinary)
    __table_args__ = (
        ForeignKeyConstraint(["org_id", "expense_id"], ["expenses.org_id", "expenses.id"]),
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    actor_id: Mapped[str] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(80))
    object_id: Mapped[str] = mapped_column(String(36))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class WebSession(Base):
    __tablename__ = "web_sessions"
    id_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36))
    encrypted_access_token: Mapped[str] = mapped_column(Text)
    encrypted_id_token: Mapped[str] = mapped_column(Text)
    csrf_token: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Invitation(Base):
    __tablename__ = "invitations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    email: Mapped[str] = mapped_column(String(254))
    role: Mapped[str] = mapped_column(String(20))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (CheckConstraint("role IN ('employee','approver','admin','auditor')"),)
