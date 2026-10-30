from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

engine = create_engine(settings().database_url, pool_pre_ping=True, pool_size=5, max_overflow=5)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_db():
    with SessionLocal() as session:
        with session.begin():
            yield session


def set_tenant(db: Session, org_id: str):
    # Transaction-local: connection pooling cannot carry a tenant into the next transaction.
    db.execute(text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": org_id})
