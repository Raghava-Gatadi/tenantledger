# Three-minute portfolio walkthrough

Start with `make up`. Use a fresh sign-in for each role; sign out through the UI so
the Keycloak session also ends. All demo passwords are `LedgerDemo123!`.

1. **0:00 — Show a real product.** Sign in as Alice. Create a travel expense in
   Northstar, attach a receipt, select Bob, and submit. Explain that ownership and
   organization are server-derived and the amount becomes immutable on submission.
2. **0:45 — Show an authorized approval.** Sign out, sign in as Bob, and approve
   the assigned expense. Show that Bob cannot see Alice's unrelated drafts.
3. **1:10 — Show tenant-specific roles.** Sign in as Alex. Northstar grants employee
   access; switch to Juniper and show membership administration. This is one identity
   with different organization permissions, not two unrelated account systems.
4. **1:40 — Show the evidence.** Open the CI/test report and run `make lab`. Show
   the secure baseline and five detected mutations. Pick V01 and explain why RLS cannot
   compensate for the application establishing an unauthorized tenant context.
5. **2:15 — Show offboarding.** In two browser profiles, use Carol to deactivate
   Alice's Northstar membership. Alice's next API request fails even while her token
   is unexpired. An account can remain authenticated while losing organization access.
6. **2:45 — State the tradeoff.** Explain uncached introspection versus availability
   and latency, the migration/runtime DB-role separation, and the limits of the local deployment.

For invitations, Carol can invite `heidi@example.test`. Sign in as Heidi and use
“Accept an invitation.” No email is sent; the UI gives the admin a one-time token.

## Questions to be ready to answer

- Why are authentication, tenant membership and object authorization separate checks?
- Why is an unguessable UUID insufficient authorization?
- Which failure does RLS catch, and which failures require application policy?
- Why does an access token's valid signature not prove the user's current session is active?
- What happens if Keycloak is unavailable? What would a five-second cache change?
- How do connection pools and transaction-local tenant settings interact?
- How do row locking and client versions prevent duplicate approval decisions?
- What is and is not protected by the audit-table grants?
- How do you know a regression test detects the bug it was written for?
- Which production capabilities are deliberately outside this portfolio's scope?

## Resume wording

Use only claims supported by your own run and understanding:

> Built a multi-tenant expense approval platform with FastAPI, PostgreSQL and Keycloak;
> implemented organization-scoped authorization, row-level isolation, and automated
> tests for cross-tenant access, privilege escalation and membership revocation.

> Created five reproducible vulnerable source variants and regression tests that
> detect each defect, with documented root causes, fixes and CI verification.

Add measured counts from `docs/verification.md` after reproducing them. Do not describe
local demo traffic as production usage, a unit-test percentage as security coverage,
or this lab as an independent penetration test.
