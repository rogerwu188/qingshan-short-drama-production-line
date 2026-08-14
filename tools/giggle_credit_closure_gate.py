#!/usr/bin/env python3
"""Validate Giggle credit ledgers before release-finance closure."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def validate(ledger: dict[str, Any], require_actual_credits: bool = False) -> dict[str, Any]:
    failures: list[str] = []
    tasks = ledger.get("tasks") or []
    submitted = int(ledger.get("submitted_task_count", -1))
    image_count = int(ledger.get("image_task_count", -1))
    video_count = int(ledger.get("video_task_count", -1))
    unknown_count = int(ledger.get("unknown_media_task_count", 0))
    if ledger.get("schema") != "qingshan.giggle_credit_ledger.v1":
        failures.append("invalid_schema")
    if submitted != len(tasks):
        failures.append(f"submitted_task_count_mismatch:{submitted}:{len(tasks)}")
    if image_count + video_count + unknown_count != submitted:
        failures.append("media_task_count_sum_mismatch")
    task_ids = [row.get("task_id") for row in tasks if row.get("task_id")]
    if len(task_ids) != len(set(task_ids)):
        failures.append("duplicate_task_id")
    actual = ledger.get("actual_credits_total")
    if require_actual_credits and not isinstance(actual, int):
        failures.append("actual_credits_total_not_reconciled")
    before = ledger.get("balance_before")
    after = ledger.get("balance_after")
    if isinstance(actual, int) and isinstance(before, int) and isinstance(after, int):
        if before - after != actual:
            failures.append("balance_delta_does_not_match_actual_credits")
    return {
        "schema": "qingshan.giggle_credit_closure_gate.v1",
        "status": "PASS" if not failures else "FAIL",
        "require_actual_credits": require_actual_credits,
        "submitted_task_count": submitted,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--require-actual-credits", action="store_true")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    ledger = json.loads(Path(args.ledger).read_text(encoding="utf-8"))
    report = validate(ledger, args.require_actual_credits)
    Path(args.out).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": report["status"], "failures": report["failures"]}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
