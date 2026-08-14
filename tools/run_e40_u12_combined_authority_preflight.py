#!/usr/bin/env python3
"""Combined E40 U12 authority preflight with mandatory revocation-first order."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REVOCATION_INVOKER = ROOT / "tools/run_e40_u12_authority_revocation_gate.py"
REVOCATION_INVOKER_SHA256 = "f844bcb5e742b404217330e621d2c6f34a59a1cb14a2ec5f892936b00738a9aa"
REQUEST_VALIDATOR = ROOT / "tools/validate_e40_u12_authority_admission_request.py"
REQUEST_VALIDATOR_SHA256 = "06997681ce6e503aae1786a597e36f12756f08d1c4672f76e43a90728e993f8d"
REQUEST_CONTRACT = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v10_authority_admission_contract_v1/E40_U12_V10_TRUSTED_AUTHORITY_ADMISSION_KEY_CUSTODY_CONTRACT_V1.json"
REQUEST_CONTRACT_SHA256 = "064ea0ee42f82d817fe33976f2a765a663fe4735c9f8e4fa97c8997bf03500fb"
SOURCE_INVOKER = ROOT / "tools/run_e40_u12_source_layer_admission.py"
SOURCE_INVOKER_SHA256 = "3e192b878d94a679393ef89b715e739070f4638d16222557776732fffba4b9f6"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def require_pin(path: Path, expected: str, label: str) -> None:
    if not path.is_file():
        raise SystemExit(f"PIN_FAIL_{label}_MISSING:{path}")
    actual = sha256_file(path)
    if actual != expected:
        raise SystemExit(f"PIN_FAIL_{label}_SHA256:expected={expected}:actual={actual}")


def safe_repo_path(raw: str, label: str) -> Path:
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise SystemExit(f"{label}_MUST_BE_REPO_RELATIVE")
    resolved = (ROOT / path).resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise SystemExit(f"{label}_OUTSIDE_REPOSITORY") from exc
    return resolved


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--authority-request", required=True)
    parser.add_argument("--source-package", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--expect-reject", action="store_true")
    args = parser.parse_args()
    request = safe_repo_path(args.authority_request, "AUTHORITY_REQUEST")
    package = safe_repo_path(args.source_package, "SOURCE_PACKAGE")
    out = safe_repo_path(args.out, "OUT")
    for path, label in ((request, "AUTHORITY_REQUEST"), (package, "SOURCE_PACKAGE")):
        if not path.is_file():
            raise SystemExit(f"{label}_MISSING:{path}")
    require_pin(REVOCATION_INVOKER, REVOCATION_INVOKER_SHA256, "REVOCATION_INVOKER")
    require_pin(REQUEST_VALIDATOR, REQUEST_VALIDATOR_SHA256, "REQUEST_VALIDATOR")
    require_pin(REQUEST_CONTRACT, REQUEST_CONTRACT_SHA256, "REQUEST_CONTRACT")
    require_pin(SOURCE_INVOKER, SOURCE_INVOKER_SHA256, "SOURCE_INVOKER")

    stage1 = out.with_name(out.stem + ".stage1_revocation.json")
    stage2 = out.with_name(out.stem + ".stage2_request.json")
    stage3 = out.with_name(out.stem + ".stage3_source_package.json")
    for path in (stage2, stage3):
        if path.exists():
            raise SystemExit(f"REFUSING_STALE_DOWNSTREAM_RECEIPT:{path}")

    stage1_cmd = [
        sys.executable,
        str(REVOCATION_INVOKER),
        "--subject",
        relative(request),
        "--out",
        relative(stage1),
    ]
    stage1_result = subprocess.run(stage1_cmd, cwd=ROOT, check=False)
    stage1_doc = json.loads(stage1.read_text(encoding="utf-8")) if stage1.is_file() else {}
    stage1_pass = stage1_result.returncode == 0 and stage1_doc.get("status") == "PASS_NOT_REVOKED"

    stages = [
        {
            "stage": 1,
            "name": "PINNED_REVOCATION_GATE",
            "executed": True,
            "exit_code": stage1_result.returncode,
            "status": stage1_doc.get("status"),
            "receipt": relative(stage1),
            "receipt_sha256": sha256_file(stage1) if stage1.is_file() else None,
        }
    ]
    final_status: str
    rejected = False
    if not stage1_pass:
        rejected = True
        final_status = "FAIL_CLOSED_REVOKED_OR_INVALID_STOPPED_AT_STAGE1"
        stages.extend(
            [
                {"stage": 2, "name": "AUTHORITY_REQUEST_GATE", "executed": False, "reason": "STAGE1_REVOCATION_FAILED"},
                {"stage": 3, "name": "SOURCE_RECEIPT_AND_PACKAGE_GATE", "executed": False, "reason": "STAGE1_REVOCATION_FAILED"},
            ]
        )
    else:
        stage2_result = subprocess.run(
            [
                sys.executable,
                str(REQUEST_VALIDATOR),
                "--contract",
                relative(REQUEST_CONTRACT),
                "--request",
                relative(request),
                "--out",
                relative(stage2),
            ],
            cwd=ROOT,
            check=False,
        )
        stage2_doc = json.loads(stage2.read_text(encoding="utf-8")) if stage2.is_file() else {}
        stage2_pass = stage2_result.returncode == 0 and stage2_doc.get("status") == "PASS_REQUEST_ELIGIBLE_FOR_SEPARATE_POLICY_ADMISSION_REVIEW"
        stages.append({"stage": 2, "name": "AUTHORITY_REQUEST_GATE", "executed": True, "exit_code": stage2_result.returncode, "status": stage2_doc.get("status"), "receipt": relative(stage2), "receipt_sha256": sha256_file(stage2) if stage2.is_file() else None})
        if not stage2_pass:
            rejected = True
            final_status = "FAIL_CLOSED_AUTHORITY_REQUEST_STOPPED_AT_STAGE2"
            stages.append({"stage": 3, "name": "SOURCE_RECEIPT_AND_PACKAGE_GATE", "executed": False, "reason": "STAGE2_REQUEST_FAILED"})
        else:
            stage3_result = subprocess.run(
                [sys.executable, str(SOURCE_INVOKER), "--package", relative(package), "--out", relative(stage3)],
                cwd=ROOT,
                check=False,
            )
            stage3_doc = json.loads(stage3.read_text(encoding="utf-8")) if stage3.is_file() else {}
            stages.append({"stage": 3, "name": "SOURCE_RECEIPT_AND_PACKAGE_GATE", "executed": True, "exit_code": stage3_result.returncode, "status": stage3_doc.get("status"), "receipt": relative(stage3), "receipt_sha256": sha256_file(stage3) if stage3.is_file() else None})
            rejected = stage3_result.returncode != 0
            final_status = stage3_doc.get("status") or "FAIL_CLOSED_STAGE3_NO_RECEIPT"

    receipt = {
        "schema": "qingshan.e40.u12.v15.combined_authority_preflight.v1",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": final_status,
        "stage_order": ["PINNED_REVOCATION_GATE", "AUTHORITY_REQUEST_GATE", "SOURCE_RECEIPT_AND_PACKAGE_GATE"],
        "stages": stages,
        "downstream_stage2_receipt_exists": stage2.exists(),
        "downstream_stage3_receipt_exists": stage3.exists(),
        "authority_admitted": False,
        "asset_admitted": False,
        "policy_changed": False,
        "failure_behavior": "NO_KEY_ADMISSION_NO_SOURCE_ADMISSION_NO_RENDER_NO_SUBMIT_NO_TRANSACTION_NO_CREDITS_NO_AGENTCUT_NO_ASSEMBLY",
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": final_status, "stages": stages, "out": relative(out)}, ensure_ascii=False))
    if args.expect_reject:
        return 0 if rejected else 3
    return 0 if not rejected else 2


if __name__ == "__main__":
    sys.exit(main())
