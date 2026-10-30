"""Prove that each security assertion passes when fixed and detects its isolated fault.

No vulnerable HTTP server is started. Each version lives in a temporary directory
and uses the guarded ledger_test database via FastAPI's in-process test client.
"""
import difflib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

from lab.cases import CASES

ROOT = Path(__file__).resolve().parents[1]


def run_pytest(root: Path, target: str, report: Path):
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "HYPOTHESIS_STORAGE_DIRECTORY": "/tmp/ledger-hypothesis"}
    result = subprocess.run([sys.executable, "-m", "pytest", target, "-q", "-p", "no:cacheprovider", f"--junitxml={report}"],
                            cwd=root, env=env, capture_output=True, text=True, timeout=90)
    return result


def main():
    destination = ROOT / "artifacts" / "lab"
    destination.mkdir(parents=True, exist_ok=True)
    baseline = run_pytest(ROOT, "tests/test_lab_regressions.py", destination / "secure.xml")
    (destination / "secure.txt").write_text(baseline.stdout + baseline.stderr)
    if baseline.returncode != 0:
        print(baseline.stdout, baseline.stderr)
        raise SystemExit("Secure baseline failed. No mutation result can be trusted.")
    print("SECURE BASELINE: all five security regressions pass.")
    results = []
    for case in CASES:
        with tempfile.TemporaryDirectory(prefix="tenantledger-lab-") as folder:
            variant = Path(folder)
            for name in ("app", "tests"):
                shutil.copytree(ROOT / name, variant / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            shutil.copy(ROOT / "pyproject.toml", variant / "pyproject.toml")
            # Only relevant to direct local runs; container runs receive settings via environment.
            if (ROOT / ".env").exists():
                shutil.copy(ROOT / ".env", variant / ".env")
            target = variant / case["file"]
            original = target.read_text()
            if original.count(case["before"]) != 1:
                raise SystemExit(f"Ambiguous or stale mutation anchor: {case['id']}")
            mutated = original.replace(case["before"], case["after"], 1)
            target.write_text(mutated)
            patch = "".join(difflib.unified_diff(original.splitlines(keepends=True), mutated.splitlines(keepends=True),
                                               fromfile="secure/" + case["file"], tofile="vulnerable/" + case["file"]))
            (destination / (case["id"] + ".patch")).write_text(patch)
            xml = destination / (case["id"] + ".xml")
            result = run_pytest(variant, "tests/test_lab_regressions.py::" + case["test"], xml)
            (destination / (case["id"] + ".txt")).write_text(result.stdout + result.stderr)
            failures = ElementTree.parse(xml).findall(".//testcase/failure") if xml.exists() else []
            errors = ElementTree.parse(xml).findall(".//testcase/error") if xml.exists() else []
            expected = f"assert {case['insecure_status']} == {case['secure_status']}"
            # Require the expected assertion mismatch, not an import, setup, or infrastructure error.
            detected = result.returncode == 1 and len(failures) == 1 and not errors and expected in (failures[0].text or "")
            results.append({"case": case["id"], "detected": detected, "test": case["test"],
                            "expected_secure_status": case["secure_status"], "observed_vulnerable_status": case["insecure_status"] if detected else None})
            print(f"{case['id']}: {'DETECTED' if detected else 'FAILED EXPERIMENT'}")
    report = {"generated_at": datetime.now(UTC).isoformat(), "secure_baseline_passed": True,
              "mutants_detected": sum(r["detected"] for r in results), "mutants_total": len(CASES), "results": results}
    (destination / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Detected {report['mutants_detected']}/{len(CASES)} deliberately introduced defects. Reports: artifacts/lab/")
    if not all(r["detected"] for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
