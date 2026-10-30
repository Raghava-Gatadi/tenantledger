# Threat model

## Assets and actors

Protect expense contents, receipts, membership authority, approval integrity, session
credentials, and organization audit records. Adversaries include anonymous clients,
ordinary members changing IDs/fields, users with different roles across organizations,
removed members holding old tokens, and a malicious website triggering browser requests.

The local demo assumes its host, database owner, identity provider, configured signing
keys and API process are trusted. A compromised database owner or API host is outside
the tenant-isolation security claim. All seeded people and expenses are fictional.

## Abuse cases and evidence

| Threat | Control | Evidence |
| --- | --- | --- |
| Change organization path/header | Current DB membership before setting context | Cross-tenant API matrix; V01 |
| Guess another member's expense ID | Shared object visibility policy | Same-tenant tests; V02 |
| Hide foreign IDs in an authorized organization's path | Explicit org predicate + RLS | Foreign-ID matrix and RLS tests |
| Change owner, org or approval status in JSON | Strict input schema + server-derived fields | Protected-property tests; V03 |
| Invoke admin routes as an employee | Server-side administrative role checks | Privilege escalation tests; V04 |
| Reuse access after removal/demotion | Current membership on every request | Lifecycle tests; V05; real unchanged-token test |
| Forge, confuse or replay invalid tokens | Fixed issuer/JWKS, RS256 allowlist, audience, required claims, expiry and introspection | Token validation and real IdP tests |
| Provider logout/account disable leaves JWT accepted | Uncached introspection with API credentials | Real disable/logout tests |
| Cross-site cookie mutation | SameSite cookie + Origin + CSRF check | Session tests and actual browser workflow |
| Login CSRF/code interception | Signed state, nonce, PKCE, fixed redirect URI | State tests + real OIDC browser login |
| Unauthorized file download | Parent expense authorization on download | Receipt-boundary tests |
| Hostile upload/resource exhaustion | Body limits before parsing, 2 MB/5-receipt bounds, basic file signature checks | Input tests |
| Double approval | Row lock + version + state transition | Concurrent request test |
| Last admin removed by racing changes | Transaction-scoped advisory lock per organization | Last-admin protection test; lock in implementation |
| Pool retains previous tenant | Transaction-local context | Same-backend commit/rollback test |
| App tampers with audit records | SELECT/INSERT-only grant | Database permission test |
| CSV formula injection | Prefix formula-leading titles | Export regression test |

The request log records method, path, status and a generated request ID for denied
access. Business audit rows record the verified actor and organization. Logs intentionally
omit credentials, authorization headers, query strings and request bodies.

## Residual risks and boundaries

- RLS protects business records under the tenant context the API establishes. Arbitrary
  SQL execution with runtime credentials could alter that context. Parameterized queries
  and review remain necessary. Control-plane tables use application checks.
- A browser XSS could act through the current session despite HttpOnly cookies. The UI
  escapes server-returned values and uses a restrictive CSP; there has been no independent
  penetration test or exhaustive XSS audit.
- Basic file magic checks do not establish that a receipt is safe. Files are downloaded
  as attachments and never executed/rendered by this application. Production requires
  malware scanning and a content-handling policy.
- Receipt/data storage is bounded per request/expense, but the demo does not enforce
  tenant storage quotas or ingress-wide request/concurrency rate limits.
- Keycloak introspection adds a dependency and latency to every authenticated request.
  No cache means there is no application-cache revocation window; provider replication
  and already authorized in-flight operations still matter.
- The API cannot promise immediate cancellation of work already authorized before a
  membership change commits. Tests verify the next request after a committed change.
- Database-owner privileges can alter audit rows. External retention, alerts, backups
  and tamper-evident storage are operational extensions, not current capabilities.
- Admin membership powers permit role grants. Four-eyes approval, approval limits,
  reimbursements, currencies, notifications, and external integrations are out of scope.
- The provided Compose stack uses development credentials, Keycloak start-dev, and
  loopback HTTP. It must be hardened before any public deployment.

The five mutations establish detection of those five known faults. They do not prove
the absence of other vulnerabilities. Statement coverage measures executed code, not
authorization completeness or security assurance.
