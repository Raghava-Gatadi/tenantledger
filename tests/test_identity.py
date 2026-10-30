"""Real Keycloak integration. The ledger-test client exists only in the local realm."""
import os
import time
import uuid

import httpx
import pytest

from app.auth import TokenVerifier
from app.config import settings
from app.seed import IDS, ORG_A

pytestmark = pytest.mark.identity
BASE = os.environ.get("KEYCLOAK_BASE_URL", "http://localhost:8080")
REALM = BASE + "/realms/tenantledger/protocol/openid-connect"


def token(username="alice"):
    result = httpx.post(REALM + "/token", data={
        "client_id": "ledger-test", "client_secret": "local-test-client-secret",
        "grant_type": "password", "username": username, "password": "LedgerDemo123!", "scope": "openid profile email",
    }, timeout=10)
    result.raise_for_status()
    return result.json()


def admin_headers():
    result = httpx.post(BASE + "/realms/master/protocol/openid-connect/token", data={
        "client_id": "admin-cli", "grant_type": "password", "username": "admin", "password": "local-admin-password",
    }, timeout=10)
    result.raise_for_status()
    return {"Authorization": "Bearer " + result.json()["access_token"]}


def test_real_token_and_tenant_boundary(client):
    tokens = token()
    headers = {"Authorization": "Bearer " + tokens["access_token"]}
    assert client.get("/api/me", headers=headers).status_code == 200
    assert client.get(f"/api/orgs/{ORG_A}/expenses", headers=headers).json()["total"] == 5
    assert client.get("/api/orgs/20000000-0000-0000-0000-000000000002/expenses", headers=headers).status_code == 404
    assert client.get("/api/me", headers={"Authorization": "Bearer " + tokens["id_token"]}).status_code == 401


def test_real_membership_revocation_with_unchanged_token(client):
    alice = {"Authorization": "Bearer " + token()["access_token"]}
    carol = {"Authorization": "Bearer " + token("carol")["access_token"]}
    url = f"/api/orgs/{ORG_A}/expenses"
    assert client.get(url, headers=alice).status_code == 200
    result = client.patch(f"/api/orgs/{ORG_A}/members/{IDS['alice']}", headers=carol,
                          json={"role": "employee", "active": False})
    assert result.status_code == 200
    assert client.get(url, headers=alice).status_code == 404
    assert client.get("/api/me", headers=alice).json()["organizations"] == []


def test_identity_provider_disable_rejects_existing_access_token(client):
    tokens = token("heidi")
    headers = {"Authorization": "Bearer " + tokens["access_token"]}
    assert client.get("/api/me", headers=headers).status_code == 200
    admin = admin_headers()
    url = BASE + f"/admin/realms/tenantledger/users/{IDS['heidi']}"
    try:
        httpx.put(url, headers=admin, json={"enabled": False}, timeout=10).raise_for_status()
        assert client.get("/api/me", headers=headers).status_code == 401
    finally:
        httpx.put(url, headers=admin, json={"enabled": True}, timeout=10).raise_for_status()


def test_provider_logout_invalidates_access_and_refresh(client):
    tokens = token("grace")
    headers = {"Authorization": "Bearer " + tokens["access_token"]}
    assert client.get("/api/me", headers=headers).status_code == 200
    httpx.post(BASE + f"/admin/realms/tenantledger/users/{IDS['grace']}/logout", headers=admin_headers(), timeout=10).raise_for_status()
    assert client.get("/api/me", headers=headers).status_code == 401
    refresh = httpx.post(REALM + "/token", data={"client_id": "ledger-test", "client_secret": "local-test-client-secret",
                                                "grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]}, timeout=10)
    assert refresh.status_code == 400


def test_deleted_identity_cannot_keep_using_old_token(client):
    admin = admin_headers()
    username = "lifecycle-" + uuid.uuid4().hex[:10]
    users_url = BASE + "/admin/realms/tenantledger/users"
    created = httpx.post(users_url, headers=admin, timeout=10, json={
        "username": username, "firstName": "Lifecycle", "lastName": "Test",
        "email": username + "@example.test", "emailVerified": True, "enabled": True,
        "credentials": [{"type": "password", "value": "LedgerDemo123!", "temporary": False}],
    })
    created.raise_for_status()
    user_url = created.headers["location"].replace("http://localhost:8080", BASE)
    try:
        credentials = token(username)
        headers = {"Authorization": "Bearer " + credentials["access_token"]}
        assert client.get("/api/me", headers=headers).status_code == 200
        httpx.delete(user_url, headers=admin, timeout=10).raise_for_status()
        assert client.get("/api/me", headers=headers).status_code == 401
    finally:
        removed = httpx.delete(user_url, headers=admin, timeout=10)
        assert removed.status_code in (204, 404)


def test_real_refresh_and_expired_token(client):
    # A short lifespan on a temporary local test client avoids changing the web client.
    admin = admin_headers()
    url = BASE + "/admin/realms/tenantledger/clients"
    config = {"clientId": "ledger-expiry-test", "enabled": True, "publicClient": False,
              "secret": "expiry-test-secret", "directAccessGrantsEnabled": True,
              "attributes": {"access.token.lifespan": "3"},
              "protocolMappers": [{"name": "aud", "protocol": "openid-connect", "protocolMapper": "oidc-audience-mapper",
                                    "config": {"included.custom.audience": settings().oidc_audience, "access.token.claim": "true"}}]}
    created = httpx.post(url, headers=admin, json=config, timeout=10)
    created.raise_for_status()
    client_url = created.headers["location"].replace("http://localhost:8080", BASE)
    try:
        data = {"client_id": "ledger-expiry-test", "client_secret": "expiry-test-secret", "grant_type": "password",
                "username": "frank", "password": "LedgerDemo123!", "scope": "openid profile email"}
        response = httpx.post(REALM + "/token", data=data, timeout=10)
        response.raise_for_status()
        tokens = response.json()
        headers = {"Authorization": "Bearer " + tokens["access_token"]}
        assert client.get("/api/me", headers=headers).status_code == 200
        time.sleep(6)  # Real provider expiry, including the API's two-second clock tolerance.
        assert client.get("/api/me", headers=headers).status_code == 401
        refresh = httpx.post(REALM + "/token", data={"client_id": "ledger-expiry-test", "client_secret": "expiry-test-secret",
                                                    "grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]}, timeout=10)
        refresh.raise_for_status()
        assert TokenVerifier().verify(refresh.json()["access_token"])["sub"] == IDS["frank"]
    finally:
        httpx.delete(client_url, headers=admin, timeout=10).raise_for_status()
