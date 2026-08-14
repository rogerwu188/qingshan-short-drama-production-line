#!/usr/bin/env python3
"""Audit V72-V74 scheduler terminal/evidence continuity locally."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "workflow/production_line/E40_TASK_LANES_V1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    payload = json.loads(STATE.read_text())
    rows = []
    for task in payload.get("tasks", []):
        match = re.match(r"E40-U12-V(7[234])-", task.get("task_id", ""))
        if not match:
            continue
        evidence = ROOT / task.get("evidence_ref", "")
        checks = {
            "terminal": task.get("state") == "TERMINAL",
            "evidence_exists": evidence.is_file(),
            "evidence_sha_exact": evidence.is_file()
            and sha256(evidence) == task.get("evidence_sha256"),
            "authorization_false": task.get("authorization") is False
            and task.get("maximum_new_submissions") == 0,
        }
        rows.append(
            {
                "version": int(match.group(1)),
                "task_id": task["task_id"],
                "evidence_ref": task.get("evidence_ref"),
                "checks": checks,
                "passed": all(checks.values()),
            }
        )
    rows.sort(key=lambda row: row["version"])
    ok = [row["version"] for row in rows] == [72, 73, 74] and all(
        row["passed"] for row in rows
    )
    result = {
        "schema": "qingshan.e40.u12.v75.audit.v1",
        "status": "PASS_V72_V74_3_OF_3_TERMINAL_EVIDENCE_EXACT" if ok else "FAIL",
        "rows": rows,
        "passed": sum(row["passed"] for row in rows),
        "total": 3,
        "authorization": False,
        "maximum_new_submissions": 0,
        "provider_calls": 0,
        "transactions": 0,
        "credits": 0,
    }
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
