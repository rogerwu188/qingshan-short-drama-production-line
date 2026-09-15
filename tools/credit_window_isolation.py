#!/usr/bin/env python3
"""Per-transaction credit isolation by submit window (standard library, no network).

Some provider charge types are booked without any per-task project id, so the
exact per-task statement query can never match them.  When the tasks were
submitted SEQUENTIALLY, each transaction still owns a half-open submit window
[intent, response) on the provider clock: every statement row booked inside
that window belongs to that transaction and to no other.

Rules (all fail closed):
  * windows are half-open; a row stamped exactly at ``response`` belongs to the
    NEXT transaction, because tx N's response stamp is tx N+1's intent stamp;
  * any two windows that overlap fail both transactions (FAIL_WINDOW_OVERLAP);
  * the statement page must reach back to before the window start, otherwise
    rows may be missing (FAIL_STATEMENT_PAGE_TOO_SHORT);
  * exactly one Pay row of the watched event must sit inside the window
    (FAIL_WINDOW_PAY_ROW_COUNT_<n>);
  * the result carries the DISTINCT label ``PASS_WINDOW_ISOLATED_LEDGER_NET``
    and ``isolation = SUBMIT_WINDOW``; it is never the exact-per-task label.

Whether a release gate accepts the window label is a deployment owner's
policy decision; this module only computes the evidence.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path

ISOLATION = "SUBMIT_WINDOW"
PASS_STATUS = "PASS_WINDOW_ISOLATED"
PASS_LABEL = "PASS_WINDOW_ISOLATED_LEDGER_NET"
EXACT_LABEL_NEVER_EMITTED = "PASS_EXACT_ISOLATED_LEDGER_NET"
STATEMENT_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
DEFAULT_EVENT_TYPES = ("Pay", "Refund")


def parse_iso_utc(value: str) -> datetime:
    """Parse an ISO-8601 stamp (``Z`` or offset) into an aware UTC datetime."""
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    stamp = datetime.fromisoformat(text)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def parse_statement_utc(value: str) -> datetime:
    """Parse a provider statement ``created_at`` (``YYYY-MM-DD HH:MM:SS``, UTC)."""
    return datetime.strptime(str(value).strip(), STATEMENT_TIME_FORMAT).replace(tzinfo=timezone.utc)


def _field(row: dict, *names: str):
    for name in names:
        if row.get(name) not in (None, ""):
            return row[name]
    return None


def _window(tx: dict) -> tuple[datetime, datetime] | None:
    intent = _field(tx, "intent", "intent_recorded_at")
    response = _field(tx, "response", "response_recorded_at")
    if intent is None or response is None:
        return None
    try:
        start, end = parse_iso_utc(intent), parse_iso_utc(response)
    except ValueError:
        return None
    if end < start:
        return None
    return start, end


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def isolate_credit_windows(transactions: list[dict], statement_rows: list[dict], *,
                           event_description: str | None = None,
                           event_types: tuple[str, ...] = DEFAULT_EVENT_TYPES,
                           slack: timedelta = timedelta(0)) -> list[dict]:
    """Return one evidence dict per transaction, in input order.

    ``transactions``: dicts with ``key`` plus ``intent``/``response`` ISO stamps
    (``intent_recorded_at``/``response_recorded_at`` are accepted aliases).
    ``statement_rows``: provider rows with ``created_at`` (UTC, statement
    format), ``event_description``, ``event_type`` and ``credit``.
    ``event_description``: when given, only rows of that event are matched;
    other events inside the window are listed, never booked.
    ``slack`` widens every window symmetrically; the default (zero) is the
    only value under which abutting sequential windows stay disjoint.
    """
    windows = [(_field(tx, "key", "source_key"), _window(tx)) for tx in transactions]
    stamped: list[tuple[datetime, dict]] = []
    for row in statement_rows:
        created = row.get("created_at")
        if created in (None, ""):
            continue
        try:
            stamped.append((parse_statement_utc(created), row))
        except ValueError:
            continue
    oldest = min((ts for ts, _ in stamped), default=None)
    results = []
    for index, (key, window) in enumerate(windows):
        base = {"key": key, "isolation": ISOLATION, "ledger_label": None,
                "window_utc": None, "paid": None, "refunded": None, "net": None,
                "matched_rows": [], "other_events_in_window": []}
        if window is None:
            results.append({**base, "status": "FAIL_WINDOW_TIMESTAMPS_MISSING"})
            continue
        start, end = window[0] - slack, window[1] + slack
        base["window_utc"] = [_stamp(start), _stamp(end)]
        overlap = None
        for other_index, (other_key, other) in enumerate(windows):
            if other_index == index or other is None:
                continue
            o_start, o_end = other[0] - slack, other[1] + slack
            if o_start < end and start < o_end:
                overlap = other_key
                break
        if overlap is not None:
            results.append({**base, "status": "FAIL_WINDOW_OVERLAP", "overlaps": overlap})
            continue
        if oldest is None or oldest > start:
            results.append({**base, "status": "FAIL_STATEMENT_PAGE_TOO_SHORT"})
            continue
        inside = [row for ts, row in stamped if start <= ts < end]
        matched = [row for row in inside
                   if (event_description is None or row.get("event_description") == event_description)
                   and row.get("event_type") in event_types]
        others = sorted({str(row.get("event_description")) for row in inside if row not in matched})
        base["other_events_in_window"] = others
        pays = [row for row in matched if row.get("event_type") == "Pay"]
        if len(pays) != 1:
            results.append({**base, "status": f"FAIL_WINDOW_PAY_ROW_COUNT_{len(pays)}",
                            "matched_rows": matched})
            continue
        paid = sum((abs(Decimal(str(row.get("credit", 0)))) for row in pays), Decimal(0))
        refunded = sum((abs(Decimal(str(row.get("credit", 0)))) for row in matched
                        if row.get("event_type") == "Refund"), Decimal(0))
        net = paid - refunded
        status = PASS_STATUS if net >= 0 else "INVALID_NEGATIVE_NET"
        results.append({**base, "status": status,
                        "ledger_label": PASS_LABEL if status == PASS_STATUS else None,
                        "paid": float(paid), "refunded": float(refunded), "net": float(net),
                        "matched_rows": matched})
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--transactions", type=Path, required=True,
                        help="JSON list of {key, intent, response}")
    parser.add_argument("--statements", type=Path, required=True,
                        help="JSON list of provider statement rows (or an object with a 'list' key)")
    parser.add_argument("--event-description", default=None,
                        help="Match only this event (e.g. the music generation event name)")
    args = parser.parse_args(argv)
    transactions = json.loads(args.transactions.read_text(encoding="utf-8"))
    statements = json.loads(args.statements.read_text(encoding="utf-8"))
    if isinstance(statements, dict):
        statements = statements.get("list") or statements.get("rows") or []
    results = isolate_credit_windows(transactions, statements, event_description=args.event_description)
    report = {"schema": "qingshan.credit_window_isolation.v1", "isolation": ISOLATION,
              "status": "PASS" if all(r["status"] == PASS_STATUS for r in results) else "FAIL",
              "exact_per_task": False, "results": results}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
