import time
from datetime import timedelta
from types import SimpleNamespace

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from app.auth import TokenVerifier, cipher, digest, get_verifier
from app.config import settings
from app.main import app
from app.models import WebSession, now
from app.seed import IDS, ORG_A


@pytest.fixture
def signing():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def verifier(signing, monkeypatch):
    instance = TokenVerifier()
    monkeypatch.setattr(instance.keys, "get_signing_key_from_jwt", lambda token: SimpleNamespace(key=signing.public_key()))
    monkeypatch.setattr("app.auth.httpx.post", lambda *a, **kw: httpx.Response(
        200, json={"active": True, "sub": IDS["alice"]}, request=httpx.Request("POST", "http://test"),
    ))
    return instance


def claims(**overrides):
    return {"sub": IDS["alice"], "iss": settings().oidc_issuer, "aud": settings().oidc_audience,
            "exp": int(time.time()) + 60, "iat": int(time.time()), "typ": "Bearer", **overrides}


def test_valid_signed_token(verifier, signing):
    assert verifier.verify(jwt.encode(claims(), signing, algorithm="RS256"))["sub"] == IDS["alice"]


@pytest.mark.parametrize("override", [
    {"iss": "https://attacker.invalid/realm"}, {"aud": "another-api"},
    {"exp": int(time.time()) - 60}, {"nbf": int(time.time()) + 120},
    {"iat": int(time.time()) + 120}, {"typ": "ID"}, {"sub": 42},
])
def test_claim_validation(verifier, signing, override):
    with pytest.raises(HTTPException) as error:
        verifier.verify(jwt.encode(claims(**override), signing, algorithm="RS256"))
    assert error.value.status_code == 401


@pytest.mark.parametrize("missing", ["iss", "aud", "exp", "iat", "sub"])
def test_required_claims(verifier, signing, missing):
    payload = claims()
    del payload[missing]
    with pytest.raises(HTTPException) as error:
        verifier.verify(jwt.encode(payload, signing, algorithm="RS256"))
    assert error.value.status_code == 401


@pytest.mark.parametrize("algorithm", ["none", "HS256"])
def test_unsigned_and_algorithm_confusion_rejected(verifier, algorithm):
    token = jwt.encode(claims(), "" if algorithm == "none" else "attacker-secret-32-characters-long", algorithm=algorithm)
    with pytest.raises(HTTPException) as error:
        verifier.verify(token)
    assert error.value.status_code == 401


def test_wrong_signature_rejected(verifier):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(HTTPException) as error:
        verifier.verify(jwt.encode(claims(), other, algorithm="RS256"))
    assert error.value.status_code == 401


def test_revoked_session_and_idp_outage_fail_closed(verifier, signing, monkeypatch):
    token = jwt.encode(claims(), signing, algorithm="RS256")
    monkeypatch.setattr("app.auth.httpx.post", lambda *a, **kw: httpx.Response(200, json={"active": False}, request=httpx.Request("POST", "http://test")))
    with pytest.raises(HTTPException) as error:
        verifier.verify(token)
    assert error.value.status_code == 401
    def timeout(*a, **kw):
        raise httpx.ConnectTimeout("unavailable")
    monkeypatch.setattr("app.auth.httpx.post", timeout)
    with pytest.raises(HTTPException) as error:
        verifier.verify(token)
    assert error.value.status_code == 503


def test_unauthenticated_api_denied(client):
    assert client.get(f"/api/orgs/{ORG_A}/expenses").status_code == 401
    assert client.get("/api/me", headers={"Authorization": "Basic abc"}).status_code == 401


def test_disabled_local_account_denied(client, account_claims, disable_account):
    app.dependency_overrides[get_verifier] = lambda: SimpleNamespace(verify=lambda _: account_claims())
    headers = {"Authorization": "Bearer valid-test-token"}
    assert client.get("/api/me", headers=headers).status_code == 200
    disable_account("alice")
    assert client.get("/api/me", headers=headers).status_code == 401


def test_cookie_session_csrf_expiration_and_logout(client, owner, account_claims):
    app.dependency_overrides[get_verifier] = lambda: SimpleNamespace(verify=lambda _: account_claims())
    raw = "synthetic-opaque-session"
    session = WebSession(id_hash=digest(raw), user_id=IDS["alice"],
                         encrypted_access_token=cipher().encrypt(b"token").decode(),
                         encrypted_id_token=cipher().encrypt(b"id-token").decode(),
                         csrf_token="test-csrf", expires_at=now() + timedelta(minutes=5))
    owner.add(session)
    owner.commit()
    client.cookies.set("ledger_session", raw)
    assert client.get("/api/me").status_code == 200
    body = {"title": "Test", "amount_cents": 100, "category": "Other"}
    url = f"/api/orgs/{ORG_A}/expenses"
    assert client.post(url, json=body).status_code == 403
    assert client.post(url, json=body, headers={"Origin": "https://attacker.invalid", "X-CSRF-Token": "test-csrf"}).status_code == 403
    headers = {"Origin": settings().app_url, "X-CSRF-Token": "test-csrf"}
    assert client.post(url, json=body, headers=headers).status_code == 201
    session.expires_at = now() - timedelta(seconds=1)
    owner.commit()
    assert client.get("/api/me").status_code == 401
    assert client.post("/auth/logout", headers=headers).status_code == 200
    owner.expire_all()
    assert owner.get(WebSession, digest(raw)) is None
    assert client.get("/api/me").status_code == 401


def test_invalid_login_state_and_cookie_flags(client):
    response = client.get("/auth/login", follow_redirects=False)
    assert response.status_code == 307
    assert "code_challenge_method=S256" in response.headers["location"]
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/auth" in cookie
    assert client.get("/auth/callback?code=fake&state=wrong", follow_redirects=False).status_code == 400


def test_tampered_login_cookie(client):
    client.cookies.set("ledger_login", "tampered")
    assert client.get("/auth/callback?code=fake&state=fake").status_code == 400


def test_security_response_headers(client):
    response = client.get("/")
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
