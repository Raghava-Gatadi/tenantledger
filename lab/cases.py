"""Exact, reviewable edits. A missing/ambiguous anchor aborts the experiment."""

CASES = [
    {
        "id": "V01-tenant-boundary", "file": "app/policy.py", "test": "test_lab_tenant_boundary",
        "before": '    if not membership or not membership.active:\n        raise HTTPException(404, "Organization not found")',
        "after": '    if not membership:\n        set_tenant(db, org_id)\n        return Tenant(org_id, user, "auditor")\n    if not membership.active:\n        raise HTTPException(404, "Organization not found")',
        "insecure_status": 200, "secure_status": 404,
    },
    {
        "id": "V02-object-ownership", "file": "app/policy.py", "test": "test_lab_object_ownership",
        "before": '    return statement.where(Expense.owner_id == ctx.user.user_id)',
        "after": '    return statement  # Deliberate local lab fault: missing ownership restriction.',
        "insecure_status": 200, "secure_status": 404,
    },
    {
        "id": "V03-mass-assignment", "file": "app/schemas.py", "test": "test_lab_protected_property",
        "before": 'ConfigDict(extra="forbid", str_strip_whitespace=True)',
        "after": 'ConfigDict(extra="allow", str_strip_whitespace=True)',
        "insecure_status": 201, "secure_status": 422,
    },
    {
        "id": "V04-admin-escalation", "file": "app/main.py", "test": "test_lab_admin_action",
        "before": 'def edit_member(user_id: str, body: MemberEdit, ctx: Tenant = Depends(tenant), db: Session = Depends(get_db)):\n    require_role(ctx, "admin")',
        "after": 'def edit_member(user_id: str, body: MemberEdit, ctx: Tenant = Depends(tenant), db: Session = Depends(get_db)):\n    # Deliberate local lab fault: no administrative permission check.',
        "insecure_status": 200, "secure_status": 403,
    },
    {
        "id": "V05-stale-membership", "file": "app/policy.py", "test": "test_lab_stale_membership",
        "before": '    if not membership or not membership.active:',
        "after": '    if not membership:',
        "insecure_status": 200, "secure_status": 404,
    },
]
