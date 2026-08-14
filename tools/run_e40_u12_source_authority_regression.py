#!/usr/bin/env python3
"""Run the bounded V7-V17 E40 U12 source-authority regression matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TOOLS = {
    "source_invoker": (ROOT / "tools/run_e40_u12_source_layer_admission.py", "3e192b878d94a679393ef89b715e739070f4638d16222557776732fffba4b9f6"),
    "request_validator": (ROOT / "tools/validate_e40_u12_authority_admission_request.py", "06997681ce6e503aae1786a597e36f12756f08d1c4672f76e43a90728e993f8d"),
    "role_validator": (ROOT / "tools/validate_e40_u12_authority_role_collision.py", "a94ff997336d73f4ac2b216363b9fdd055997fcd9f1049d906ab2a539bca027b"),
    "revocation_invoker": (ROOT / "tools/run_e40_u12_authority_revocation_gate.py", "f844bcb5e742b404217330e621d2c6f34a59a1cb14a2ec5f892936b00738a9aa"),
    "combined_preflight": (ROOT / "tools/run_e40_u12_combined_authority_preflight.py", "366fb04779327157f6ba4cdf5e5a032ac86a0ff3ebee03099a2aac3f26fe2069"),
}
CONTRACT = "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v10_authority_admission_contract_v1/E40_U12_V10_TRUSTED_AUTHORITY_ADMISSION_KEY_CUSTODY_CONTRACT_V1.json"
SELF_REQUEST = "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v11_authority_request_validator_v1/E40_U12_V11_ATTACKER_SELF_ADMISSION_REQUEST_V1.json"
SOURCE_PACKAGE = "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v8_trusted_receipt_tamper_audit_v1/E40_U12_V8_SELF_SIGNED_RECEIPT_BYPASS_FIXTURE_V1.json"
COLLISION_POLICY = "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v12_role_collision_validity_v1/E40_U12_V12_EXISTING_OPPOSITE_ROLE_POLICY_FIXTURE_V1.json"
EXPIRED_REQUEST = "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v12_role_collision_validity_v1/E40_U12_V12_EXPIRED_REQUEST_FIXTURE_V1.json"
FUTURE_REQUEST = "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v12_role_collision_validity_v1/E40_U12_V12_NOT_YET_VALID_REQUEST_FIXTURE_V1.json"
UNREVOKED_REQUEST = "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v16_stage2_short_circuit_v1/E40_U12_V16_UNREVOKED_MALFORMED_REQUEST_FIXTURE_V1.json"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def run_case(
    case_id: str,
    command: list[str],
    receipt: Path,
    expected_status: str,
    required_codes: list[str],
    assertions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = subprocess.run(command, cwd=ROOT, check=False, capture_output=True, text=True)
    doc = json.loads(receipt.read_text(encoding="utf-8")) if receipt.is_file() else {}
    codes = [row.get("code") for row in doc.get("failures", []) if isinstance(row, dict)]
    failures: list[str] = []
    if result.returncode != 0:
        failures.append(f"unexpected_exit:{result.returncode}")
    if doc.get("status") != expected_status:
        failures.append(f"status:{doc.get('status')}!=expected:{expected_status}")
    for code in required_codes:
        if code not in codes:
            failures.append(f"missing_code:{code}")
    for key, expected in (assertions or {}).items():
        actual: Any = doc
        for part in key.split("."):
            if isinstance(actual, list):
                actual = actual[int(part)]
            elif isinstance(actual, dict):
                actual = actual.get(part)
            else:
                actual = None
        if actual != expected:
            failures.append(f"assert:{key}:{actual}!=expected:{expected}")
    return {
        "case_id": case_id,
        "status": "PASS_EXPECTED_FAIL_CLOSED" if not failures else "FAIL_REGRESSION",
        "process_exit_code": result.returncode,
        "receipt": rel(receipt),
        "receipt_sha256": sha256_file(receipt) if receipt.is_file() else None,
        "observed_status": doc.get("status"),
        "required_codes": required_codes,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--summary", required=True)
    args = parser.parse_args()
    out_dir = (ROOT / args.out_dir).resolve()
    summary_path = (ROOT / args.summary).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, (path, expected) in TOOLS.items():
        actual = sha256_file(path) if path.is_file() else None
        if actual != expected:
            raise SystemExit(f"PIN_FAIL:{name}:expected={expected}:actual={actual}")

    python = sys.executable
    source_out = out_dir / "01_source_self_signed.json"
    self_out = out_dir / "02_authority_self_admission.json"
    collision_out = out_dir / "03_role_collision.json"
    expired_out = out_dir / "04_expired_request.json"
    future_out = out_dir / "05_future_request.json"
    revoked_out = out_dir / "06_revoked_key.json"
    stage1_out = out_dir / "07_stage1_short_circuit.json"
    stage2_out = out_dir / "08_stage2_short_circuit.json"
    for path in out_dir.glob("*.json"):
        raise SystemExit(f"REFUSING_NONEMPTY_REGRESSION_DIR:{path}")

    cases = [
        run_case(
            "SOURCE_SELF_SIGNED_UNTRUSTED",
            [python, str(TOOLS["source_invoker"][0]), "--package", SOURCE_PACKAGE, "--out", rel(source_out), "--expect-reject"],
            source_out,
            "FAIL_CLOSED_SOURCE_LAYER_PACKAGE_REJECTED",
            ["SOURCE_PROVENANCE_RECEIPT_AUTHORITY_TRUSTED", "QA_EVIDENCE_RECEIPT_AUTHORITY_TRUSTED"],
        ),
        run_case(
            "AUTHORITY_SELF_ADMISSION",
            [python, str(TOOLS["request_validator"][0]), "--contract", CONTRACT, "--request", SELF_REQUEST, "--out", rel(self_out), "--expect-reject"],
            self_out,
            "FAIL_CLOSED_AUTHORITY_ADMISSION_REQUEST_REJECTED",
            ["CANDIDATE_AUTHOR_MAY_NOT_SELF_ADMIT", "ROGER_AUTHORIZATION_EXPLICIT"],
        ),
        run_case(
            "SOURCE_QA_ROLE_COLLISION",
            [python, str(TOOLS["role_validator"][0]), "--contract", CONTRACT, "--current-policy", COLLISION_POLICY, "--request", SELF_REQUEST, "--out", rel(collision_out), "--expect-reject"],
            collision_out,
            "FAIL_CLOSED_AUTHORITY_ROLE_COLLISION",
            ["PUBLIC_KEY_ROLE_COLLISION", "SOURCE_AND_QA_KEYS_DISTINCT"],
        ),
        run_case(
            "EXPIRED_REQUEST",
            [python, str(TOOLS["request_validator"][0]), "--contract", CONTRACT, "--request", EXPIRED_REQUEST, "--out", rel(expired_out), "--expect-reject"],
            expired_out,
            "FAIL_CLOSED_AUTHORITY_ADMISSION_REQUEST_REJECTED",
            ["VALID_NOT_AFTER"],
        ),
        run_case(
            "NOT_YET_VALID_REQUEST",
            [python, str(TOOLS["request_validator"][0]), "--contract", CONTRACT, "--request", FUTURE_REQUEST, "--out", rel(future_out), "--expect-reject"],
            future_out,
            "FAIL_CLOSED_AUTHORITY_ADMISSION_REQUEST_REJECTED",
            ["VALID_NOT_BEFORE"],
        ),
        run_case(
            "REVOKED_KEY",
            [python, str(TOOLS["revocation_invoker"][0]), "--subject", SELF_REQUEST, "--out", rel(revoked_out), "--expect-reject"],
            revoked_out,
            "FAIL_CLOSED_AUTHORITY_OR_KEY_REVOKED",
            ["AUTHORITY_OR_KEY_REVOKED"],
        ),
        run_case(
            "STAGE1_REVOCATION_SHORT_CIRCUIT",
            [python, str(TOOLS["combined_preflight"][0]), "--authority-request", SELF_REQUEST, "--source-package", SOURCE_PACKAGE, "--out", rel(stage1_out), "--expect-reject"],
            stage1_out,
            "FAIL_CLOSED_REVOKED_OR_INVALID_STOPPED_AT_STAGE1",
            [],
            {"stages.1.executed": False, "stages.2.executed": False, "downstream_stage2_receipt_exists": False, "downstream_stage3_receipt_exists": False},
        ),
        run_case(
            "STAGE2_REQUEST_SHORT_CIRCUIT",
            [python, str(TOOLS["combined_preflight"][0]), "--authority-request", UNREVOKED_REQUEST, "--source-package", SOURCE_PACKAGE, "--out", rel(stage2_out), "--expect-reject"],
            stage2_out,
            "FAIL_CLOSED_AUTHORITY_REQUEST_STOPPED_AT_STAGE2",
            [],
            {"stages.0.status": "PASS_NOT_REVOKED", "stages.1.executed": True, "stages.2.executed": False, "downstream_stage3_receipt_exists": False},
        ),
    ]
    passed = sum(row["status"] == "PASS_EXPECTED_FAIL_CLOSED" for row in cases)
    summary = {
        "schema": "qingshan.e40.u12.v18.source_authority_regression_matrix.v1",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS_ALL_EXPECTED_FAIL_CLOSED" if passed == len(cases) else "FAIL_REGRESSION",
        "case_count": len(cases),
        "passed_count": passed,
        "failed_count": len(cases) - passed,
        "cases": cases,
        "authority_keys_admitted": 0,
        "production_assets_admitted": 0,
        "policy_changed": False,
        "failure_behavior": "NO_KEY_ADMISSION_NO_SOURCE_ADMISSION_NO_RENDER_NO_SUBMIT_NO_TRANSACTION_NO_CREDITS_NO_AGENTCUT_NO_ASSEMBLY",
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": summary["status"], "passed": passed, "total": len(cases), "summary": rel(summary_path)}, ensure_ascii=False))
    return 0 if passed == len(cases) else 2


if __name__ == "__main__":
    sys.exit(main())
