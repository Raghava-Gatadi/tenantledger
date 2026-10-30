# Running and maintaining the local project

## Services and configuration

| Service | Local address | Purpose |
| --- | --- | --- |
| API/UI | http://localhost:8000 | Application, health, API docs |
| Keycloak | http://localhost:8080 | OIDC and identity administration |
| PostgreSQL | localhost:5433 | `ledger`, `ledger_test`, `keycloak` databases |

Compose project name is `tenantledger`; its containers and named volume are independent
of other local Docker projects. The runtime API is non-root, read-only except for `/tmp`,
and has no-new-privileges enabled. Migration/test containers intentionally use privileged
database credentials for schema setup and synthetic fixture reset. Only tests run as
container root to write mounted evidence files; this is not the API identity.

| Setting | Meaning |
| --- | --- |
| `DATABASE_URL` | Runtime connection; Compose supplies the restricted app role |
| `SESSION_SECRET` | Random signing key for temporary OIDC flow cookies |
| `TOKEN_ENCRYPTION_KEY` | Fernet key for token values in server-side sessions |
| `APP_URL` | Exact browser origin and callback/logout base URL |
| `OIDC_ISSUER` | Public issuer expected in signed tokens |
| `OIDC_INTERNAL_URL` | Trusted server-to-server Keycloak realm URL |
| `OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET` | Browser authorization-code client |
| `OIDC_AUDIENCE` / `OIDC_API_CLIENT_SECRET` | API audience and introspection client credentials |
| `COOKIE_SECURE` | Enable Secure cookies when serving behind HTTPS |
| `ENVIRONMENT` | Non-development mode rejects insecure public URL/cookie/default client-secret settings |
| `SESSION_MAX_SECONDS` | Upper bound; access-token expiry can end a session sooner |

Development database passwords and client secrets are published in Compose/realm
configuration. Changing only `.env` does not rotate database or Keycloak credentials.
For a real deployment, provision fresh identities, update the actual IdP/database,
and replace this local Compose topology with a deployment-specific secret/TLS plan.

## Useful commands

```sh
make up
make test
make lab
make lint
make logs
docker compose ps
make down
```

Tests intentionally require a database named `ledger_test`; the fixture refuses
other database names before truncating synthetic data. Tests and the mutation lab
share that database and should run sequentially. The browser exercise uses the actual
demo and creates a clearly labeled synthetic record.

Python developers can install the locked requirements in a venv and run:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock -r requirements-test.lock
# Compose's postgres and keycloak must already be healthy.
DATABASE_URL=postgresql+psycopg://ledger_owner:local-owner-password@localhost:5433/ledger_test .venv/bin/alembic upgrade head
.venv/bin/python -m pytest
```

The test fixture selects the restricted test URL by default. Do not set `DATABASE_URL`
to the interactive database when invoking tests.

## Lifecycle behavior

- **Membership deactivated:** the next tenant membership check returns 404. History remains.
- **Role changed:** the next request uses the new DB role; no fresh JWT is required.
- **Local account disabled:** the next authenticated request returns 401.
- **Keycloak account disabled, deleted or logged out:** uncached introspection rejects the token
  once Keycloak reports it inactive. Real tests verify the next request in this setup.
- **Token/browser session expires:** API returns 401; the UI offers sign-in again.
- **Logout:** browser session row/cookie removed, then provider logout. The local removal
  works even after token expiry. A replayed old cookie cannot recover the deleted session.
- **Invitation expires/is consumed:** acceptance returns 404. It cannot alter an existing
  membership, so an old invitation cannot reactivate someone who was removed.

JWT signing keys are read only from the configured Keycloak JWKS endpoint. Key sets
are cached for five minutes; the library refreshes when an unknown signing key appears.
Issuer/audience are fixed configuration, never derived from the token. Session-encryption
key rotation requires invalidating existing sessions or adding a deliberate key-rotation
scheme; the current implementation accepts one encryption key.

## Troubleshooting

- **Docker socket missing:** start Docker Desktop and confirm `docker info` succeeds.
- **Port already allocated:** stop the conflicting service or deliberately update the
  Compose ports, public URLs and Keycloak redirect/issuer settings together.
- **Keycloak startup:** `docker compose logs --tail=100 keycloak`; initial import may take a minute.
- **401 with a signed token:** confirm API audience, access-token type, current session,
  and dedicated API introspection credentials. A valid signature is only one check.
- **503 after signing in:** verify Keycloak connectivity; the API fails closed.
- **API refuses DB credentials:** use `ledger_app`, not the owner/superuser migration identity.
- **Realm JSON changes do not appear:** Keycloak import runs only for a missing realm.
  Apply changes through local IdP administration, or reset the disposable demo deliberately.
- **Local test module import error:** use `python -m pytest`, not an unrelated global pytest executable.

To erase **all TenantLedger demo/test/identity data**, use
`docker compose down --volumes` and then `make up`. This destroys this project's named
volume; it is not part of normal startup or shutdown. Back up anything you want to retain first.

## Deployment boundaries

No public site, cloud account, external email, payment service or GitHub repository
is created by the setup. GitHub Actions configuration is supplied but has to run in
your repository before you can claim a hosted CI result. The local verification record
separately states what was actually executed.

Before public use, address TLS termination and trusted proxies, production Keycloak,
per-tenant/IP rate limits, storage quotas, receipt scanning, backup/recovery, secret
rotation, dependency/image updates, monitoring, external audit retention, and removal
of seeded credentials/password-grant test clients. The application does not implement
payment/reimbursement or store payment credentials.
