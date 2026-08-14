#!/usr/bin/env python3
"""Reconcile legacy Giggle video ledgers against exact task-id statements."""

from __future__ import annotations

import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from giggle_api_client import _get
from submit_giggle_task_manifest import ensure_giggle_api_key


ROOT = Path(__file__).resolve().parents[1]


def resolve(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def exact_statement(task_id: str) -> dict:
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", required=True)
    parser.add_argument("--ledger", action="append", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()

    if ensure_giggle_api_key() in {"MISSING", "UNSAFE_FILE_PERMISSIONS"}:
        raise RuntimeError("Giggle API key unavailable")

    ledgers = []
    indexed: dict[str, dict] = {}
    for ledger_arg in args.ledger:
        path = resolve(ledger_arg)
        raw = path.read_bytes()
        document = json.loads(raw)
        ledgers.append({
            "path": str(path.relative_to(ROOT)),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "episode": document.get("episode"),
            "scope": document.get("scope"),
        })
        for row in document.get("tasks") or []:
            if row.get("media_type") not in {"video", "unknown"} or not row.get("task_id"):
                continue
            task_id = str(row["task_id"])
            item = indexed.setdefault(task_id, {
                "task_id": task_id,
                "source_ids": [],
                "ledger_statuses": [],
                "ledger_media_types": [],
            })
            source_id = row.get("source_id") or Path(str(row.get("task_dir") or "")).name
            if source_id and source_id not in item["source_ids"]:
                item["source_ids"].append(source_id)
            for key, target in (("status", "ledger_statuses"), ("media_type", "ledger_media_types")):
                value = row.get(key)
                if value and value not in item[target]:
                    item[target].append(value)

    results = []
    errors = []
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        futures = {pool.submit(exact_statement, task_id): task_id for task_id in indexed}
        for future in as_completed(futures):
            task_id = futures[future]
            item = indexed[task_id]
            try:
                statement = future.result()
            except BaseException as exc:
                errors.append({"task_id": task_id, "error": str(exc)})
                continue
            if statement:
                credit = abs(Decimal(str(statement["credit"])))
                item.update({
                    "result": "EXACT_VIDEO_CHARGE",
                    "actual_charged_credits": int(credit) if credit == credit.to_integral() else str(credit),
                    "statement": statement,
                })
            elif set(item["ledger_statuses"]) == {"failed"}:
                item.update({"result": "EXPLICIT_FAILURE_ZERO", "actual_charged_credits": 0})
            else:
                item.update({"result": "NO_EXACT_VIDEO_STATEMENT_UNKNOWN", "actual_charged_credits": None})
            results.append(item)

    results.sort(key=lambda row: row["task_id"])
    unresolved = [row["task_id"] for row in results if row["actual_charged_credits"] is None]
    charged = [row for row in results if row["result"] == "EXACT_VIDEO_CHARGE"]
    failed_zero = [row for row in results if row["result"] == "EXPLICIT_FAILURE_ZERO"]
    total = sum(Decimal(str(row["actual_charged_credits"])) for row in charged)
    report = {
        "schema": "qingshan.legacy_video_credit_task_id_reconciliation.v1",
        "episode": args.episode.upper(),
        "status": "PASS" if not errors and not unresolved else "INCOMPLETE",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "endpoint": "/api/v1/payment/credit-statements",
        "method": "LEGACY_LEDGER_EXACT_PROJECT_ID_EQUALS_VIDEO_TASK_ID",
        "source_ledgers": ledgers,
        "queried_task_count": len(indexed),
        "charged_task_count": len(charged),
        "failed_zero_charge_count": len(failed_zero),
        "unresolved_task_ids": unresolved,
        "actual_charged_credits_known_total": int(total) if total == total.to_integral() else str(total),
        "errors": errors,
        "tasks": results,
        "generation_call_count": 0,
        "new_credits": 0,
    }
    out = resolve(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "queried": report["queried_task_count"],
        "charged": report["charged_task_count"],
        "failed_zero": report["failed_zero_charge_count"],
        "unresolved": len(unresolved),
        "credits": report["actual_charged_credits_known_total"],
        "report": str(out),
    }, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
