"""Initial schema and tenant isolation policies.

Revision ID: 0001
"""
import sqlalchemy as sa

from alembic import op

revision = "0001"
down_revision = None


def upgrade():
    op.create_table("accounts", sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("name", sa.String(100), nullable=False),
                    sa.Column("email", sa.String(254), nullable=False, unique=True),
                    sa.Column("active", sa.Boolean, nullable=False))
    op.create_table("organizations", sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("name", sa.String(100), nullable=False),
                    sa.Column("color", sa.String(20), nullable=False))
    op.create_table("memberships",
                    sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), primary_key=True),
                    sa.Column("user_id", sa.String(36), sa.ForeignKey("accounts.id"), primary_key=True),
                    sa.Column("role", sa.String(20), nullable=False),
                    sa.Column("active", sa.Boolean, nullable=False),
                    sa.CheckConstraint("role IN ('employee','approver','admin','auditor')"))
    op.create_table("expenses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("approver_id", sa.String(36)),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("amount_cents", sa.Integer, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("note", sa.Text, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("org_id", "id"),
        sa.ForeignKeyConstraint(["org_id", "owner_id"], ["memberships.org_id", "memberships.user_id"]),
        sa.ForeignKeyConstraint(["org_id", "approver_id"], ["memberships.org_id", "memberships.user_id"]),
        sa.CheckConstraint("amount_cents > 0 AND amount_cents <= 100000000"),
        sa.CheckConstraint("status IN ('draft','submitted','approved','rejected')"),
        sa.CheckConstraint("approver_id IS NULL OR approver_id <> owner_id"),
        sa.CheckConstraint("currency = 'USD'"))
    op.create_index("ix_expenses_org_id", "expenses", ["org_id"])
    op.create_index("ix_expense_org_status", "expenses", ["org_id", "status"])
    op.create_table("receipts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("expense_id", sa.String(36), nullable=False),
        sa.Column("filename", sa.String(160), nullable=False),
        sa.Column("mime_type", sa.String(80), nullable=False),
        sa.Column("content", sa.LargeBinary, nullable=False),
        sa.ForeignKeyConstraint(["org_id", "expense_id"], ["expenses.org_id", "expenses.id"]))
    op.create_index("ix_receipts_org_id", "receipts", ["org_id"])
    op.create_table("audit_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("object_id", sa.String(36), nullable=False),
        sa.Column("detail", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_audit_events_org_id", "audit_events", ["org_id"])
    op.create_table("web_sessions",
        sa.Column("id_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("encrypted_access_token", sa.Text, nullable=False),
        sa.Column("encrypted_id_token", sa.Text, nullable=False),
        sa.Column("csrf_token", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_web_sessions_expires_at", "web_sessions", ["expires_at"])
    op.create_table("invitations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used", sa.Boolean, nullable=False),
        sa.CheckConstraint("role IN ('employee','approver','admin','auditor')"))
    op.create_index("ix_invitations_org_id", "invitations", ["org_id"])
    # Control-plane tables are explicitly scoped in the API. Business records use RLS too.
    op.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA public TO ledger_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON accounts, organizations, memberships, expenses, receipts, web_sessions, invitations TO ledger_app")
    op.execute("GRANT SELECT, INSERT ON audit_events TO ledger_app")
    for table in ("expenses", "receipts", "audit_events"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING (org_id = current_setting('app.tenant_id', true)) WITH CHECK (org_id = current_setting('app.tenant_id', true))")


def downgrade():
    for table in ("invitations", "web_sessions", "audit_events", "receipts", "expenses", "memberships", "organizations", "accounts"):
        op.drop_table(table)
