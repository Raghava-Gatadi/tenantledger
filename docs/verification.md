# Verification record

Verified locally on **October 28, 2026**, using Docker Desktop on macOS / Apple
Silicon. The final automated suite ran at **5:29 a.m. America/New_York**; the final
browser run completed at **5:31 a.m. America/New_York**. These are local execution
results, not a claim of a hosted GitHub Actions run.

| Check | Observed result |
| --- | --- |
| Application, database, identity, lifecycle and input tests | **86 passed; 0 failed; 0 skipped** |
| Python statement coverage | **606 / 667 statements, 90.85% (rounded: 91%)** |
| Secure lab baseline | **5 / 5 security assertions pass** |
| Isolated vulnerable variants | **5 / 5 defects detected by the expected assertion mismatch** |
| Browser smoke workflow | **8 checks passed; no JavaScript page errors** |
| Static lint | **Ruff: all checks passed** |

## Environment actually exercised

- PostgreSQL **18.6**, with real RLS policies and the restricted `ledger_app` role.
- Keycloak **26.8.1**, with real code-flow browser login, JWTs and token introspection.
- Python **3.13.18** in the Docker image.
- FastAPI **0.162.0**, SQLAlchemy **2.0.55**, PyJWT **2.15.1**, psycopg **3.3.6**.
- Playwright **1.64.1**, controlling the installed Google Chrome in headless mode.
- Desktop viewport **1440 × 1000** and mobile viewport **390 × 844**.

The PostgreSQL version was updated to its current maintenance release during
verification; the final suite above ran against 18.6. Upstream release details:
[PostgreSQL 18.6 release notes](https://www.postgresql.org/docs/release/18.6/).

## Preserved evidence

- [JUnit test results](evidence/tests.xml)
- [Statement coverage JSON](evidence/coverage.json)
- [Mutation-lab report](evidence/lab-report.json)
- [Browser workflow report](evidence/browser-report.json)
- [V01 patch](evidence/V01-tenant-boundary.patch)
- [V02 patch](evidence/V02-object-ownership.patch)
- [V03 patch](evidence/V03-mass-assignment.patch)
- [V04 patch](evidence/V04-admin-escalation.patch)
- [V05 patch](evidence/V05-stale-membership.patch)
- [Desktop screenshot](screenshots/expenses-desktop.png)
- [Mobile screenshot](screenshots/expenses-mobile.png)
- [Organization administration screenshot](screenshots/organization-admin.png)

The screenshot records include clearly labeled synthetic expenses created by browser
verification. They show actual UI output, not design mockups.

## What the tests establish

The suite includes successful expense workflows and rejected cross-tenant/same-tenant
access; protected-property and administrative escalation; receipt parent checks;
role changes and removal; invitation expiry/reuse/email binding; JWT algorithm,
signature, issuer, audience and lifetime validation; CSRF; browser session expiry;
real IdP disablement, account deletion, logout, refresh and token expiration; concurrent
approval; scoped exports; database grants; and pooled-connection tenant reset after
both commit and rollback.

Most policy tests inject a verified principal to isolate authorization behavior.
The identity tests use the actual Keycloak server. The browser test uses the real
application, provider redirects and cookies. Browser execution is outside the Python
coverage run, so its callback coverage is not included in the 90.85% figure.

There is one non-failing upstream Starlette warning about the future migration of
its test client from `httpx` to `httpx2`. It did not skip tests or affect the results.

The mutation score concerns five deliberately seeded faults. It is not an exhaustive
security assessment. Statement coverage is not security coverage. GitHub Actions is
configured in the repository but was not run on GitHub during this local build.

Reproduce with `make test`, `make lab`, and the browser command in the README. New
runs write fresh evidence to `artifacts/`; this document preserves the recorded run.
