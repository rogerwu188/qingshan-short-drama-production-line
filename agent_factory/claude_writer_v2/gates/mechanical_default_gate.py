#!/usr/bin/env python3
"""Block unreviewed global defaults and mechanically uniform unit plans."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


VARIABLE_FIELDS = {
    "duration_seconds",
    "planned_reference_image_count",
    "camera",
    "camera_policy",
    "space",
    "scene_id",
    "weather",
    "dialogue_sentence_count",
    "prompt_sha256",
}
APPROVAL_REF = re.compile(r"^(?:CL2X|ROGER)-[A-Za-z0-9_-]+$")


def _value(unit: dict[str, Any], field: str) -> Any:
    current: Any = unit
    for part in field.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    units = [row for row in payload.get("units") or [] if isinstance(row, dict)]
    if not units:
        failures.append("units_missing")

    for row in payload.get("global_defaults") or []:
        field = str(row.get("field") or "")
        if field in VARIABLE_FIELDS and not APPROVAL_REF.fullmatch(str(row.get("supervisor_approval_ref") or "")):
            failures.append(f"unreviewed_global_default:{field}")

    audits = payload.get("mechanical_default_independence_audit") or {}
    checked_fields = set(payload.get("variable_fields") or VARIABLE_FIELDS)
    for field in sorted(checked_fields & VARIABLE_FIELDS):
        values = [_value(unit, field) for unit in units]
        present = [value for value in values if value is not None]
        if len(present) < 4 or len({json.dumps(value, ensure_ascii=False, sort_keys=True) for value in present}) != 1:
            continue
        audit = audits.get(field) if isinstance(audits, dict) else None
        if not isinstance(audit, dict) or audit.get("status") != "PASS":
            failures.append(f"uniform_variable_without_independence_audit:{field}")
            continue
        if audit.get("evaluated_individually") is not True:
            failures.append(f"uniform_variable_not_individually_evaluated:{field}")
        if int(audit.get("distinct_basis_count") or 0) < 2:
            failures.append(f"uniform_variable_has_single_basis:{field}")
        if len(str(audit.get("rationale") or "").strip()) < 30:
            failures.append(f"uniform_variable_audit_rationale_too_short:{field}")

    return {
        "schema": "qingshan.mechanical_default_gate.v1",
        "status": "PASS" if not failures else "FAIL",
        "unit_count": len(units),
        "checked_variable_fields": sorted(checked_fields & VARIABLE_FIELDS),
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = evaluate(json.loads(args.plan.read_text(encoding="utf-8")))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
