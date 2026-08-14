#!/usr/bin/env python3
"""Fail-closed paid preflight for the exactly-once E40 U12 V3 image plate."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
INSTALLED_ROOT = Path("/Users/rogerwu/.local/share/backlotos")
INSTALLED_TOOLS = INSTALLED_ROOT / "share/pipeline-tools"
MANIFEST = ROOT / (
    "workflow/claude_writer_agent/production/"
    "e40_claude_writer_v3_140d4b7b_20260808/u12_v3_interior_plate_v1/"
    "E40_U12_V3_INTERIOR_DESK_MOUTH_ABSENT_PLATE_NO_SUBMIT_MANIFEST_V1.json"
)
NO_SUBMIT_PRECHECK = ROOT / (
    "qa/e40_preproduction_20260808/"
    "E40_U12_V3_INTERIOR_PLATE_INSTALLED_NO_SUBMIT_PRECHECK_V1.json"
)
OUT = ROOT / (
    "qa/e40_preproduction_20260808/"
    "E40_U12_V3_INTERIOR_PLATE_PAID_PREFLIGHT_V1.json"
)
TRANSACTION_DIR = ROOT / "workflow/tasks/giggle_submit_transactions/E40"
EXPECTED_VERSION = "0.2.49"
EXPECTED_IMAGE_PRICE = 5
EXPECTED_UPPER = 11


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load installed module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> int:
    failures: list[str] = []
    checks: dict[str, Any] = {}

    submitter_path = INSTALLED_TOOLS / "submit_giggle_image_manifest.py"
    credit_path = INSTALLED_TOOLS / "giggle_credit_statements.py"
    version_path = INSTALLED_ROOT / "source/version"
    for path in (MANIFEST, NO_SUBMIT_PRECHECK, submitter_path, credit_path, version_path):
        if not path.is_file():
            failures.append(f"MISSING:{path}")

    if failures:
        payload = {
            "schema": "qingshan.e40.u12.v3.interior_plate_paid_preflight.v1",
            "recorded_at": now(),
            "status": "FAIL",
            "failures": failures,
        }
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return 2

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    task = manifest["tasks"][0]
    precheck = json.loads(NO_SUBMIT_PRECHECK.read_text(encoding="utf-8"))
    work_queue = json.loads((ROOT / "workflow/work_queue.json").read_text(encoding="utf-8"))
    ledger = work_queue["e40_credits"]

    # Load the exact installed submitter so the fingerprint cannot drift from production.
    os.sys.path.insert(0, str(INSTALLED_TOOLS))
    submitter = load_module("installed_submit_giggle_image_manifest", submitter_path)
    credit = load_module("installed_giggle_credit_statements", credit_path)
    fingerprint = submitter.submission_fingerprint(task)
    expected_transaction = submitter.transaction_path(TRANSACTION_DIR, task)
    same_key_transactions = sorted(TRANSACTION_DIR.glob(f"{task['task_key']}__*.json"))

    statements = credit.fetch_pay_statements(100)
    comparable = [
        row for row in statements
        if row.get("event_type") == "Pay"
        and row.get("event_description") == "SingleGenerateImage"
        and row.get("model") == task.get("model")
    ]
    comparable.sort(key=lambda row: str(row.get("created_at", "")), reverse=True)
    latest = comparable[0] if comparable else None
    try:
        latest_price = int(abs(Decimal(str(latest["credit"])))) if latest else None
    except (KeyError, InvalidOperation, ValueError):
        latest_price = None

    output_dir = ROOT / manifest["output_dir"]
    existing_output_files = sorted(str(path.relative_to(ROOT)) for path in output_dir.glob("*") if path.is_file()) if output_dir.exists() else []
    process_text = subprocess.run(
        ["ps", "-axo", "pid=,command="], check=True, capture_output=True, text=True
    ).stdout
    relevant_processes = [
        line.strip() for line in process_text.splitlines()
        if task["task_key"] in line
        or ("submit_giggle_image_manifest.py" in line and "ps -axo" not in line)
    ]

    installed_version = version_path.read_text(encoding="utf-8").strip()
    prompt_path = ROOT / task["prompt_file"]
    reference_checks = []
    for binding in task.get("reference_bindings") or []:
        path = ROOT / binding["path"]
        observed = sha256(path) if path.is_file() else None
        reference_checks.append({
            "role": binding.get("role"),
            "path": binding["path"],
            "expected_sha256": binding.get("sha256"),
            "observed_sha256": observed,
            "status": "PASS" if observed == binding.get("sha256") else "FAIL",
        })

    checks.update({
        "installed_backlotos_version": {
            "expected": EXPECTED_VERSION,
            "observed": installed_version,
            "status": "PASS" if installed_version == EXPECTED_VERSION else "FAIL",
        },
        "installed_submitter": {
            "path": str(submitter_path),
            "sha256": sha256(submitter_path),
            "status": "PASS",
        },
        "api_credential_present": {
            "status": "PASS" if any(os.environ.get(name) for name in ("GIGGLE_API_KEY", "GIGGLEPRO_API_KEY", "GIGGLE_TOKEN")) else "FAIL"
        },
        "installed_no_submit_precheck": {
            "path": str(NO_SUBMIT_PRECHECK.relative_to(ROOT)),
            "sha256": sha256(NO_SUBMIT_PRECHECK),
            "observed_status": precheck.get("status"),
            "submitted": precheck.get("submitted"),
            "precheck_pass": precheck.get("precheck_pass"),
            "failed": precheck.get("failed"),
            "status": "PASS" if precheck.get("status") == "PASS" and precheck.get("submitted") == 0 and precheck.get("precheck_pass") == 1 and precheck.get("failed") == 0 else "FAIL",
        },
        "prompt": {
            "path": task["prompt_file"],
            "expected_sha256": task["prompt_sha256"],
            "observed_sha256": sha256(prompt_path) if prompt_path.is_file() else None,
            "status": "PASS" if prompt_path.is_file() and sha256(prompt_path) == task["prompt_sha256"] else "FAIL",
        },
        "reference_bindings": reference_checks,
        "task_fingerprint": fingerprint,
        "transaction_collision": {
            "expected_path": str(expected_transaction.relative_to(ROOT)),
            "expected_path_exists": expected_transaction.exists(),
            "same_task_key_transaction_count": len(same_key_transactions),
            "same_task_key_transactions": [str(path.relative_to(ROOT)) for path in same_key_transactions],
            "status": "PASS_ZERO" if not expected_transaction.exists() and not same_key_transactions else "FAIL",
        },
        "output_collision": {
            "directory": manifest["output_dir"],
            "existing_files": existing_output_files,
            "status": "PASS_ZERO" if not existing_output_files else "FAIL",
        },
        "isolated_submission_window": {
            "active_remote_image_pay": ledger.get("active_remote_image_pay"),
            "relevant_local_submit_processes": relevant_processes,
            "status": "PASS" if ledger.get("active_remote_image_pay") == 0 and not relevant_processes else "FAIL",
        },
        "authoritative_recent_image_price": {
            "endpoint": "/api/v1/payment/credit-statements",
            "event_description": "SingleGenerateImage",
            "model": task.get("model"),
            "expected_exact_price": EXPECTED_IMAGE_PRICE,
            "observed_latest_price": latest_price,
            "latest_statement_row": latest,
            "status": "PASS" if latest_price == EXPECTED_IMAGE_PRICE else "FAIL",
        },
        "credit_cap": {
            "current": ledger,
            "expected_pay_upper": EXPECTED_UPPER,
            "projected_net_upper": ledger.get("net", 0) + EXPECTED_UPPER,
            "projected_remaining_upper": ledger.get("cap", 0) - ledger.get("net", 0) - EXPECTED_UPPER,
            "projected_exact_net": ledger.get("net", 0) + EXPECTED_IMAGE_PRICE,
            "projected_exact_remaining": ledger.get("cap", 0) - ledger.get("net", 0) - EXPECTED_IMAGE_PRICE,
            "status": "PASS" if ledger.get("net", 0) + EXPECTED_UPPER <= ledger.get("cap", 0) else "FAIL",
        },
        "manifest_is_no_submit": {
            "authorization": manifest.get("authorization"),
            "maximum_new_submissions": manifest.get("maximum_new_submissions"),
            "status": "PASS" if manifest.get("authorization") is False and manifest.get("maximum_new_submissions") == 0 else "FAIL",
        },
    })

    for key, value in checks.items():
        if isinstance(value, dict) and str(value.get("status", "PASS")).startswith("FAIL"):
            failures.append(key)
    if any(row["status"] != "PASS" for row in reference_checks):
        failures.append("reference_bindings")

    payload = {
        "schema": "qingshan.e40.u12.v3.interior_plate_paid_preflight.v1",
        "recorded_at": now(),
        "status": "PASS" if not failures else "FAIL",
        "episode": "E40",
        "unit_id": "U12",
        "task_key": task["task_key"],
        "source_manifest": str(MANIFEST.relative_to(ROOT)),
        "source_manifest_sha256": sha256(MANIFEST),
        "submission_fingerprint": fingerprint,
        "maximum_new_submissions_after_explicit_authorization": 1,
        "provider_post_performed_by_this_preflight": False,
        "checks": checks,
        "failures": failures,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "out": str(OUT), "fingerprint": fingerprint, "latest_price": latest_price}, ensure_ascii=False))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
