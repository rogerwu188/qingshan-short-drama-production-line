#!/usr/bin/env python3
"""Reject authority IDs or keys already assigned to another admission role."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def mismatch(failures: list[dict[str, Any]], code: str, actual: Any, expected: Any) -> None:
    if actual != expected:
        failures.append({"code": code, "actual": actual, "expected": expected})


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--current-policy", required=True)
    parser.add_argument("--request", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--expect-reject", action="store_true")
    args = parser.parse_args()

    contract_path = (ROOT / args.contract).resolve()
    policy_path = (ROOT / args.current_policy).resolve()
    request_path = (ROOT / args.request).resolve()
    out_path = (ROOT / args.out).resolve()
    contract = load_json(contract_path)
    policy = load_json(policy_path)
    request = load_json(request_path)
    failures: list[dict[str, Any]] = []

    mismatch(
        failures,
        "CONTRACT_SCHEMA",
        contract.get("schema"),
        "qingshan.e40.u12.v10.trusted_authority_admission_key_custody_contract.v1",
    )
    mismatch(
        failures,
        "POLICY_SCHEMA",
        policy.get("schema"),
        "qingshan.e40.u12.v8.trusted_receipt_policy.v1",
    )
    mismatch(failures, "POLICY_CONTRACT_SHA256", policy.get("contract_sha256"), contract.get("source_layer_contract_sha256"))
    mismatch(
        failures,
        "REQUEST_SCHEMA",
        request.get("schema"),
        "qingshan.e40.u12.trusted_authority_admission_request.v1",
    )
    mismatch(failures, "REQUEST_CONTRACT_SHA256", request.get("contract_sha256"), sha256_file(contract_path))

    authority_id = request.get("authority_id")
    key_sha = request.get("public_key_sha256")
    purpose = request.get("purpose")
    rows = policy.get("trusted_authorities")
    rows = rows if isinstance(rows, list) else []
    admitted = [row for row in rows if isinstance(row, dict) and row.get("status") == "ADMITTED"]
    same_id = [row for row in admitted if row.get("authority_id") == authority_id]
    same_key = [row for row in admitted if row.get("public_key_sha256") == key_sha]
    opposite_id = [row for row in same_id if row.get("purpose") != purpose]
    opposite_key = [row for row in same_key if row.get("purpose") != purpose]
    duplicate_role = [row for row in admitted if row.get("purpose") == purpose and (row.get("authority_id") == authority_id or row.get("public_key_sha256") == key_sha)]

    mismatch(failures, "AUTHORITY_ID_ROLE_COLLISION", len(opposite_id), 0)
    mismatch(failures, "PUBLIC_KEY_ROLE_COLLISION", len(opposite_key), 0)
    mismatch(failures, "DUPLICATE_AUTHORITY_OR_KEY_IN_ROLE", len(duplicate_role), 0)
    mismatch(failures, "SOURCE_AND_QA_KEYS_DISTINCT", len(opposite_key), 0)

    status = "PASS_NO_EXISTING_ROLE_COLLISION" if not failures else "FAIL_CLOSED_AUTHORITY_ROLE_COLLISION"
    receipt = {
        "schema": "qingshan.e40.u12.v12.authority_role_collision_gate.v1",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "contract": args.contract,
        "contract_sha256": sha256_file(contract_path),
        "current_policy": args.current_policy,
        "current_policy_sha256": sha256_file(policy_path),
        "request": args.request,
        "request_sha256": sha256_file(request_path),
        "opposite_role_authority_id_matches": len(opposite_id),
        "opposite_role_public_key_matches": len(opposite_key),
        "failure_count": len(failures),
        "failures": failures,
        "authority_admitted": False,
        "policy_changed": False,
        "failure_behavior": "NO_KEY_ADMISSION_NO_SOURCE_ADMISSION_NO_RENDER_NO_SUBMIT_NO_TRANSACTION_NO_CREDITS_NO_AGENTCUT_NO_ASSEMBLY",
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "failure_count": len(failures), "out": args.out}, ensure_ascii=False))
    if args.expect_reject:
        return 0 if failures else 3
    return 0 if not failures else 2


if __name__ == "__main__":
    sys.exit(main())
