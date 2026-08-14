#!/usr/bin/env python3
"""Audit an account statement window against locally reconciled video task ids."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from giggle_api_client import _get
from submit_giggle_task_manifest import ensure_giggle_api_key


ROOT = Path(__file__).resolve().parents[1]


def resolve(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def parse_time(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def fetch_page(page: int, page_size: int) -> dict:
    response = _get(
        "/api/v1/payment/credit-statements",
        {"credit_type": "Pay", "page": page, "page_size": page_size, "project_id": ""},
    )
    if response.get("code") != 200:
        raise RuntimeError(f"credit page {page} failed")
    return {"page": page, "rows": list((response.get("data") or {}).get("list") or [])}


def known_video_task_ids(paths: list[Path]) -> set[str]:
    task_ids: set[str] = set()
    for path in paths:
        document = json.loads(path.read_text(encoding="utf-8"))
        for row in document.get("tasks") or []:
            task_id = row.get("task_id")
            if task_id:
                task_ids.add(str(task_id))
        for row in document.get("results") or []:
            if row.get("classification") == "EXACT_VIDEO_CHARGE" and row.get("task_id"):
                task_ids.add(str(row["task_id"]))
    return task_ids


def credit_total(rows: list[dict]) -> Decimal:
    return sum((abs(Decimal(str(row["credit"]))) for row in rows), Decimal("0"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--known-report", action="append", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--first-page", type=int, required=True)
    parser.add_argument("--last-page", type=int, required=True)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    if ensure_giggle_api_key() in {"MISSING", "UNSAFE_FILE_PERMISSIONS"}:
        raise RuntimeError("Giggle API key unavailable")

    start = datetime.fromisoformat(args.start.replace("Z", "+00:00")).astimezone(timezone.utc)
    end = datetime.fromisoformat(args.end.replace("Z", "+00:00")).astimezone(timezone.utc)
    report_paths = [resolve(value) for value in args.known_report]
    known_ids = known_video_task_ids(report_paths)
    pages = list(range(args.first_page, args.last_page + 1))
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        fetched = list(pool.map(lambda page: fetch_page(page, args.page_size), pages))

    all_rows = [row for page in fetched for row in page["rows"]]
    window_rows = [
        row for row in all_rows
        if row.get("event_type") == "Pay"
        and row.get("event_description") == "SingleGenerateVideo"
        and start <= parse_time(str(row.get("created_at"))) <= end
    ]
    window_rows.sort(key=lambda row: (row.get("created_at", ""), row.get("project_id", "")))
    duplicate_statement_project_ids = sorted({
        task_id for task_id in (str(row.get("project_id") or "") for row in window_rows)
        if task_id and sum(str(item.get("project_id") or "") == task_id for item in window_rows) > 1
    })
    matched = [row for row in window_rows if str(row.get("project_id") or "") in known_ids]
    unmatched = [row for row in window_rows if str(row.get("project_id") or "") not in known_ids]
    matched_known_ids = {str(row.get("project_id") or "") for row in matched}
    known_ids_missing_from_window = sorted(known_ids - matched_known_ids)

    if known_ids_missing_from_window:
        status = "FAIL_KNOWN_TASK_IDS_MISSING_FROM_WINDOW"
    elif unmatched:
        status = "PASS_WITH_UNMATCHED_ROWS"
    else:
        status = "PASS"

    report = {
        "schema": "qingshan.account_video_credit_window_audit.v1",
        "status": status,
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "endpoint": "/api/v1/payment/credit-statements",
        "method": "ACCOUNT_WINDOW_SINGLEGENERATEVIDEO_PROJECT_ID_SET_RECONCILIATION",
        "window_start_utc": start.isoformat().replace("+00:00", "Z"),
        "window_end_utc": end.isoformat().replace("+00:00", "Z"),
        "pages": [args.first_page, args.last_page],
        "page_size": args.page_size,
        "fetched_statement_row_count": len(all_rows),
        "known_report_paths": [str(path.relative_to(ROOT)) for path in report_paths],
        "known_unique_video_task_id_count": len(known_ids),
        "window_video_statement_count": len(window_rows),
        "window_video_statement_credits": int(credit_total(window_rows)),
        "matched_known_video_statement_count": len(matched),
        "matched_known_video_statement_credits": int(credit_total(matched)),
        "unmatched_video_statement_count": len(unmatched),
        "unmatched_video_statement_credits": int(credit_total(unmatched)),
        "multi_charge_project_ids": duplicate_statement_project_ids,
        "multi_charge_project_id_policy": "Retain every authoritative statement row; repeated project ids are evidence of multiple charges, not an audit failure.",
        "known_video_task_ids_missing_from_window": known_ids_missing_from_window,
        "unmatched_video_statements": unmatched,
        "generation_call_count": 0,
        "new_credits": 0
    }
    out = resolve(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "known_ids": len(known_ids),
        "window_video_rows": len(window_rows),
        "matched": len(matched),
        "unmatched": len(unmatched),
        "unmatched_credits": report["unmatched_video_statement_credits"],
        "out": str(out)
    }, ensure_ascii=False))
    return 2 if known_ids_missing_from_window else 0


if __name__ == "__main__":
    raise SystemExit(main())
