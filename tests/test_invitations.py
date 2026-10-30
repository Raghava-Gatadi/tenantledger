from datetime import timedelta

from sqlalchemy import select

from app.models import Invitation, Membership, now
from app.seed import IDS, ORG_A

A = f"/api/orgs/{ORG_A}"


def invitation(as_user, email="heidi@example.test"):
    response = as_user("carol").post(A + "/invitations", json={"email": email, "role": "employee"})
    assert response.status_code == 201
    return response.json()["token"]


def test_invite_is_email_bound_and_single_use(as_user, owner):
    token = invitation(as_user)
    assert owner.scalar(select(Invitation)).token_hash != token
    assert as_user("eve").post("/api/invitations/accept", json={"token": token}).status_code == 404
    client = as_user("heidi")
    assert client.post("/api/invitations/accept", json={"token": token}).status_code == 200
    assert client.get(A + "/expenses").status_code == 200
    assert client.post("/api/invitations/accept", json={"token": token}).status_code == 404


def test_expired_invite_is_rejected(as_user, owner):
    token = invitation(as_user)
    row = owner.scalar(select(Invitation))
    row.expires_at = now() - timedelta(seconds=1)
    owner.commit()
    assert as_user("heidi").post("/api/invitations/accept", json={"token": token}).status_code == 404
    assert owner.get(Membership, (ORG_A, IDS["heidi"])) is None


def test_invite_cannot_reactivate_removed_member(as_user, owner):
    token = invitation(as_user, "alice@example.test")
    member = owner.get(Membership, (ORG_A, IDS["alice"]))
    member.active = False
    owner.commit()
    assert as_user("alice").post("/api/invitations/accept", json={"token": token}).status_code == 409
    owner.refresh(member)
    assert not member.active
