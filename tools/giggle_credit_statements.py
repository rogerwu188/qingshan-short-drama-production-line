#!/usr/bin/env python3
"""Fetch and reconcile Giggle's authoritative credit statement ledger."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

try:
    from giggle_api_client import _get
except ModuleNotFoundError:  # Imported as tools.giggle_credit_statements.
    from tools.giggle_api_client import _get


ROOT = Path(__file__).resolve().parents[1]
STATEMENT_PATH = "/api/v1/payment/credit-statements"


def resolve(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def parse_utc(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    normalized = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", normalized)
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_statement_time(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def fetch_pay_statements(page_size: int = 100) -> list[dict[str, Any]]:
    response = _get(
        STATEMENT_PATH,
        {"credit_type": "Pay", "page": 1, "page_size": page_size, "project_id": ""},
    )
    if response.get("code") != 200:
        raise RuntimeError(f"Credit statement request failed: {response}")
    data = response.get("data") or {}
    rows = data.get("list") or []
    if not isinstance(rows, list):
        raise RuntimeError("Credit statement response data.list is not a list")
    return rows


def fetch_video_credit_by_task_id(task_id: str) -> dict[str, Any]:
    """Return the exact authoritative video charge for one completed task."""
    response = _get(
        STATEMENT_PATH,
        {"credit_type": "Pay", "page": 1, "page_size": 20, "project_id": task_id},
    )
    if response.get("code") != 200:
        raise RuntimeError(f"Credit statement request failed for {task_id}: {response}")
    rows = (response.get("data") or {}).get("list") or []
    matches = [
        row for row in rows
        if str(row.get("project_id") or "") == str(task_id)
        and row.get("event_type") == "Pay"
        and row.get("event_description") == "SingleGenerateVideo"
    ]
    total = Decimal("0")
    invalid = []
    for row in matches:
        try:
            total += abs(Decimal(str(row["credit"])))
        except (KeyError, InvalidOperation):
            invalid.append(row)
    status = "PASS" if matches and not invalid else "INCOMPLETE"
    charged = int(total) if total == total.to_integral() else str(total)
    return {
        "status": status,
        "endpoint": STATEMENT_PATH,
        "method": "EXACT_PROJECT_ID_EQUALS_VIDEO_TASK_ID",
        "task_id": str(task_id),
        "matched_count": len(matches),
        "invalid_credit_rows": len(invalid),
        "charged_credits": charged if status == "PASS" else None,
        "statement_rows": matches,
    }


def fetch_task_credit_net_by_task_id(
    task_id: str,
    *,
    event_description: str | None = None,
) -> dict[str, Any]:
    """Return authoritative Pay/Refund rows and net cost for one task.

    Failed remote generations can briefly create a Pay row before a matching
    Refund row appears. Cost evidence therefore has to use the complete task
    ledger instead of inferring zero from lifecycle status or reading Pay only.
    """
    response = _get(
        STATEMENT_PATH,
        {"page": 1, "page_size": 100, "project_id": task_id},
    )
    if response.get("code") != 200:
        raise RuntimeError(f"Credit statement request failed for {task_id}: {response}")
    rows = [
        row
        for row in (response.get("data") or {}).get("list") or []
        if str(row.get("project_id") or "") == str(task_id)
        and (event_description is None or row.get("event_description") == event_description)
        and row.get("event_type") in {"Pay", "Refund"}
    ]
    invalid = []
    paid = Decimal("0")
    refunded = Decimal("0")
    for row in rows:
        try:
            amount = abs(Decimal(str(row["credit"])))
        except (KeyError, InvalidOperation):
            invalid.append(row)
            continue
        if row.get("event_type") == "Pay":
            paid += amount
        else:
            refunded += amount
    net = paid - refunded
    if invalid or not rows:
        status = "INCOMPLETE"
    elif net < 0:
        status = "INVALID_NEGATIVE_NET"
    elif paid > 0 and net == 0:
        status = "PASS_ZERO_REFUNDED"
    elif paid > 0:
        status = "PASS_CHARGED"
    else:
        status = "INCOMPLETE"

    def number(value: Decimal) -> int | str:
        return int(value) if value == value.to_integral() else str(value)

    return {
        "status": status,
        "endpoint": STATEMENT_PATH,
        "method": "EXACT_PROJECT_ID_PAY_MINUS_REFUND",
        "task_id": str(task_id),
        "event_description": event_description,
        "paid_credits": number(paid),
        "refunded_credits": number(refunded),
        "net_charged_credits": number(net),
        "matched_count": len(rows),
        "invalid_credit_rows": len(invalid),
        "statement_rows": rows,
    }


def reconcile_rows(
    rows: list[dict[str, Any]],
    *,
    start: datetime,
    end: datetime,
    expected_count: int,
    event_description: str,
    model: str,
) -> dict[str, Any]:
    matches = []
    for row in rows:
        if row.get("event_type") != "Pay":
            continue
        if row.get("event_description") != event_description:
            continue
        if row.get("model") != model:
            continue
        created = parse_statement_time(str(row.get("created_at", "")))
        if start <= created <= end:
            matches.append(row)
    matches.sort(key=lambda row: row["created_at"])

    total = Decimal("0")
    invalid_credit_rows = 0
    for row in matches:
        try:
            total += abs(Decimal(str(row["credit"])))
        except (KeyError, InvalidOperation):
            invalid_credit_rows += 1

    exact_count = len(matches) == expected_count
    exact_credits = invalid_credit_rows == 0
    return {
        "status": "PASS" if exact_count and exact_credits else "FAIL",
        "endpoint": STATEMENT_PATH,
        "method": "BATCH_TIME_WINDOW_EVENT_MODEL_EXACT_COUNT",
        "window_start_utc": start.isoformat().replace("+00:00", "Z"),
        "window_end_utc": end.isoformat().replace("+00:00", "Z"),
        "event_description": event_description,
        "model": model,
        "expected_count": expected_count,
        "matched_count": len(matches),
        "invalid_credit_rows": invalid_credit_rows,
        "charged_credits": int(total) if total == total.to_integral() else str(total),
        "statement_rows": matches,
        "limitation": "Giggle credit statements omit image task_id; evidence is batch-level and requires an isolated UTC window with exact event/model/count matching.",
    }


def update_harvest_report(path: Path, reconciliation: dict[str, Any]) -> None:
    report = json.loads(path.read_text(encoding="utf-8"))
    if reconciliation["status"] != "PASS":
        raise RuntimeError("Refusing to update harvest report from a failed reconciliation")
    expected = reconciliation["expected_count"]
    results = report.get("results") or []
    if len(results) != expected:
        raise RuntimeError(f"Harvest result count {len(results)} does not match expected {expected}")
    per_item = Decimal(str(reconciliation["charged_credits"])) / Decimal(expected)
    if per_item != per_item.to_integral():
        raise RuntimeError("Batch credits do not divide evenly across successful image results")
    report["credit_known_total"] = reconciliation["charged_credits"]
    report["credit_unknown_success_count"] = 0
    report["credit_reconciliation"] = reconciliation
    for row in results:
        row["credit"] = int(per_item)
        row["credit_status"] = "KNOWN_BATCH_LEDGER_EXACT_COUNT"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True, help="Inclusive UTC ISO timestamp")
    parser.add_argument("--end", required=True, help="Inclusive UTC ISO timestamp")
    parser.add_argument("--expected-count", type=int, required=True)
    parser.add_argument("--event-description", default="SingleGenerateImage")
    parser.add_argument("--model", default="gpt-image-2-pro")
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--out", required=True)
    parser.add_argument("--harvest-report")
    args = parser.parse_args()

    result = reconcile_rows(
        fetch_pay_statements(args.page_size),
        start=parse_utc(args.start),
        end=parse_utc(args.end),
        expected_count=args.expected_count,
        event_description=args.event_description,
        model=args.model,
    )
    out = resolve(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.harvest_report:
        update_harvest_report(resolve(args.harvest_report), result)
    print(json.dumps({key: result[key] for key in ("status", "matched_count", "charged_credits")}, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
