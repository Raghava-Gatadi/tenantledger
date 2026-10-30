import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

# Tests must never reset the interactive demo database.
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://ledger_app:local-app-password@localhost:5433/ledger_test")

from app.auth import Principal, principal
from app.main import app
from app.models import Account
from app.seed import IDS, USERS, seed

OWNER_URL = os.environ.get("TEST_OWNER_URL", "postgresql+psycopg://ledger_owner:local-owner-password@localhost:5433/ledger_test")
if not OWNER_URL.split("?")[0].endswith("/ledger_test"):
    raise RuntimeError("Destructive test fixtures require a database named ledger_test")
if not os.environ["DATABASE_URL"].split("?")[0].endswith("/ledger_test"):
    raise RuntimeError("API test database must be named ledger_test")
owner_engine = create_engine(OWNER_URL)


@pytest.fixture(autouse=True)
def fresh_database():
    with owner_engine.begin() as connection:
        connection.execute(text("TRUNCATE receipts, audit_events, expenses, invitations, web_sessions, memberships, accounts, organizations CASCADE"))
    with Session(owner_engine) as db, db.begin():
        seed(db)
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def owner():
    with Session(owner_engine) as db:
        yield db


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client


@pytest.fixture
def as_user(client):
    def choose(username):
        full_name = dict(USERS)[username]
        app.dependency_overrides[principal] = lambda: Principal(IDS[username], full_name, username + "@example.test")
        return client
    return choose


@pytest.fixture
def account_claims():
    def claims(username="alice"):
        return {"sub": IDS[username], "email": username + "@example.test", "email_verified": True,
                "name": dict(USERS)[username]}
    return claims


@pytest.fixture
def disable_account(owner):
    def disable(username):
        owner.get(Account, IDS[username]).active = False
        owner.commit()
    return disable
