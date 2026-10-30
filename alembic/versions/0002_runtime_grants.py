"""Restrict the runtime role to operations used by application routes.

Revision ID: 0002
"""
from alembic import op

revision = "0002"
down_revision = "0001"

TABLES = "accounts, organizations, memberships, expenses, receipts, web_sessions, invitations"


def upgrade():
    op.execute(f"REVOKE ALL ON {TABLES} FROM ledger_app")
    op.execute("GRANT SELECT ON organizations TO ledger_app")
    op.execute("GRANT SELECT, INSERT ON accounts, receipts TO ledger_app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON memberships, expenses, invitations TO ledger_app")
    op.execute("GRANT SELECT, INSERT, DELETE ON web_sessions TO ledger_app")


def downgrade():
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {TABLES} TO ledger_app")
