from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.main import app
from app.models import AuditEvent, Expense, Membership
from app.seed import IDS, ORG_A, ORG_B

A = f"/api/orgs/{ORG_A}"
B = f"/api/orgs/{ORG_B}"
DRAFT = "30000000-0000-0000-0000-000000000001"
PENDING = "30000000-0000-0000-0000-000000000002"
ALEX_PENDING = "30000000-0000-0000-0000-000000000006"
OTHER = "30000000-0000-0000-0000-000000000008"
RECEIPT = "40000000-0000-0000-0000-000000000001"
CREATE = {"title": "Rail fare", "category": "Travel", "amount_cents": 2500, "note": "Workshop"}


def test_complete_expense_workflow(as_user, owner):
    client = as_user("alice")
    response = client.post(A + "/expenses", json=CREATE)
    assert response.status_code == 201
    expense = response.json()
    assert expense["owner_id"] == IDS["alice"] and expense["org_id"] == ORG_A
    receipt = client.post(A + f"/expenses/{expense['id']}/receipts", files={"file": ("rail.pdf", b"%PDF-1.4\nsynthetic", "application/pdf")})
    assert receipt.status_code == 201
    edited = client.patch(A + f"/expenses/{expense['id']}", json={**CREATE, "amount_cents": 2800, "version": 1})
    assert edited.status_code == 200 and edited.json()["version"] == 2
    submitted = client.post(A + f"/expenses/{expense['id']}/submit", json={"version": 2, "approver_id": IDS["bob"]})
    assert submitted.status_code == 200 and submitted.json()["status"] == "submitted"
    as_user("bob")
    approved = client.post(A + f"/expenses/{expense['id']}/decision", json={"version": 3, "decision": "approved"})
    assert approved.status_code == 200 and approved.json()["version"] == 4
    as_user("diana")
    assert client.get(A + f"/expenses/{expense['id']}").json()["status"] == "approved"
    actions = {event["action"] for event in client.get(A + "/audit").json()}
    assert {"expense.created", "receipt.uploaded", "expense.edited", "expense.submitted", "expense.approved"} <= actions


@pytest.mark.parametrize("suffix", ["/expenses", f"/expenses/{OTHER}", "/summary", "/expenses/export", "/members", "/audit", "/approvers", "/assignments"])
def test_cross_tenant_endpoints_are_hidden(as_user, suffix):
    assert as_user("alice").get(B + suffix).status_code == 404


@pytest.mark.parametrize("username", ["alice", "bob", "carol", "diana", "alex"])
def test_foreign_id_cannot_be_smuggled_into_authorized_org(as_user, username):
    client = as_user(username)
    assert client.get(A + f"/expenses/{OTHER}").status_code == 404


def test_cross_tenant_write_has_no_side_effect(as_user, owner):
    original = owner.get(Expense, OTHER).amount_cents
    before = owner.scalar(select(func.count()).select_from(AuditEvent))
    response = as_user("alice").patch(A + f"/expenses/{OTHER}", json={**CREATE, "version": 1})
    assert response.status_code == 404
    owner.expire_all()
    assert owner.get(Expense, OTHER).amount_cents == original
    assert owner.scalar(select(func.count()).select_from(AuditEvent)) == before


def test_same_tenant_ownership_and_list_export_consistency(as_user):
    client = as_user("alex")
    assert client.get(A + f"/expenses/{DRAFT}").status_code == 404
    assert client.patch(A + f"/expenses/{DRAFT}", json={**CREATE, "version": 1}).status_code == 404
    listing = client.get(A + "/expenses").json()
    assert {e["id"] for e in listing["items"]} == {ALEX_PENDING}
    export = client.get(A + "/expenses/export").text
    assert ALEX_PENDING in export and DRAFT not in export and OTHER not in export
    assert client.get(A + "/summary").json()["submitted"]["count"] == 1


def test_membership_roles_are_not_global(as_user):
    client = as_user("alex")
    assert client.get(B + "/members").status_code == 200
    assert client.get(A + "/members").status_code == 403
    assert client.post(A + "/invitations", json={"email": "heidi@example.test", "role": "admin"}).status_code == 403
    assert len(client.get("/api/me").json()["organizations"]) == 2


@pytest.mark.parametrize("role", ["alice", "bob", "diana"])
def test_administrative_escalation_is_denied(as_user, owner, role):
    response = as_user(role).patch(A + f"/members/{IDS[role]}", json={"role": "admin", "active": True})
    assert response.status_code == 403
    assert owner.get(Membership, (ORG_A, IDS[role])).role != "admin"


@pytest.mark.parametrize("field,value", [("org_id", ORG_B), ("owner_id", IDS["bob"]), ("status", "approved"), ("approver_id", IDS["alice"]), ("currency", "EUR")])
def test_mass_assignment_rejected(as_user, owner, field, value):
    client = as_user("alice")
    before = owner.scalar(select(func.count()).select_from(Expense))
    assert client.post(A + "/expenses", json={**CREATE, field: value}).status_code == 422
    assert client.patch(A + f"/expenses/{DRAFT}", json={**CREATE, "version": 1, field: value}).status_code == 422
    owner.expire_all()
    assert owner.get(Expense, DRAFT).status == "draft"
    assert owner.scalar(select(func.count()).select_from(Expense)) == before


