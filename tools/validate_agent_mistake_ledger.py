#!/usr/bin/env python3
"""Validate the append-only agent mistake and anti-recurrence ledger."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


REQUIRED = {
    "mistake_id", "date", "episode", "summary", "impact", "root_cause",
    "evidence_refs", "do_not_repeat", "prevention", "code_ref", "test_ref",
    "gate_ref", "status",
}
STATUS_PREFIXES = ("OPEN", "PARTIAL", "CLOSED")
SECRET_PATTERNS = [re.compile(r"sk_(?:prod|test)_[A-Za-z0-9+/=]{12,}"), re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{12,}", re.I)]


def valid_status(value: object) -> bool:
    return isinstance(value, str) and any(
        value == prefix or value.startswith(prefix + "_") for prefix in STATUS_PREFIXES
    )


def closed_status(value: object) -> bool:
    return isinstance(value, str) and (value == "CLOSED" or value.startswith("CLOSED_"))


def validate(payload: dict) -> list[str]:
    errors: list[str] = []
    rows = payload.get("mistakes")
    if not isinstance(rows, list) or not rows:
        return ["mistakes_missing_or_empty"]
    serialized = json.dumps(payload, ensure_ascii=False)
    for pattern in SECRET_PATTERNS:
        if pattern.search(serialized):
            errors.append("secret_like_material_forbidden")
    seen: set[str] = set()
    for index, row in enumerate(rows, 1):
        prefix = f"row_{index}"
        missing = sorted(key for key in REQUIRED if key not in row or row[key] in (None, "", []))
        if missing:
            errors.append(f"{prefix}:missing:{','.join(missing)}")
        mistake_id = str(row.get("mistake_id", ""))
        expected = f"ERR-{index:03d}"
        if mistake_id != expected:
            errors.append(f"{prefix}:id_expected:{expected}:got:{mistake_id}")
        if mistake_id in seen:
            errors.append(f"{prefix}:duplicate_id:{mistake_id}")
        seen.add(mistake_id)
        if not valid_status(row.get("status")):
            errors.append(f"{prefix}:invalid_status:{row.get('status')}")
        if closed_status(row.get("status")):
            for key in ("evidence_refs", "code_ref", "test_ref", "gate_ref", "prevention"):
                if not row.get(key):
                    errors.append(f"{prefix}:closed_without:{key}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", default="workflow/agent_mistake_ledger.json")
    parser.add_argument("--out")
    args = parser.parse_args()
    path = Path(args.ledger)
    payload = json.loads(path.read_text(encoding="utf-8"))
    errors = validate(payload)
    report = {
        "schema": "qingshan.agent_mistake_ledger_validation.v1",
        "ledger": str(path),
        "status": "PASS" if not errors else "FAIL",
        "mistake_count": len(payload.get("mistakes", [])),
        "open_count": sum(not closed_status(row.get("status")) for row in payload.get("mistakes", [])),
        "errors": errors,
    }
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
