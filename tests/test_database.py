import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal, set_tenant
from app.models import AuditEvent, Expense, Receipt
from app.seed import ORG_A, ORG_B


@pytest.mark.parametrize("model", [Expense, Receipt, AuditEvent])
def test_rls_default_denies_unscoped_access(model):
    with SessionLocal.begin() as db:
        assert db.scalars(select(model)).all() == []


def test_rls_hides_other_tenant_even_without_api_filter():
    with SessionLocal.begin() as db:
        set_tenant(db, ORG_A)
        rows = db.scalars(select(Expense)).all()
        assert len(rows) == 7 and {e.org_id for e in rows} == {ORG_A}
        assert db.get(Expense, "30000000-0000-0000-0000-000000000008") is None


def test_rls_rejects_cross_tenant_insert():
    with pytest.raises(DBAPIError), SessionLocal.begin() as db:
        set_tenant(db, ORG_A)
        db.execute(text("INSERT INTO audit_events (id,org_id,actor_id,action,object_id,detail,created_at) VALUES ('x', :org, 'x','forged','x','{}',now())"), {"org": ORG_B})


def test_runtime_role_cannot_bypass_rls_or_edit_audit():
    with SessionLocal.begin() as db:
        assert db.execute(text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")).scalar() is False
    for sql in ("DELETE FROM audit_events", "UPDATE audit_events SET action='changed'", "ALTER TABLE expenses DISABLE ROW LEVEL SECURITY"):
        with pytest.raises(DBAPIError), SessionLocal.begin() as db:
            set_tenant(db, ORG_A)
            db.execute(text(sql))


def test_runtime_has_only_required_control_plane_and_business_grants():
    for sql in ("DELETE FROM expenses", "DELETE FROM memberships", "UPDATE accounts SET active=false",
                "UPDATE organizations SET name='forged'", "DELETE FROM receipts"):
        with pytest.raises(DBAPIError), SessionLocal.begin() as db:
            set_tenant(db, ORG_A)
            db.execute(text(sql))


def test_pool_reuse_does_not_leak_tenant_after_commit_or_rollback():
    engine = create_engine(settings().database_url, pool_size=1, max_overflow=0)
    try:
        with Session(engine) as db, db.begin():
            pid = db.execute(text("SELECT pg_backend_pid()")).scalar()
            set_tenant(db, ORG_A)
            assert len(db.scalars(select(Expense)).all()) == 7
        with Session(engine) as db, db.begin():
            assert db.execute(text("SELECT pg_backend_pid()")).scalar() == pid
            assert db.scalars(select(Expense)).all() == []
            set_tenant(db, ORG_B)
            assert {e.org_id for e in db.scalars(select(Expense))} == {ORG_B}
            db.rollback()
        with Session(engine) as db, db.begin():
            assert db.execute(text("SELECT pg_backend_pid()")).scalar() == pid
            assert db.scalars(select(Expense)).all() == []
    finally:
        engine.dispose()


def test_composite_foreign_key_rejects_wrong_org_owner(owner):
    with pytest.raises(DBAPIError):
        owner.execute(text("UPDATE expenses SET owner_id='10000000-0000-0000-0000-000000000006' WHERE id='30000000-0000-0000-0000-000000000001'"))
        owner.commit()
    owner.rollback()
