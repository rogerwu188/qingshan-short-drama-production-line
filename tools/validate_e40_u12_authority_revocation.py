#!/usr/bin/env python3
"""Fail closed when an E40 U12 authority identity or key is revoked."""

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


def parse_time(raw: Any) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--expect-reject", action="store_true")
    args = parser.parse_args()

    contract_path = (ROOT / args.contract).resolve()
    registry_path = (ROOT / args.registry).resolve()
    subject_path = (ROOT / args.subject).resolve()
    out_path = (ROOT / args.out).resolve()
    contract = load_json(contract_path)
    registry = load_json(registry_path)
    subject = load_json(subject_path)
    failures: list[dict[str, Any]] = []

    def require(code: str, actual: Any, expected: Any) -> None:
        if actual != expected:
            failures.append({"code": code, "actual": actual, "expected": expected})

    require(
        "CONTRACT_SCHEMA",
        contract.get("schema"),
        "qingshan.e40.u12.v10.trusted_authority_admission_key_custody_contract.v1",
    )
    require(
        "REGISTRY_SCHEMA",
        registry.get("schema"),
        "qingshan.e40.u12.authority_revocation_registry.v1",
    )
    require("REGISTRY_CONTRACT_SHA256", registry.get("contract_sha256"), sha256_file(contract_path))
    require("REGISTRY_SERIAL_POSITIVE", isinstance(registry.get("serial"), int) and registry.get("serial") >= 1, True)

    authority = subject.get("authority") if isinstance(subject.get("authority"), dict) else subject
    authority_id = authority.get("authority_id")
    public_key_sha = authority.get("public_key_sha256")
    require("SUBJECT_AUTHORITY_ID_PRESENT", isinstance(authority_id, str) and bool(authority_id), True)
    require("SUBJECT_PUBLIC_KEY_SHA256", isinstance(public_key_sha, str) and len(public_key_sha) == 64, True)

    now = datetime.now(timezone.utc)
    rows = registry.get("revocations")
    rows = rows if isinstance(rows, list) else []
    active_matches: list[dict[str, Any]] = []
    malformed_rows = 0
    for row in rows:
        if not isinstance(row, dict):
            malformed_rows += 1
            continue
        revoked_at = parse_time(row.get("revoked_at"))
        valid = (
            isinstance(row.get("authority_id"), str)
            and isinstance(row.get("public_key_sha256"), str)
            and len(row.get("public_key_sha256")) == 64
            and revoked_at is not None
            and revoked_at <= now
            and isinstance(row.get("reason"), str)
            and bool(row.get("reason"))
            and isinstance(row.get("authorization_ref"), str)
            and bool(row.get("authorization_ref"))
        )
        if not valid:
            malformed_rows += 1
            continue
        if row.get("authority_id") == authority_id or row.get("public_key_sha256") == public_key_sha:
            active_matches.append(row)
    require("REGISTRY_ROWS_WELL_FORMED", malformed_rows, 0)
    if active_matches:
        failures.append(
            {
                "code": "AUTHORITY_OR_KEY_REVOKED",
                "actual": [
                    {
                        "authority_id": row.get("authority_id"),
                        "public_key_sha256": row.get("public_key_sha256"),
                        "revoked_at": row.get("revoked_at"),
                        "reason": row.get("reason"),
                    }
                    for row in active_matches
                ],
                "expected": [],
            }
        )

    status = "PASS_NOT_REVOKED" if not failures else "FAIL_CLOSED_AUTHORITY_OR_KEY_REVOKED"
    receipt = {
        "schema": "qingshan.e40.u12.v13.authority_revocation_gate.v1",
        "recorded_at": now.isoformat(),
        "status": status,
        "contract": args.contract,
        "contract_sha256": sha256_file(contract_path),
        "registry": args.registry,
        "registry_sha256": sha256_file(registry_path),
        "registry_serial": registry.get("serial"),
        "subject": args.subject,
        "subject_sha256": sha256_file(subject_path),
        "match_count": len(active_matches),
        "failure_count": len(failures),
        "failures": failures,
        "authority_admitted": False,
        "policy_changed": False,
        "failure_behavior": "NO_KEY_ADMISSION_NO_SOURCE_ADMISSION_NO_RENDER_NO_SUBMIT_NO_TRANSACTION_NO_CREDITS_NO_AGENTCUT_NO_ASSEMBLY",
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "match_count": len(active_matches), "out": args.out}, ensure_ascii=False))
    if args.expect_reject:
        return 0 if active_matches else 3
    return 0 if not failures else 2


if __name__ == "__main__":
    sys.exit(main())
