from hypothesis import HealthCheck, given
from hypothesis import settings as hypothesis_settings
from hypothesis import strategies as st

from app.seed import ORG_A

A = f"/api/orgs/{ORG_A}"
DRAFT = "30000000-0000-0000-0000-000000000001"


def test_receipt_type_and_size_limits(as_user):
    client = as_user("alice")
    path = A + f"/expenses/{DRAFT}/receipts"
    assert client.post(path, files={"file": ("script.html", b"<script>alert(1)</script>", "application/pdf")}).status_code == 415
    assert client.post(path, files={"file": ("big.pdf", b"%PDF-" + b"a" * 2_000_000, "application/pdf")}).status_code == 413
    assert client.post(A + "/expenses", content=b"x" * 33000, headers={"Content-Type": "application/json"}).status_code == 413


def test_export_formula_injection_and_search(as_user):
    client = as_user("alice")
    response = client.post(A + "/expenses", json={"title": "=SUM(1+1)", "category": "Other", "amount_cents": 100})
    assert response.status_code == 201
    assert "'=SUM(1+1)" in client.get(A + "/expenses/export").text
    result = client.get(A + "/expenses", params={"q": "=SUM"}).json()
    assert result["total"] == 1
    assert client.get(A + "/expenses", params={"q": "%"}).json()["total"] == 0


@given(st.integers(max_value=0) | st.integers(min_value=100_000_001, max_value=2**63))
@hypothesis_settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_invalid_money_values_never_create_expenses(as_user, amount):
    client = as_user("alice")
    response = client.post(A + "/expenses", json={"title": "Bad value", "category": "Other", "amount_cents": amount})
    assert response.status_code == 422


def test_pagination_and_invalid_status(as_user):
    client = as_user("alice")
    first = client.get(A + "/expenses?limit=2").json()
    second = client.get(A + "/expenses?limit=2&offset=2").json()
    assert first["total"] == 5
    assert {e["id"] for e in first["items"]}.isdisjoint(e["id"] for e in second["items"])
    assert client.get(A + "/expenses?limit=1000").status_code == 422
    assert client.get(A + "/expenses?status=unknown").status_code == 422
