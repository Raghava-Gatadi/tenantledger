# Reproducible vulnerability case studies

Run `make lab`. The runner first requires all five security assertions to pass on the
secure source. It then creates a temporary copy per defect, applies one exact source
edit, and runs the same targeted assertion. It accepts only the expected HTTP status
mismatch; import errors, fixture failures, or an unrelated exception fail the experiment.

No insecure environment variable, application route, or deployment mode exists in the
normal API. The variants run through FastAPI's in-process client against `ledger_test`.
Source transformations are in `lab/cases.py`; generated unified patches and reports
are saved to `artifacts/lab/`. Removing/reversing the one mutation restores the documented fix.

## V01 — Trusting the requested organization

**Rule:** An authenticated identity needs an active membership before accessing an
organization. A path parameter is a requested context, not proof of permission.

**Vulnerable version:** If the membership is absent, set the requested database tenant
and grant a fallback auditor role. RLS cannot repair an incorrectly authenticated
tenant context supplied by the application itself.

**Reproduction:** Alice requests Juniper's expense
`GET /api/orgs/20000000-0000-0000-0000-000000000002/expenses/30000000-0000-0000-0000-000000000008`.
The variant returns 200 with another organization's data.

**Fix:** Reject missing/inactive membership before setting transaction tenant context.
The secure version returns 404 and discloses no expense content.

**Regression:** `test_lab_tenant_boundary`. Related tests cover list, summary, export,
directory, audit and foreign IDs inside an otherwise authorized organization's path.
Maps to [OWASP API1: Broken Object Level Authorization](https://api-security.owasp.org/editions/2023/en/0xa1-broken-object-level-authorization/).

## V02 — Checking only the organization

**Rule:** Membership in the same organization does not grant access to every object.

**Vulnerable version:** Remove the employee ownership predicate from `visible_expenses`.
Database tenant isolation still holds, but private objects inside that tenant become visible.

**Reproduction:** Alex, an employee in Northstar, requests Alice's draft
`GET /api/orgs/20000000-0000-0000-0000-000000000001/expenses/30000000-0000-0000-0000-000000000001`.
The variant returns 200.

**Fix:** Apply the owner predicate for ordinary members, the assignment/state predicate
for approvers, and explicit auditor scope. Use the same function for detail/list/export.
The secure request returns 404.

**Regression:** `test_lab_object_ownership`, plus same-tenant writes, list/export
consistency, draft privacy, and parent-authorized receipt tests. This is an object
authorization defect, independently of cross-tenant isolation.

## V03 — Protected-property mass assignment

**Rule:** Expense approval state is set only by the authorized workflow.

**Vulnerable version:** Change the common input schema from `extra="forbid"` to
`extra="allow"`; expense creation forwards the extra field to the model.

**Reproduction:** As Alice, POST to Northstar's `/expenses` with:

```json
{"title":"Forged approval","category":"Other","amount_cents":500,"status":"approved"}
```

The variant returns 201 and creates an approved expense without a review. The database
status constraint permits the value because it is a valid state; it cannot establish
that an authorized business transition occurred.

**Fix:** Strict allowlisted request models reject unknown/protected fields. Owner and
organization are derived on the server; approval uses its own authorized transition.
The secure request returns 422 without an inserted expense.

**Regression:** `test_lab_protected_property` and the parameterized protected-field
suite. Maps to [OWASP API3: Broken Object Property Level Authorization](https://api-security.owasp.org/editions/2023/en/0xa3-broken-object-property-level-authorization/).

## V04 — Missing administrative action authorization

**Rule:** Being able to authenticate and name a membership does not grant role-edit authority.

**Vulnerable version:** Remove `require_role(ctx, "admin")` from `edit_member`.

**Reproduction:** Alice PATCHes her own Northstar membership with
`{"role":"admin","active":true}`. The variant returns 200 and elevates her role.

**Fix:** Enforce the current organization role at the administrative route. The secure
version returns 403; a database assertion verifies her employee role remains unchanged.

**Regression:** `test_lab_admin_action` and parameterized employee/approver/auditor
escalation tests. Maps to [OWASP API5: Broken Function Level Authorization](https://api-security.owasp.org/editions/2023/en/0xa5-broken-function-level-authorization/).

## V05 — Ignoring offboarding state

**Rule:** Removed members cannot retain organization access using an otherwise valid identity.

**Vulnerable version:** Check only for a membership row, ignoring its active flag.
Rows are retained for historical foreign keys, so presence alone is not current permission.

**Reproduction:** Alice first lists her expenses successfully. An admin deactivates
her membership. She repeats the list request with the same identity; the variant returns 200.

**Fix:** Evaluate current `membership.active` during every tenant authorization check.
The secure version returns 404. A separate real-Keycloak test repeats this scenario
with the exact same valid signed access token before and after removal.

**Regression:** `test_lab_stale_membership`, real unchanged-token revocation, role
demotion, local account disablement, provider disablement, provider logout, and invitation
reactivation protection. Membership lifecycle and authentication lifecycle are tested separately.

## Interpreting the report

`report.json` records a secure baseline and a detected/total count. Each vulnerable
test is expected to fail; the **lab command succeeds** only when every secure assertion
passes and every seeded defect causes its specific expected assertion failure. This
is a small, purposeful mutation campaign, not an exhaustive mutation score.
