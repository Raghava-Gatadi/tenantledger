"""Idempotent synthetic demo data. Run with the migration database role."""
import base64
from datetime import timedelta

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Account, AuditEvent, Expense, Membership, Organization, Receipt, now

ORG_A = "20000000-0000-0000-0000-000000000001"
ORG_B = "20000000-0000-0000-0000-000000000002"
USERS = [
    ("alice", "Alice Chen"), ("bob", "Bob Rivera"), ("carol", "Carol Brooks"),
    ("diana", "Diana Patel"), ("alex", "Alex Morgan"), ("eve", "Eve Walker"),
    ("frank", "Frank Lee"), ("grace", "Grace Kim"), ("heidi", "Heidi Nguyen"),
]
IDS = {name: f"10000000-0000-0000-0000-{i:012d}" for i, (name, _) in enumerate(USERS, 1)}


def seed(db):
    if db.scalar(select(Organization.id).limit(1)):
        return
    db.add_all([Organization(id=ORG_A, name="Northstar Studio", color="teal"),
                Organization(id=ORG_B, name="Juniper Labs", color="purple")])
    for name, full_name in USERS:
        db.add(Account(id=IDS[name], name=full_name, email=name + "@example.test", active=True))
    db.flush()
    roles = [(ORG_A, "alice", "employee"), (ORG_A, "bob", "approver"), (ORG_A, "carol", "admin"),
             (ORG_A, "diana", "auditor"), (ORG_A, "alex", "employee"),
             (ORG_B, "alex", "admin"), (ORG_B, "eve", "employee"),
             (ORG_B, "frank", "approver"), (ORG_B, "grace", "auditor")]
    for org, user, role in roles:
        db.add(Membership(org_id=org, user_id=IDS[user], role=role, active=True))
    db.flush()
    data = [
        (ORG_A, "alice", "Client workshop · train tickets", "Travel", 12850, "draft", None),
        (ORG_A, "alice", "Design team lunch", "Meals", 8640, "submitted", "bob"),
        (ORG_A, "alice", "Figma team subscription", "Software", 4500, "approved", "bob"),
        (ORG_A, "alice", "Home office supplies", "Office", 7299, "draft", None),
        (ORG_A, "alice", "Conference registration", "Other", 34900, "rejected", "bob"),
        (ORG_A, "alex", "Prototype materials", "Office", 21200, "submitted", "bob"),
        (ORG_A, "bob", "Project planning lunch", "Meals", 5800, "draft", None),
        (ORG_B, "eve", "Research lab equipment", "Office", 68500, "submitted", "frank"),
        (ORG_B, "eve", "Customer visit airfare", "Travel", 42180, "draft", None),
    ]
    for i, (org, owner, title, category, amount, status, approver) in enumerate(data, 1):
        expense = Expense(id=f"30000000-0000-0000-0000-{i:012d}", org_id=org, owner_id=IDS[owner],
                          title=title, category=category, amount_cents=amount, status=status,
                          approver_id=IDS[approver] if approver else None, note="Synthetic portfolio demonstration data.",
                          created_at=now() - timedelta(days=i), updated_at=now() - timedelta(days=i), version=1)
        db.add(expense)
        db.flush()
        db.add(AuditEvent(org_id=org, actor_id=IDS[owner], action="demo.seeded", object_id=expense.id,
                          detail={"synthetic": True}, created_at=expense.created_at))
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aN1cAAAAASUVORK5CYII=")
    db.add(Receipt(id="40000000-0000-0000-0000-000000000001", org_id=ORG_A,
                   expense_id="30000000-0000-0000-0000-000000000002", filename="demo-receipt.png",
                   mime_type="image/png", content=png))


if __name__ == "__main__":
    with SessionLocal.begin() as db:
        seed(db)
    print("Demo data is ready.")
