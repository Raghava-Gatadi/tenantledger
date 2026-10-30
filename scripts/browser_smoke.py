"""Exercise the local UI through real OIDC sign-in. Creates one synthetic expense.

Install playwright and its Chromium browser, or set CHROME_EXECUTABLE to a local
Chrome executable. Screenshots and a machine-readable report go to artifacts/browser.
"""
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("APP_URL", "http://localhost:8000")
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "browser"
OUTPUT.mkdir(parents=True, exist_ok=True)


def main():
    failures = []
    checks = []
    with sync_playwright() as p:
        launch = {"headless": True}
        if os.environ.get("CHROME_EXECUTABLE"):
            launch["executable_path"] = os.environ["CHROME_EXECUTABLE"]
        browser = p.chromium.launch(**launch)
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
        page.on("pageerror", lambda error: failures.append(str(error)))

        def login(name):
            page.goto(BASE)
            page.get_by_role("link", name="Sign in to your workspace").click()
            page.locator("#username").fill(name)
            page.locator("#password").fill("LedgerDemo123!")
            page.locator("#kc-login").click()
            page.wait_for_url(BASE + "/")
            expect(page.locator("#workspace")).to_be_visible()

        def logout():
            page.locator("#logout").click()
            expect(page.locator("#welcome")).to_be_visible(timeout=15000)

        page.goto(BASE)
        expect(page.locator("#welcome")).to_be_visible()
        page.screenshot(path=str(OUTPUT / "sign-in.png"), full_page=True)
        login("alice")
        expect(page.get_by_role("heading", name="Your expenses")).to_be_visible()
        expect(page.locator("#expense-rows tr").first).to_be_visible()
        page.screenshot(path=str(OUTPUT / "expenses-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        expect(page.get_by_role("button", name="New expense")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Mobile page overflows horizontally"
        page.screenshot(path=str(OUTPUT / "expenses-mobile.png"), full_page=True)
        page.set_viewport_size({"width": 1440, "height": 1000})
        checks.extend(["OIDC authorization code + PKCE login", "desktop dashboard", "mobile layout"])

        title = "Browser smoke " + datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        page.get_by_role("button", name="New expense").click()
        page.get_by_label("Expense title").fill(title)
        page.get_by_label("Amount (USD)").fill("19.50")
        page.get_by_label("Category", exact=True).select_option("Travel")
        page.get_by_role("button", name="Create draft").click()
        expect(page.locator("#modal-title")).to_have_text(title)
        page.locator("#receipt-file").set_input_files({"name": "synthetic.pdf", "mimeType": "application/pdf", "buffer": b"%PDF-1.4\nSynthetic browser test receipt\n%%EOF"})
        expect(page.get_by_role("link", name="synthetic.pdf")).to_be_visible()
        page.get_by_role("button", name="Submit for approval").click()
        page.get_by_label("Approver", exact=True).select_option(label="Bob Rivera")
        page.get_by_role("button", name="Submit expense", exact=True).click()
        expect(page.locator("#modal")).not_to_be_visible()
        expect(page.locator("#expense-rows tr").filter(has_text=title)).to_contain_text("Pending")
        checks.append("create draft, attach receipt, submit with CSRF protection")
        logout()
        checks.append("browser logout removes local session and returns through Keycloak")

        login("bob")
        page.get_by_role("button", name=title, exact=True).click()
        page.get_by_role("button", name="Approve expense").click()
        expect(page.locator("#expense-rows tr").filter(has_text=title)).to_contain_text("Approved")
        checks.append("assigned approver completes workflow")
        logout()

        login("alex")
        expect(page.locator("#role-label")).to_contain_text("employee")
        page.get_by_label("Organization", exact=True).select_option(label="Juniper Labs")
        expect(page.get_by_role("heading", name="Team members")).to_be_visible()
        expect(page.locator("#role-label")).to_contain_text("admin")
        expect(page.locator("#member-list .member-card")).to_have_count(4)
        expect(page.locator("#member-list")).to_contain_text("Eve Walker")
        page.screenshot(path=str(OUTPUT / "organization-admin.png"), full_page=True)
        page.get_by_label("Organization", exact=True).select_option(label="Northstar Studio")
        expect(page.get_by_role("heading", name="Your expenses")).to_be_visible()
        expect(page.locator('[data-view="members"]')).not_to_be_visible()
        checks.append("same user has different roles in two organizations")
        logout()

        page.goto(BASE + "/docs")
        expect(page.locator(".swagger-ui")).to_be_visible()
        expect(page.locator(".swagger-ui .info .title")).to_contain_text("TenantLedger")
        checks.append("self-hosted OpenAPI documentation")
        browser.close()
    report = {"timestamp": datetime.now(UTC).isoformat(), "checks": checks, "javascript_errors": failures,
              "synthetic_expense_created": title}
    (OUTPUT / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    if failures:
        raise AssertionError(f"Browser JavaScript errors: {failures}")
    print(f"PASS: {len(checks)} browser checks; zero JavaScript errors. Screenshots: artifacts/browser/")


if __name__ == "__main__":
    main()