def test_admin_has_no_implicit_approval_or_content_access(as_user):
    client = as_user("carol")
    assert client.get(A + f"/expenses/{PENDING}").status_code == 404
    assert client.post(A + f"/expenses/{PENDING}/decision", json={"decision": "approved", "version": 1}).status_code == 403
    assert client.post(A + "/expenses", json=CREATE).status_code == 403
    assert client.get(A + "/assignments").status_code == 200


def test_approver_cannot_read_others_drafts_or_approve_own(as_user):
    client = as_user("bob")
    assert client.get(A + f"/expenses/{DRAFT}").status_code == 404
    own = "30000000-0000-0000-0000-000000000007"
    assert client.post(A + f"/expenses/{own}/submit", json={"approver_id": IDS["bob"], "version": 1}).status_code == 403
    assert client.post(A + f"/expenses/{own}/decision", json={"decision": "approved", "version": 1}).status_code == 403


def test_only_assigned_approver_can_decide(as_user, owner):
    owner.add(Membership(org_id=ORG_A, user_id=IDS["frank"], role="approver", active=True))
    owner.commit()
    client = as_user("frank")
    assert client.get(A + f"/expenses/{PENDING}").status_code == 404
    assert client.post(A + f"/expenses/{PENDING}/decision", json={"decision": "approved", "version": 1}).status_code == 404


def test_submitted_expenses_are_immutable(as_user, owner):
    client = as_user("alice")
    assert client.patch(A + f"/expenses/{PENDING}", json={**CREATE, "version": 1}).status_code == 409
    assert client.post(A + f"/expenses/{PENDING}/receipts", files={"file": ("x.pdf", b"%PDF-1.4", "application/pdf")}).status_code == 409
    owner.expire_all()
    assert owner.get(Expense, PENDING).amount_cents == 8640


def test_invalid_approver_from_other_org_is_rejected(as_user):
    assert as_user("alice").post(A + f"/expenses/{DRAFT}/submit", json={"approver_id": IDS["frank"], "version": 1}).status_code == 422


def test_receipt_inherits_parent_authorization(as_user):
    path = A + f"/expenses/{PENDING}/receipts/{RECEIPT}"
    assert as_user("alice").get(path).status_code == 200
    assert as_user("bob").get(path).status_code == 200
    assert as_user("alex").get(path).status_code == 404
    assert as_user("eve").get(path).status_code == 404
    assert as_user("alice").get(A + f"/expenses/{DRAFT}/receipts/{RECEIPT}").status_code == 404


def test_rejection_reason_and_optimistic_version(as_user):
    client = as_user("bob")
    assert client.post(A + f"/expenses/{PENDING}/decision", json={"decision": "rejected", "version": 1}).status_code == 422
    assert client.post(A + f"/expenses/{PENDING}/decision", json={"decision": "rejected", "version": 99, "reason": "Duplicate"}).status_code == 409
    assert client.post(A + f"/expenses/{PENDING}/decision", json={"decision": "rejected", "version": 1, "reason": "Duplicate"}).status_code == 200
    assert client.post(A + f"/expenses/{PENDING}/decision", json={"decision": "approved", "version": 2}).status_code == 409


def test_concurrent_decisions_commit_once(as_user, owner):
    as_user("bob")
    def request(decision):
        with TestClient(app) as c:
            return c.post(A + f"/expenses/{PENDING}/decision", json={"decision": decision, "version": 1, "reason": "Checked"}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(request, ["approved", "rejected"]))
    assert sorted(results) == [200, 409]
    assert owner.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action.in_(["expense.approved", "expense.rejected"]))) == 1


def test_removal_and_demotion_take_effect_next_request(as_user):
    client = as_user("bob")
    assert client.get(A + f"/expenses/{PENDING}").status_code == 200
    as_user("carol")
    assert client.patch(A + f"/members/{IDS['bob']}", json={"role": "employee", "active": True}).status_code == 200
    as_user("bob")
    assert client.post(A + f"/expenses/{PENDING}/decision", json={"decision": "approved", "version": 1}).status_code == 403
    as_user("carol")
    client.patch(A + f"/members/{IDS['bob']}", json={"role": "employee", "active": False})
    as_user("bob")
    assert client.get(A + "/expenses").status_code == 404


def test_last_admin_cannot_be_removed(as_user):
    assert as_user("carol").patch(A + f"/members/{IDS['carol']}", json={"role": "employee", "active": False}).status_code == 409


def test_admin_reassignment(as_user, owner):
    owner.add(Membership(org_id=ORG_A, user_id=IDS["frank"], role="approver", active=True))
    owner.commit()
    client = as_user("carol")
    result = client.post(A + f"/expenses/{PENDING}/assignment", json={"approver_id": IDS["frank"], "version": 1})
    assert result.status_code == 200 and "title" not in result.json()
    assert as_user("bob").get(A + f"/expenses/{PENDING}").status_code == 404
    assert as_user("frank").get(A + f"/expenses/{PENDING}").status_code == 200
