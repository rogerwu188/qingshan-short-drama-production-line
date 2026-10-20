#!/usr/bin/env python3
"""Write off charged image generations whose provider task id can never be recovered (K073).

K073 (E10-VU-020, line-owner standing instruction 2026-10-01 「没关系，选2，以后都这样」):
when a credit statement proves a batch was charged but every task id was lost, the spend is
recorded as a loss, the transaction is settled as CHARGED_WRITTEN_OFF_BY_ORDER, and the SAME
fingerprint is never resubmitted.  The charge stays in the books because the ledger counts
archived ``*_credit_statement.json`` files; this tool changes transaction STATE only.

Evidence rules, all checked before anything is written:

* every named transaction exists and is in an unresolved state;
* a charge-evidenced transaction names an archived PASS_BOUNDED statement whose SHA matches
  the file on disk, whose window contains the transaction's own timestamp, and whose
  ``unmapped_pay_row_count`` is greater than zero (a pay row no task id explains);
* a transaction with no surviving statement window may be settled only with an explicit
  reason; it records zero attributable credits and the same never-resubmit guard.

Nothing here calls the provider.  ``--apply`` writes transaction files atomically and an
append-only report; without it the tool prints the same report and changes nothing.
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

SCHEMA = "qingshan.giggle_charged_write_off.v1"
UNRESOLVED = {"CHARGE_STATE_UNRESOLVED_BATCH", "CHARGED_TASK_ID_MISSING",
              "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION"}
NEVER_RESUBMIT = "DO_NOT_RESUBMIT_THIS_FINGERPRINT"


def load(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(raw, path)
    finally:
        if os.path.exists(raw):
            os.unlink(raw)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def transaction_paths(root: Path) -> dict[str, list[Path]]:
    """Every transaction file per task key.

    A shot can own more than one transaction: its original bound attempt and a later
    response-lost retry with a different fingerprint.  Keying by task key alone would
    pick one arbitrarily and mis-report the other as settled.
    """
    found: dict[str, list[Path]] = {}
    for path in sorted(root.glob("*.json")):
        payload = load(path)
        key = str((payload or {}).get("task_key") or "")
        if key:
            found.setdefault(key, []).append(path)
    return found


def select_transaction(candidates: list[Path], row: dict[str, Any]) -> tuple[Path | None, str]:
    """Pick the exact transaction the evidence names.

    Preferred: the fingerprint named by the evidence row.  Otherwise the candidate is
    accepted only when exactly one file carries an unresolved state — never when a
    settled and an unresolved file share the key (that is the E12 shape).
    """
    want = str(row.get("submission_fingerprint") or "").strip()
    if want:
        for path in candidates:
            payload = load(path) or {}
            if str(payload.get("submission_fingerprint") or "") == want:
                return path, ""
        return None, "FINGERPRINT_NOT_FOUND"
    unresolved = [p for p in candidates
                  if str((load(p) or {}).get("state") or "") in UNRESOLVED]
    if len(unresolved) == 1:
        return unresolved[0], ""
    if not unresolved:
        state = str((load(candidates[0]) or {}).get("state") or "") if candidates else ""
        return None, f"NOT_UNRESOLVED:{state}"
    return None, f"AMBIGUOUS_TASK_KEY:{len(unresolved)}_unresolved"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--episode", required=True)
    parser.add_argument("--transactions", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True,
                        help="JSON file: authority + one row per transaction to settle")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    evidence = load(args.evidence)
    if not evidence:
        raise SystemExit(f"evidence file is missing or unreadable: {args.evidence}")
    authority = evidence.get("authority") or {}
    for field in ("kind", "order_id", "issued_by", "verbatim", "recorded_at_utc"):
        if not str(authority.get(field) or "").strip():
            raise SystemExit(f"evidence authority lacks {field}")
    rows = evidence.get("transactions") or []
    if not rows:
        raise SystemExit("evidence lists no transactions")

    paths = transaction_paths(args.transactions)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    eligible: list[dict[str, Any]] = []
    refused: list[dict[str, Any]] = []
    batch_credits: dict[str, int] = {}

    for row in rows:
        key = str(row.get("task_key") or "").strip()
        candidates = paths.get(key) or []
        if not candidates:
            refused.append({"task_key": key, "reason": "TRANSACTION_NOT_FOUND"})
            continue
        path, why = select_transaction(candidates, row)
        if path is None:
            refused.append({"task_key": key, "reason": why})
            continue
        payload = load(path) or {}
        state = str(payload.get("state") or "")
        if state not in UNRESOLVED:
            refused.append({"task_key": key, "reason": f"NOT_UNRESOLVED:{state}"})
            continue
        proved = row.get("charge_evidence")
        if proved:
            statement_path = Path(str(proved.get("statement") or ""))
            if not statement_path.is_absolute():
                statement_path = Path.cwd() / statement_path
            if not statement_path.is_file():
                refused.append({"task_key": key, "reason": "STATEMENT_MISSING"})
                continue
            actual_sha = sha256(statement_path)
            if actual_sha != str(proved.get("sha256") or ""):
                refused.append({"task_key": key, "reason": "STATEMENT_SHA_MISMATCH",
                                "expected": proved.get("sha256"), "actual": actual_sha})
                continue
            statement = load(statement_path) or {}
            if statement.get("status") != "PASS_BOUNDED":
                refused.append({"task_key": key, "reason": "STATEMENT_NOT_PASS_BOUNDED"})
                continue
            unmapped = int(statement.get("unmapped_pay_row_count") or 0)
            if unmapped <= 0:
                refused.append({"task_key": key,
                                "reason": "NO_UNMAPPED_PAY_ROW_TO_WRITE_OFF"})
                continue
            moment = parse_time(payload.get("response_lost_at") or payload.get("intent_recorded_at"))
            window = (parse_time(statement.get("window_start_utc")),
                      parse_time(statement.get("window_end_utc")))
            if moment is None or None in window or not (window[0] <= moment <= window[1]):
                refused.append({"task_key": key, "reason": "TRANSACTION_OUTSIDE_STATEMENT_WINDOW"})
                continue
            batch_key = str(statement_path)
            batch_credits[batch_key] = int(statement.get("charged_credits") or 0)
            eligible.append({
                "task_key": key, "path": path,
                "written_off_credits": None,
                "batch_charge_evidence": {
                    "statement": str(statement_path),
                    "sha256": actual_sha,
                    "window": [statement.get("window_start_utc"), statement.get("window_end_utc")],
                    "charged_credits": batch_credits[batch_key],
                    "unmapped_pay_rows": unmapped,
                },
            })
            continue
        reason = str(row.get("reason") or "").strip()
        if not reason:
            refused.append({"task_key": key,
                            "reason": "NO_EVIDENCE_AND_NO_REASON"})
            continue
        eligible.append({
            "task_key": key, "path": path,
            "written_off_credits": 0,
            "batch_charge_evidence": None,
            "no_evidence_reason": reason,
        })

    report: dict[str, Any] = {
        "schema": SCHEMA,
        "episode": args.episode,
        "mode": "APPLY" if args.apply else "DRY_RUN",
        "network_calls": 0,
        "posts": 0,
        "authority": authority,
        "eligible_count": len(eligible),
        "refused_count": len(refused),
        "batch_charged_credits": batch_credits,
        "eligible": [{k: v for k, v in row.items() if k != "path"} for row in eligible],
        "refused": refused,
        "recorded_at_utc": now,
    }
    if args.apply:
        for item in eligible:
            path = Path(item["path"])
            payload = load(path)
            if not payload:
                continue
            payload.update({
                "state": "CHARGED_WRITTEN_OFF_BY_ORDER",
                "previous_state": payload.get("state"),
                "ledger_reconciled_at": now,
                "written_off_at": now,
                "written_off_credits": item["written_off_credits"],
                "written_off_by_order": {
                    "kind": authority["kind"],
                    "order_id": authority["order_id"],
                    "issued_by": authority["issued_by"],
                    "verbatim": authority["verbatim"],
                    "recorded_at_utc": authority["recorded_at_utc"],
                },
                "charge_evidence": item["batch_charge_evidence"],
                "retry_guard": NEVER_RESUBMIT,
            })
            if item.get("no_evidence_reason"):
                payload["written_off_without_charge_evidence"] = item["no_evidence_reason"]
            atomic_write(path, payload)
        atomic_write(args.out, report)
        print(json.dumps({"status": "PASS", "applied": len(eligible),
                          "refused": len(refused)}, ensure_ascii=False))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not refused else 2


if __name__ == "__main__":
    raise SystemExit(main())
