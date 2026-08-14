#!/usr/bin/env python3
"""Build one receipt-backed ledger row for every remote generation attempt."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

try:
    from episode_parallel_batch_supervisor import extract_credit_observation, now
except ModuleNotFoundError:  # Imported as tools.build_remote_generation_credit_ledger.
    from tools.episode_parallel_batch_supervisor import extract_credit_observation, now


ROOT = Path(__file__).resolve().parents[1]
SUCCESS = {"qa_pass", "qa_failed_terminal", "image_pass", "complete"}
FAILURE = {"remote_failed_terminal", "submit_failed_terminal"}


def inferred_legacy_attempt(task: dict) -> dict | None:
    if task.get("tool_type") not in {"video_generation", "image_generation"}:
        return None
    if not task.get("task_id") and not task.get("submit_response"):
        return None
    observed = extract_credit_observation(task.get("submit_response") or {})
    state = str(task.get("state") or task.get("status") or "unknown")
    remote_status = str(task.get("remote_status") or "").lower()
    output_exists = bool(task.get("output_path"))
    if state in FAILURE or remote_status in {"failed", "error", "cancelled", "timeout"}:
        charge_status = "FAILED_ZERO_CHARGE"
        actual = 0
        success = False
    elif state in SUCCESS or remote_status == "completed" or output_exists:
        charge_status = "SUCCESS_ACTUAL_CHARGE_RECORDED" if observed else "SUCCESS_CREDIT_UNKNOWN_API_FIELD_MISSING"
        actual = observed["credits"] if observed else None
        success = True
    else:
        charge_status = "PENDING_REMOTE_RESULT"
        actual = None
        success = None
    return {
        "attempt": 1,
        "task_id": task.get("task_id"),
        "tool_type": task.get("tool_type"),
        "submitted_at": task.get("submitted_at"),
        "returned_credit": observed.get("credits") if observed else None,
        "credit_response_path": observed.get("response_path") if observed else None,
        "charge_status": charge_status,
        "actual_charged_credits": actual,
        "success": success,
        "evidence": "legacy_receipt_backfill",
    }


def build(tasks_root: Path) -> dict:
    rows = []
    for receipt_path in sorted(tasks_root.rglob("*.json")):
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(receipt, dict) or not isinstance(receipt.get("tasks"), list):
            continue
        episode = str(receipt.get("episode") or "UNKNOWN")
        for task in receipt["tasks"]:
            attempts = task.get("credit_attempts") or []
            if not attempts:
                legacy = inferred_legacy_attempt(task)
                attempts = [legacy] if legacy else []
            for attempt in attempts:
                rows.append(
                    {
                        "episode": episode,
                        "task_key": task.get("task_key"),
                        "source_id": task.get("source_id") or task.get("dialogue_id") or task.get("dia_id"),
                        "receipt": str(receipt_path),
                        **attempt,
                    }
                )
    by_episode = defaultdict(lambda: {"attempt_count": 0, "known_actual_credits": 0, "unknown_success_count": 0, "failed_zero_charge_count": 0})
    for row in rows:
        summary = by_episode[row["episode"]]
        summary["attempt_count"] += 1
        actual = row.get("actual_charged_credits")
        if isinstance(actual, (int, float)):
            summary["known_actual_credits"] += actual
        if row.get("charge_status") == "SUCCESS_CREDIT_UNKNOWN_API_FIELD_MISSING":
            summary["unknown_success_count"] += 1
        if row.get("charge_status") == "FAILED_ZERO_CHARGE":
            summary["failed_zero_charge_count"] += 1
    return {
        "schema": "qingshan.remote_generation_action_credit_ledger.v1",
        "generated_at": now(),
        "policy": "One row per remote generation attempt; explicit API values only; failed attempts cost zero; no estimation.",
        "attempt_count": len(rows),
        "actual_credits_known_total": sum(
            row["actual_charged_credits"]
            for row in rows
            if isinstance(row.get("actual_charged_credits"), (int, float))
        ),
        "actual_total_complete": all(row.get("actual_charged_credits") is not None for row in rows),
        "episodes": dict(sorted(by_episode.items())),
        "actions": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks-root", type=Path, default=ROOT / "workflow/tasks")
    parser.add_argument("--out", type=Path, default=ROOT / "workflow/credit_reports/REMOTE_GENERATION_ACTION_CREDIT_LEDGER.json")
    args = parser.parse_args()
    report = build(args.tasks_root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "out": str(args.out), "attempt_count": report["attempt_count"], "actual_total_complete": report["actual_total_complete"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
