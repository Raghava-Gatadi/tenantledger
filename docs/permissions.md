# Permission matrix

All permissions are **within one currently active organization membership**. There
are four mutually exclusive roles per membership. Roles in another organization have
no effect. An account may have multiple memberships.

| Action | Employee | Approver | Admin | Auditor |
| --- | --- | --- | --- | --- |
| Create expense | Yes | Yes | No | No |
| View own expense | Yes | Yes | Yes, if previously owned | Yes |
| View someone else's expense | No | Assigned, non-draft only | No | Yes |
| Edit draft / attach receipt | Own draft | Own draft | No | No |
| Submit expense | Own draft | Own draft | No | No |
| Approve/reject | No | Assigned, submitted, not own | No | No |
| Download receipt | Same scope as expense | Same scope as expense | Same scope as expense | Yes |
| List, summary, export | Own records | Own + assigned non-drafts | Own historical records only | All organization records |
| List eligible approvers | Yes | Yes | Yes | Yes |
| Read member directory | No | No | Yes | Yes |
| Invite / change membership | No | No | Yes | No |
| Reassign submitted expense | No | No | Yes | No |
| Read audit log | No | No | Yes | Yes |

An admin can change roles, including granting an approval role, and this is audited.
This project does not implement two-person approval for role grants. A person who
needs both duties must explicitly change roles; holding an admin role does not itself
authorize an approval.

## Object and state rules

- New expense `org_id` and `owner_id` come from server context. Status begins at draft.
- Unknown/protected fields are rejected; roles, owner, organization, status and version
  cannot be mass-assigned through an expense creation/edit schema.
- Draft → submitted → approved **or** rejected. Approved/rejected records are terminal.
- An owner selects a different active organization member with the approver role.
- Only the assigned approver can decide a submitted expense. Rejection needs a reason.
- Mutation versions must match current database state; stale or repeated actions return 409.
- Admin reassignment exposes expense ID/owner/assignee/version metadata, not amount,
  title, notes, or receipts. The assignment list is bounded to 100 pending records.
- No active organization can lose its final active admin through the membership API.
- Existing memberships cannot be overwritten/reactivated by accepting an old invitation.
- Identity-provider disablement, local account disablement, and membership removal are
  distinct controls and have separate tests.

## Response contract

- **401**: unauthenticated, invalid/expired token/session, disabled account, provider-revoked session.
- **403**: authenticated in this organization but action forbidden, or invalid CSRF/origin.
- **404**: organization/object outside the caller's visible scope, or invalid invitation.
- **409**: invalid transition, stale version, existing invited membership, or final-admin removal.
- **413 / 415**: oversized request/receipt or unsupported receipt bytes.
- **422**: invalid input, protected fields, invalid approver, or missing rejection reason.
- **503**: identity provider unavailable; authenticated access fails closed.

Returning 404 for inaccessible objects avoids confirming their existence. This is
not a promise of identical timing for all missing and unauthorized requests.
