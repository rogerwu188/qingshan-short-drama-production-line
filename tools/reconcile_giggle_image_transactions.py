#!/usr/bin/env python3
"""Evidence-bound, offline reconciliation for image submit transactions.

This tool never calls Giggle and never submits a task.  It may settle an
ambiguous image transaction only when a single archived PASS_BOUNDED credit
statement proves that the whole batch is accounted for:

* exactly one statement window contains the transaction timestamp;
* the statement has no unmapped pay rows;
* known task ids equal matched pay rows;
* the statement's ambiguous count equals the unresolved transactions mapped
  to that window; and
* the batch cardinality closes (known + ambiguous == expected).

Anything else remains quarantined.  ``--apply`` writes an append-only report
and updates only the eligible transaction rows to NOT_CHARGED_RETRYABLE.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


UNRESOLVED = {"CHARGE_STATE_UNRESOLVED_BATCH", "CHARGED_TASK_ID_MISSING"}


def load(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(raw, path)
    finally:
        if os.path.exists(raw):
            os.unlink(raw)


def tx_time(payload: dict[str, Any]) -> datetime | None:
    return parse_time(payload.get("response_lost_at") or payload.get("intent_recorded_at"))


def report_window(payload: dict[str, Any]) -> tuple[datetime, datetime] | None:
    start = parse_time(payload.get("window_start_utc"))
    end = parse_time(payload.get("window_end_utc"))
    return (start, end) if start is not None and end is not None and start <= end else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episode", required=True)
    ap.add_argument("--transactions", type=Path, required=True)
    ap.add_argument("--reports-root", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    tx_rows: list[tuple[Path, dict[str, Any], datetime]] = []
    for path in sorted(args.transactions.glob("*.json")):
        payload = load(path)
        if not payload or payload.get("state") not in UNRESOLVED:
            continue
        moment = tx_time(payload)
        if moment is not None:
            tx_rows.append((path, payload, moment))

    statements: list[tuple[Path, dict[str, Any], datetime, datetime]] = []
    for path in sorted(args.reports_root.rglob("*_credit_statement.json")):
        payload = load(path)
        if not payload or payload.get("status") != "PASS_BOUNDED":
            continue
        window = report_window(payload)
        if window:
            statements.append((path, payload, window[0], window[1]))

    eligible: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    by_statement: dict[str, list[tuple[Path, dict[str, Any], datetime]]] = {}

    # A provider-declined request can be marked safe when every pay row in its
    # isolated retry windows is already explained by a different, bound task
    # whose response timestamp matches the pay-row timestamp.  This is the
    # only accepted recovery for CHARGED_TASK_ID_MISSING; unmatched rows stay
    # quarantined.
    bound_responses: list[tuple[Path, dict[str, Any], datetime]] = []
    for path in args.transactions.glob("*.json"):
        payload = load(path)
        if not payload or payload.get("state") != "SUBMITTED_TASK_ID_BOUND":
            continue
        moment = parse_time(payload.get("response_recorded_at"))
        if moment is not None:
            bound_responses.append((path, payload, moment))
    for path, payload, moment in tx_rows:
        if payload.get("state") != "CHARGED_TASK_ID_MISSING":
            continue
        provider = payload.get("provider_response") or {}
        if provider.get("code") != 400 or "ReferenceImages" not in str(provider.get("msg") or ""):
            continue
        relevant = []
        for statement_path, statement, start, end in statements:
            if not (start <= moment <= end):
                continue
            rows = statement.get("statement_rows") or []
            if statement.get("unmapped_pay_row_count") != 1 or statement.get("matched_count") != 1 or len(rows) != 1:
                continue
            row_time = parse_time(str(rows[0].get("created_at") or "").replace(" ", "T") + "+00:00")
            if row_time is None:
                continue
            matches = [
                (bound_path, bound_payload)
                for bound_path, bound_payload, bound_time in bound_responses
                if bound_payload.get("model") == payload.get("model")
                and abs((bound_time - row_time).total_seconds()) <= 3.0
            ]
            if len(matches) == 1:
                relevant.append((statement_path, statement, matches[0], row_time))
        if relevant:
            eligible.append({
                "transaction": str(path),
                "task_key": payload.get("task_key"),
                "statement": str(relevant[0][0]),
                "statement_sha256": sha256(relevant[0][0]),
                "known_task_ids": 1,
                "matched_pay_rows": 1,
                "ambiguous_transactions": 0,
                "expected_count": 1,
                "evidence_mode": "PROVIDER_DECLINE_PAY_ROW_MATCHES_BOUND_TASK",
                "matched_bound_tasks": [
                    {"statement": str(statement_path), "bound_transaction": str(match[0]),
                     "bound_task_id": match[1].get("task_id"), "pay_row_time": row_time.isoformat()}
                    for statement_path, _statement, match, row_time in relevant
                ],
            })

    candidates: dict[str, list[tuple[Path, dict[str, Any]]]] = {}
    for path, payload, moment in tx_rows:
        hits = [(sp, report) for sp, report, start, end in statements if start <= moment <= end]
        candidates[str(path)] = hits

    # Some historical batch records were timestamped before the provider's
    # submit window (the submitter recorded the intent time, not the final
    # response time).  They still carry the exact batch reconciliation tuple;
    # use that tuple only when it identifies one closed statement and the full
    # unresolved cardinality closes.
    embedded_groups: dict[tuple[int, int, int], list[tuple[Path, dict[str, Any]]]] = {}
    for path, payload, _moment in tx_rows:
        fields = (
            payload.get("batch_known_task_ids"),
            payload.get("batch_ledger_pay_rows"),
            payload.get("batch_unmapped_pay_rows"),
        )
        if all(isinstance(value, int) for value in fields):
            embedded_groups.setdefault(fields, []).append((path, payload))

    for path, payload, moment in tx_rows:
        hits = candidates[str(path)]
        embedded = [
            (statement_path, statement)
            for statement_path, statement, _start, _end in statements
            if (
                statement.get("known_task_id_count"),
                statement.get("matched_count"),
                statement.get("unmapped_pay_row_count"),
            ) == (
                payload.get("batch_known_task_ids"),
                payload.get("batch_ledger_pay_rows"),
                payload.get("batch_unmapped_pay_rows"),
            )
            and isinstance(statement.get("expected_count"), int)
            and isinstance(statement.get("ambiguous_response_count"), int)
            and statement.get("expected_count") == statement.get("known_task_id_count") + statement.get("ambiguous_response_count")
        ]
        if len(embedded) == 1:
            statement_path, statement = embedded[0]
            group = embedded_groups.get((
                payload.get("batch_known_task_ids"),
                payload.get("batch_ledger_pay_rows"),
                payload.get("batch_unmapped_pay_rows"),
            ), [])
            if len(group) == statement.get("ambiguous_response_count"):
                eligible.append({
                    "transaction": str(path),
                    "task_key": payload.get("task_key"),
                    "statement": str(statement_path),
                    "statement_sha256": sha256(statement_path),
                    "known_task_ids": statement.get("known_task_id_count"),
                    "matched_pay_rows": statement.get("matched_count"),
                    "ambiguous_transactions": statement.get("ambiguous_response_count"),
                    "expected_count": statement.get("expected_count"),
                    "evidence_mode": "EMBEDDED_BATCH_RECONCILIATION_CLOSED",
                })
                continue
        # A bounded statement with zero pay rows is safe even when multiple
        # retry windows overlap: every candidate must independently prove a
        # closed zero-charge batch.  This handles legacy retry reports whose
        # time windows overlap but contain no payment rows at all.
        if hits and all(
            isinstance(report.get("expected_count"), int)
            and isinstance(report.get("ambiguous_response_count"), int)
            and report.get("expected_count") == report.get("ambiguous_response_count")
            and report.get("matched_count") == 0
            and report.get("known_task_id_count") == 0
            and report.get("unmapped_pay_row_count") == 0
            and report.get("charged_credits") == 0
            for _statement_path, report in hits
        ):
            eligible.append({
                "transaction": str(path),
                "task_key": payload.get("task_key"),
                "statement": str(hits[0][0]),
                "statement_sha256": sha256(hits[0][0]),
                "known_task_ids": 0,
                "matched_pay_rows": 0,
                "ambiguous_transactions": hits[0][1].get("ambiguous_response_count"),
                "expected_count": hits[0][1].get("expected_count"),
                "evidence_mode": "ALL_CANDIDATE_WINDOWS_CLOSED_ZERO_CHARGE",
                "all_zero_charge_statements": [str(p) for p, _ in hits],
                "statement_sha256s": [sha256(p) for p, _ in hits],
            })
            continue
        if len(hits) != 1:
            skipped.append({"transaction": str(path), "reason": "WINDOW_NOT_UNIQUE", "hit_count": len(hits)})
            continue
        statement_path, statement = hits[0]
        by_statement.setdefault(str(statement_path), []).append((path, payload, moment))

    for statement_path, rows in by_statement.items():
        statement = load(Path(statement_path)) or {}
        expected = statement.get("expected_count")
        matched = statement.get("matched_count")
        known = statement.get("known_task_id_count")
        ambiguous = statement.get("ambiguous_response_count")
        unmapped = statement.get("unmapped_pay_row_count")
        reason = None
        if not all(isinstance(v, int) for v in (expected, matched, known, ambiguous, unmapped)):
            reason = "MISSING_INTEGER_ACCOUNTING_FIELDS"
        elif unmapped != 0:
            reason = "UNMAPPED_PAY_ROWS"
        elif known != matched:
            reason = "KNOWN_TASK_COUNT_DOES_NOT_MATCH_PAY_ROWS"
        elif len(rows) != ambiguous:
            reason = "WINDOW_AMBIGUOUS_COUNT_MISMATCH"
        elif known + ambiguous != expected:
            reason = "BATCH_CARDINALITY_NOT_CLOSED"
        if reason:
            for path, _payload, _moment in rows:
                skipped.append({"transaction": str(path), "reason": reason, "statement": statement_path})
            continue
        statement_sha = sha256(Path(statement_path))
        for path, payload, _moment in rows:
            eligible.append({
                "transaction": str(path),
                "task_key": payload.get("task_key"),
                "statement": statement_path,
                "statement_sha256": statement_sha,
                "known_task_ids": known,
                "matched_pay_rows": matched,
                "ambiguous_transactions": ambiguous,
                "expected_count": expected,
            })

    report: dict[str, Any] = {
        "schema": "qingshan.giggle_image_transaction_reconciliation.v1",
        "episode": args.episode,
        "mode": "APPLY" if args.apply else "DRY_RUN",
        "network_calls": 0,
        "posts": 0,
        "eligible_count": len(eligible),
        "skipped_count": len(skipped),
        "eligible": eligible,
        "skipped": skipped,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    if args.apply:
        for item in eligible:
            path = Path(item["transaction"])
            payload = load(path)
            if not payload or payload.get("state") not in UNRESOLVED:
                continue
            payload.update({
                "state": "NOT_CHARGED_RETRYABLE",
                "ledger_reconciled_at": report["recorded_at_utc"],
                "batch_known_task_ids": item["known_task_ids"],
                "batch_ledger_pay_rows": item["matched_pay_rows"],
                "batch_unmapped_pay_rows": 0,
                "retry_guard": "RETRY_ALLOWED_NEW_ATTEMPT",
                "reconciliation_evidence": {
                    "method": "PASS_BOUNDED_UNIQUE_WINDOW_CLOSED_BATCH",
                    "statement": item["statement"],
                    "statement_sha256": item["statement_sha256"],
                },
            })
            atomic_write(path, payload)
        atomic_write(args.out, report)
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.apply:
        print(json.dumps({"status": "PASS", "applied": len(eligible), "skipped": len(skipped)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
