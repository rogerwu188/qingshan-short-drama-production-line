#!/usr/bin/env python3
"""Reconcile historical video credits against Giggle by exact task id."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from episode_video_generation_guard import _episode_video_attempts
from giggle_api_client import _get
from submit_giggle_task_manifest import ensure_giggle_api_key


ROOT = Path(__file__).resolve().parents[1]


def statement_for(task_id: str) -> dict:
    response = _get(
        "/api/v1/payment/credit-statements",
        {"credit_type": "Pay", "page": 1, "page_size": 10, "project_id": task_id},
    )
    if response.get("code") != 200:
        raise RuntimeError(f"credit statement query failed for {task_id}")
    rows = [
        row for row in ((response.get("data") or {}).get("list") or [])
        if str(row.get("project_id")) == task_id
        and row.get("event_description") == "SingleGenerateVideo"
    ]
    if len(rows) > 1:
        raise RuntimeError(f"multiple video charges found for task {task_id}")
    return rows[0] if rows else {}


def reconcile(row: dict) -> dict:
    task_id = str(row["task_id"])
    statement = statement_for(task_id)
    task = {
        "task_key": row.get("task_key") or f"RECONCILED-{task_id}",
        "source_id": row.get("source_id"),
        "tool_type": "video_generation",
        "task_id": task_id,
        "credit_attempts": [],
    }
    if statement:
        credit = abs(float(statement["credit"]))
        if credit.is_integer():
            credit = int(credit)
        task.update({"state": "remote_completed_credit_reconciled", "remote_status": "completed"})
        task["credit_attempts"] = [{
            "attempt": row.get("attempt", 1),
            "task_id": task_id,
            "success": True,
            "actual_charged_credits": credit,
            "returned_credit": credit,
            "charge_status": "EXACT_TASK_ID_STATEMENT_MATCH",
            "credit_response_path": "/api/v1/payment/credit-statements",
            "statement_created_at": statement.get("created_at"),
            "statement_project_id": statement.get("project_id"),
            "evidence": "credit_statement_project_id_equals_task_id",
        }]
        task["statement"] = statement
        return task

    task.update({"state": "successful_receipt_missing_exact_statement", "remote_status": "completed"})
    task["credit_attempts"] = [{
        "attempt": row.get("attempt", 1),
        "task_id": task_id,
        "success": True,
        "actual_charged_credits": None,
        "charge_status": "SUCCESSFUL_RECEIPT_NO_EXACT_TASK_ID_STATEMENT",
        "evidence": "/api/v1/payment/credit-statements",
    }]
    return task


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument(
        "--task-id",
        action="append",
        default=[],
        help="Reconcile only these exact video task ids; may be repeated.",
    )
    args = parser.parse_args()
    if ensure_giggle_api_key() in {"MISSING", "UNSAFE_FILE_PERMISSIONS"}:
        raise RuntimeError("Giggle API key unavailable")

    all_attempts = _episode_video_attempts(args.episode)
    source_rows = [
        row for row in all_attempts
        if row.get("task_id") and row.get("success") is True
    ]
    if args.task_id:
        known = {str(row["task_id"]): row for row in source_rows}
        source_rows = [
            known.get(task_id, {"task_id": task_id, "success": True})
            for task_id in args.task_id
        ]
    by_id = {str(row["task_id"]): row for row in source_rows}
    tasks = []
    errors = []
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        futures = {pool.submit(reconcile, row): task_id for task_id, row in by_id.items()}
        for future in as_completed(futures):
            task_id = futures[future]
            try:
                tasks.append(future.result())
            except BaseException as exc:
                errors.append({"task_id": task_id, "error": str(exc)})
    tasks.sort(key=lambda row: row["task_id"])
    charged = [
        attempt["actual_charged_credits"]
        for task in tasks
        for attempt in task["credit_attempts"]
        if attempt.get("success") is True
    ]
    unresolved = [
        task["task_id"] for task in tasks
        if task["credit_attempts"][0].get("actual_charged_credits") is None
    ]
    pending = [
        str(row["task_id"]) for row in all_attempts
        if row.get("task_id") and row.get("success") is None
    ]
    report = {
        "schema": "qingshan.episode_video_credit_task_id_reconciliation.v1",
        "episode": args.episode.upper(),
        "status": "PASS" if not errors and not unresolved else "INCOMPLETE",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "endpoint": "/api/v1/payment/credit-statements",
        "method": "EXACT_PROJECT_ID_EQUALS_VIDEO_TASK_ID",
        "queried_task_count": len(by_id),
        "charged_task_count": len(charged),
        "failed_zero_charge_count": sum(1 for row in all_attempts if row.get("success") is False),
        "pending_task_ids_not_charged_or_counted": sorted(pending),
        "unresolved_task_ids": unresolved,
        "actual_charged_credits_known_total": sum(charged),
        "errors": errors,
        "tasks": tasks,
    }
    output = Path(args.out)
    if not output.is_absolute():
        output = ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "queried": report["queried_task_count"],
        "charged": report["charged_task_count"],
        "failed_zero": report["failed_zero_charge_count"],
        "unresolved": len(unresolved),
        "credits": report["actual_charged_credits_known_total"],
        "report": str(output),
    }, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
