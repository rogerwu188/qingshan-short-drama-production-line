#!/usr/bin/env python3
"""Reconcile an episode's historical successful video calls to Giggle statements."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

from episode_video_generation_guard import _episode_video_attempts
from giggle_api_client import _get
from giggle_credit_statements import parse_statement_time, parse_utc
from submit_giggle_task_manifest import ensure_giggle_api_key


ROOT = Path(__file__).resolve().parents[1]


def fetch_page(page: int) -> list[dict]:
    response = _get(
        "/api/v1/payment/credit-statements",
        {"credit_type": "Pay", "page": page, "page_size": 10, "project_id": ""},
    )
    if response.get("code") != 200:
        raise RuntimeError(f"credit page {page} failed: {response}")
    return list((response.get("data") or {}).get("list") or [])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--first-page", type=int, required=True)
    parser.add_argument("--last-page", type=int, required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    if ensure_giggle_api_key() in {"MISSING", "UNSAFE_FILE_PERMISSIONS"}:
        raise RuntimeError("Giggle API key is unavailable")
    start = parse_utc(args.start) - timedelta(seconds=10)
    end = parse_utc(args.end) + timedelta(seconds=10)
    pages = list(range(args.first_page, args.last_page + 1))
    with ThreadPoolExecutor(max_workers=min(8, len(pages))) as pool:
        fetched = list(pool.map(fetch_page, pages))
    rows = [row for page in fetched for row in page]
    matches = [
        row for row in rows
        if row.get("event_type") == "Pay"
        and row.get("event_description") == "SingleGenerateVideo"
        and row.get("model") == "seedance-2.0-pro"
        and start <= parse_statement_time(str(row.get("created_at"))) <= end
    ]
    matches.sort(key=lambda row: row["created_at"])

    successful = [
        row for row in _episode_video_attempts(args.episode)
        if row.get("success") is True
    ]
    covered_ids = sorted(str(row["task_id"]) for row in successful if row.get("task_id"))
    charged = sum(abs(float(row["credit"])) for row in matches)
    exact_count = len(matches) == len(covered_ids)
    report = {
        "schema": "qingshan.episode_video_credit_history_reconciliation.v1",
        "episode": args.episode.upper(),
        "status": "PASS" if exact_count else "FAIL",
        "endpoint": "/api/v1/payment/credit-statements",
        "method": "EPISODE_ISOLATED_TIME_WINDOW_EVENT_MODEL_EXACT_COUNT",
        "window_start_utc": start.isoformat().replace("+00:00", "Z"),
        "window_end_utc": end.isoformat().replace("+00:00", "Z"),
        "pages": [args.first_page, args.last_page],
        "expected_success_count": len(covered_ids),
        "matched_statement_count": len(matches),
        "charged_credits": int(charged) if float(charged).is_integer() else charged,
        "covered_task_ids": covered_ids,
        "statement_rows": matches,
        "limitation": (
            "Giggle statements omit video task_id. This binds the exact episode total only when the isolated "
            "time window, event, model and successful-call count all match; it does not invent per-task mapping."
        ),
    }
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "expected": len(covered_ids),
        "matched": len(matches),
        "charged_credits": report["charged_credits"],
        "out": str(out),
    }, ensure_ascii=False))
    return 0 if exact_count else 2


if __name__ == "__main__":
    raise SystemExit(main())
