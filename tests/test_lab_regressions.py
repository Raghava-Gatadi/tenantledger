"""The same security assertions run against secure and deliberately vulnerable sources."""
from app.models import Membership
from app.seed import IDS, ORG_A, ORG_B

A = f"/api/orgs/{ORG_A}"
B = f"/api/orgs/{ORG_B}"


def test_lab_tenant_boundary(as_user):
    assert as_user("alice").get(B + "/expenses/30000000-0000-0000-0000-000000000008").status_code == 404


def test_lab_object_ownership(as_user):
    assert as_user("alex").get(A + "/expenses/30000000-0000-0000-0000-000000000001").status_code == 404


def test_lab_protected_property(as_user):
    response = as_user("alice").post(A + "/expenses", json={
        "title": "Forged approval", "category": "Other", "amount_cents": 500, "status": "approved",
    })
    assert response.status_code == 422


def test_lab_admin_action(as_user, owner):
    response = as_user("alice").patch(A + f"/members/{IDS['alice']}", json={"role": "admin", "active": True})
    assert response.status_code == 403
    owner.expire_all()
    assert owner.get(Membership, (ORG_A, IDS["alice"])).role == "employee"


def test_lab_stale_membership(as_user, owner):
    client = as_user("alice")
    assert client.get(A + "/expenses").status_code == 200
    member = owner.get(Membership, (ORG_A, IDS["alice"]))
    member.active = False
    owner.commit()
    assert client.get(A + "/expenses").status_code == 404
