#!/usr/bin/env python3
"""HopsAPI billing-usage reconciliation of lost create responses (lab E11 S6, 2026-10-31).

HopsAPI has no idempotency key, so a create POST whose response was lost (timeout / reset / 5xx
after sending) is recorded as ``RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION`` and never resent
blindly; the budget ledger fails closed on it.  This tool settles such a transaction against the
billing usage API (https://docs.hopsapi.com/en/docs/usage), read-only GETs only:

* ``GET /v1/account/usage?scope=key|account&kind=media&model=<m>&from&to&limit=500[&cursor]`` lists
  billed rows; a media row's ``request_id`` is the task id and appears only once the task finished
  (failed / cancelled tasks are never billed and never appear).
* ``GET /v1/account/usage/summary`` aggregates the same rows (``summary`` sub-command).

Reconciliation rule (per episode and kind, after a grace period longer than a task's normal
completion: video >= 20 min, image >= 10 min after the newest lost intent of the group):

1. list billed media rows of that model from (earliest lost intent - 1 min) to now;
2. a row whose task id is bound to NO transaction anywhere in ``workflow/tasks/**`` is
   *unattributed*;
3. no unattributed row -> nothing on the provider can be bound to the lost POST.  Line owner standing ruling
   A (2026-11-11, K073): the POST is written off with its reserved credits counted as spent
   (``WRITTEN_OFF_UNATTRIBUTABLE_RETRYABLE``, ``credit_status`` ``ASSUMED_CHARGED_NO_BILLED_TASK_FOUND``) and the
   unit gets ONE new attempt.  (Engines before 2026-11-21 settled this case as ``VERIFIED_ZERO_NO_REMOTE_TASK``
   at 0 credits; a usage row only appears once a task finished, so a task still queued at the provider was
   invisible and its later charge was never counted.  Old rows in that state stay settled.)
4. exactly one lost transaction, exactly one unattributed row billed after its intent, and no other
   lost transaction (any episode) of that kind overlapping the window -> the row's task id is
   ADOPTED: the transaction becomes ``SUBMITTED_TASK_ID_BOUND`` and is polled / harvested like any
   bound task, never re-POSTed;
5. anything else -> ``WRITTEN_OFF_UNATTRIBUTABLE_RETRYABLE`` (line owner 2026-11-11: one key is shared by the
   fleet, so other devices' rows make these windows unattributable by hand): the lost POST is assumed
   charged at its planned price (``written_off_credits``, counted as spend by the ledger) and a new attempt
   may POST.  ``NEEDS_MANUAL_ATTRIBUTION`` rows written by older engines are reconciled again into it.  Several lost POSTs vs several unattributed rows are never paired by guesswork: a
   wrong pairing would harvest one unit's paid clip under another unit.  ``adopt`` binds one by hand.

ONE new attempt per lost transaction (fleet devices 1485 E03 S6, 1101 E20 S5, 2026-11-21): the submitters call
:func:`auto_retry_open` before they replace an auto-reconciled row with a new intent.  It archives the written-off
row beside the transaction (``<tx>.json.lost_response_reconciled.1``, still counted by the budget ledger) and
refuses a second auto-reconciled row of the same transaction, so a resubmit that loses its response again is
written off (counted) but never resubmitted by itself: no paid retry loop.

What the provider can see: HopsAPI has no idempotency key, no client reference and no task-list endpoint; a lost
create has no task id to query.  The only provider view is the billing usage list above, which shows a media
task once it FINISHED (failed / cancelled tasks are never billed).  Hence the grace period, and why "nothing
billed" is written off at the reserved price instead of being called zero.

Automatic use (``reconcile_episode(auto=True)``: the pipeline's budget check, the S6 re-entry, ``paid_stage.sh``
preflight and therefore every system-tick re-run) stops when ``NALU_LOST_RESPONSE_AUTO_RECONCILE=0`` (kill
switch; the operator CLI ``reconcile`` without ``--auto`` still works).  While a lost transaction waits for its
grace period or the usage read fails, :func:`lost_response_wait` turns the budget refusal into a remote wait
(``HOPSAPI_LOST_RESPONSE_RECONCILING``) that the system tick re-runs, instead of a stop that waits for a human.
Each settled transaction logs one line ``LOST_RESPONSE_RECONCILED kind=BOUND|WRITTEN_OFF ...`` (stderr).

Key scope: ``scope=key`` sees only the current key.  It is used when every lost intent carries the
current key's fingerprint, or (legacy intents without one) a sibling transaction bound within
10 minutes of the lost intent is billed on this key (same process, same key); otherwise the query
widens to ``scope=account`` (every key of the buyer; foreign rows then block as unattributed).

Every decision is appended to ``workflow/tasks/_hopsapi_usage_reconciliation/<EP>.jsonl`` (with a
snapshot of the transaction before the change) and to the transaction's own
``usage_reconciliation_history``; the original lost-response fields are kept.

The key is read from ``HOPSAPI_API_KEY`` only and is never printed, logged or written.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlencode

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import hopsapi_video_client as hops  # noqa: E402

ENGINE_ROOT = TOOLS.parent
SCHEMA = "qingshan.hopsapi_usage_reconciliation.v1"
LOST_STATE = "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION"
VERIFIED_ZERO_STATE = "VERIFIED_ZERO_NO_REMOTE_TASK"
MANUAL_STATE = "NEEDS_MANUAL_ATTRIBUTION"
BOUND_STATE = "SUBMITTED_TASK_ID_BOUND"
#: line owner 2026-11-11 (option B): one HopsAPI key is shared by the whole fleet, so an ambiguous window (other
#: devices' billed rows) can never be attributed by hand at scale.  The lost POST is assumed charged at its
#: planned price -- counted in the ledger as spend -- and a new attempt may POST.
AUTO_WRITEOFF_STATE = "WRITTEN_OFF_UNATTRIBUTABLE_RETRYABLE"
WRITEOFF_FALLBACK_CREDITS = {"video": 15.0, "image": 2.0}
#: A submitter killed between the intent record and the create response (SIGKILL / command timeout: no
#: exception handler runs) leaves the transaction at INTENT_RECORDED with no task id.  The POST may or may
#: not have left, exactly like a lost response, but nothing ever settled it: the submitter guard refused the
#: fingerprint forever and this tool did not look at it (device ...0069 E15 S5, 2026-11-17: 19 / 21 keyframes
#: bound, two stuck).  It is reconciled by the same rules after the same grace period; the write happens
#: under the transaction's flock and only if the attempt is still unbound, so a live submitter is never
#: overtaken.  The neutral health probe keeps its own never-re-POST rule and is left alone.
INTERRUPTED_STATE = "INTENT_RECORDED"
RECONCILABLE_STATES = {LOST_STATE, MANUAL_STATE, INTERRUPTED_STATE}
#: A neutral health probe (``hopsapi_health_probe``) whose create response was lost sits in the episode's image
#: store at RESPONSE_LOST and the ledger refuses every paid step on it -- and this tool skipped every probe, so
#: nothing could ever settle it (fleet device 1101 E20 S5, 2026-11-21).  A lost / manual probe is reconciled
#: like any POST (it is never re-POSTed: the next probe is a new attempt anyway); an INTENT_RECORDED probe is
#: still left to its live owner (the ledger does not count INTENT_RECORDED as unresolved).
PROBE_RECONCILABLE_STATES = {LOST_STATE, MANUAL_STATE}
KILL_SWITCH_ENV = "NALU_LOST_RESPONSE_AUTO_RECONCILE"
NO_BILLED_TASK_CREDIT_STATUS = "ASSUMED_CHARGED_NO_BILLED_TASK_FOUND"
#: rows an auto reconciliation leaves retryable; :func:`auto_retry_open` allows ONE new attempt per transaction
AUTO_RETRY_STATES = {VERIFIED_ZERO_STATE, AUTO_WRITEOFF_STATE}
RETRY_ARCHIVE_SUFFIX = ".lost_response_reconciled.1"
#: the budget-gate blocker paid_run_status treats as a remote wait (the system tick re-runs the stage)
WAIT_BLOCKER = "HOPSAPI_LOST_RESPONSE_RECONCILING"
STORES = {"video": "giggle_video_submit_transactions", "image": "giggle_submit_transactions"}
USAGE_MODELS = {"video": hops.H3_MODEL, "image": "gpt-image-2"}
GRACE_SECONDS = {"video": int(os.environ.get("HOPSAPI_USAGE_GRACE_VIDEO_SECONDS", "1200")),
                 "image": int(os.environ.get("HOPSAPI_USAGE_GRACE_IMAGE_SECONDS", "600"))}
WINDOW_LEAD_SECONDS = 60
SIBLING_KEY_PROOF_SECONDS = 600
#: another unresolved lost POST this long before the window may still bill inside it: no adoption then
OTHER_LOST_LOOKBACK_SECONDS = 24 * 3600
EVIDENCE_DIRNAME = "_hopsapi_usage_reconciliation"
PAGE_LIMIT = 500
MAX_PAGES = 200
USAGE_ATTEMPTS = 3


class UsageError(RuntimeError):
    """A usage read failed; nothing is changed (the ledger keeps failing closed)."""


# --------------------------------------------------------------------------- #
# time helpers
# --------------------------------------------------------------------------- #
def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


# --------------------------------------------------------------------------- #
# usage API (GET only)
# --------------------------------------------------------------------------- #
def key_fingerprint() -> str | None:
    return hops.key_fingerprint()


def usage_get(path: str, params: dict[str, Any]) -> dict[str, Any]:
    """One GET against /v1/account/usage*; 429 / 5xx / network retried, anything else raises."""
    query = urlencode({k: v for k, v in params.items() if v not in (None, "")})
    url = f"{hops.base_url()}{path}" + (f"?{query}" if query else "")
    last = ""
    for attempt in range(USAGE_ATTEMPTS):
        try:
            _status, parsed, raw = hops._http("GET", url, headers=hops._auth_headers(),
                                              timeout=hops.HTTP_TIMEOUT_SECONDS)
        except hops.HopsapiHTTPError as exc:
            last = f"HTTP {exc.status}"
            if exc.status == 429 or exc.status >= 500:
                time.sleep(hops.RETRY_DELAY_SECONDS * (attempt + 1))
                continue
            raise UsageError(f"USAGE_READ_REJECTED:{path}:HTTP {exc.status}:{exc.raw[:300]}") from None
        except (hops.HopsapiNotSent, OSError) as exc:
            last = f"NETWORK:{type(exc).__name__}"
            time.sleep(hops.RETRY_DELAY_SECONDS * (attempt + 1))
            continue
        if not isinstance(parsed, dict):
            raise UsageError(f"USAGE_READ_NOT_JSON:{path}:{raw[:200]}")
        return parsed
    raise UsageError(f"USAGE_READ_FAILED_AFTER_{USAGE_ATTEMPTS}_ATTEMPTS:{path}:{last}")


def list_usage(*, scope: str, start: datetime, end: datetime, kind: str | None = None,
               model: str | None = None) -> dict[str, Any]:
    """Every billed row of the window (all pages), newest first, plus the query evidence."""
    params = {"scope": scope, "kind": kind, "model": model, "from": iso(start), "to": iso(end),
              "limit": PAGE_LIMIT}
    rows: list[dict[str, Any]] = []
    cursor = None
    pages = 0
    while True:
        payload = usage_get("/account/usage", {**params, "cursor": cursor})
        pages += 1
        data = payload.get("data")
        if not isinstance(data, list):
            raise UsageError("USAGE_LIST_HAS_NO_DATA_ARRAY")
        rows.extend(row for row in data if isinstance(row, dict))
        cursor = payload.get("next_cursor")
        if not payload.get("has_more") or not cursor:
            break
        if pages >= MAX_PAGES:
            raise UsageError(f"USAGE_LIST_EXCEEDED_{MAX_PAGES}_PAGES")
    return {"rows": rows, "query": {"endpoint": "GET /v1/account/usage", **params, "pages": pages,
                                    "queried_at": iso(utc_now())}}


def usage_summary(*, scope: str, start: datetime, end: datetime, kind: str | None = None,
                  model: str | None = None, group_by: str = "model") -> dict[str, Any]:
    return usage_get("/account/usage/summary", {"scope": scope, "kind": kind, "model": model,
                                                "from": iso(start), "to": iso(end), "group_by": group_by})


# --------------------------------------------------------------------------- #
# local stores
# --------------------------------------------------------------------------- #
def tasks_root_default() -> Path:
    return ENGINE_ROOT / "workflow" / "tasks"


def _load(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _task_ids(node: Any, out: set[str], depth: int = 0) -> None:
    if depth > 12:
        return
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "task_id" and isinstance(value, str) and value.strip():
                out.add(value.strip())
            elif isinstance(value, (dict, list)):
                _task_ids(value, out, depth + 1)
    elif isinstance(node, list):
        for value in node:
            _task_ids(value, out, depth + 1)


def bound_task_ids(tasks_root: Path) -> set[str]:
    """Every task id any durable record under workflow/tasks/** holds (all stores, all episodes,
    retired ``.terminal-*`` copies, receipts).  Only ``task_id`` fields count: the ids this tool
    lists as unattributed (``unattributed_task_ids``) must never make themselves look bound."""
    found: set[str] = set()
    if not tasks_root.is_dir():
        return found
    for path in tasks_root.rglob("*.json"):
        if EVIDENCE_DIRNAME in path.parts:
            continue
        payload = _load(path)
        if payload is not None:
            _task_ids(payload, found)
    return found


def _is_hopsapi(payload: dict[str, Any]) -> bool:
    return str(payload.get("provider") or "").lower() == hops.PROVIDER_HOPSAPI


def lost_transactions(tasks_root: Path, kind: str, episode: str | None = None) -> list[tuple[Path, dict[str, Any]]]:
    """HopsAPI transactions of ``kind`` still waiting for usage reconciliation (lost or manual)."""
    store = tasks_root / STORES[kind]
    directories = [store / episode] if episode else sorted(p for p in store.glob("*") if p.is_dir())
    found = []
    for directory in directories:
        for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
            payload = _load(path)
            if payload and _is_hopsapi(payload) and payload.get("state") in RECONCILABLE_STATES \
                    and not payload.get("task_id") \
                    and (not payload.get("hopsapi_health_probe") or payload.get("state") in PROBE_RECONCILABLE_STATES):
                found.append((path, payload))
    return found


def bound_siblings(tasks_root: Path, kind: str, episode: str) -> list[dict[str, Any]]:
    directory = tasks_root / STORES[kind] / episode
    rows = []
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        payload = _load(path)
        if payload and _is_hopsapi(payload) and payload.get("task_id"):
            rows.append(payload)
    return rows


def evidence_path(tasks_root: Path, episode: str) -> Path:
    return tasks_root / EVIDENCE_DIRNAME / f"{episode}.jsonl"


def append_evidence(tasks_root: Path, episode: str, record: dict[str, Any]) -> None:
    path = evidence_path(tasks_root, episode)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _write_transaction(path: Path, expected: dict[str, Any], update: Callable[[dict[str, Any]], None]) -> bool:
    """Apply ``update`` under the transaction's flock, only if it is still the attempt we decided on."""
    with path.with_suffix(".lock").open("a") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        current = _load(path)
        if not current or current.get("attempt_id") != expected.get("attempt_id") \
                or current.get("state") not in RECONCILABLE_STATES or current.get("task_id"):
            return False
        update(current)
        temporary = path.with_suffix(path.suffix + ".part")
        temporary.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
        return True


# --------------------------------------------------------------------------- #
# reconciliation
# --------------------------------------------------------------------------- #
def _key_scope(group: list[dict[str, Any]], siblings: list[dict[str, Any]], key_row_ids: set[str],
               current_fp: str | None) -> tuple[str, list[dict[str, Any]]]:
    """('key'|'account', per-transaction basis).  ``key`` only when every lost intent provably used
    the current key: its recorded fingerprint, or a sibling bound close in time billed on this key."""
    basis = []
    for row in group:
        fp = row.get("hopsapi_key_fingerprint")
        intent = parse_utc(row.get("intent_recorded_at"))
        if fp:
            ok = bool(current_fp) and fp == current_fp
            basis.append({"task_key": row.get("task_key"), "basis": "INTENT_KEY_FINGERPRINT",
                          "matches_current_key": ok})
            continue
        proof = None
        for sib in siblings:
            sib_at = parse_utc(sib.get("intent_recorded_at"))
            if intent and sib_at and abs((sib_at - intent).total_seconds()) <= SIBLING_KEY_PROOF_SECONDS \
                    and str(sib.get("task_id")) in key_row_ids:
                proof = str(sib.get("task_id"))
                break
        basis.append({"task_key": row.get("task_key"), "basis": "SIBLING_BOUND_TASK_BILLED_ON_CURRENT_KEY",
                      "sibling_task_id": proof, "matches_current_key": proof is not None})
    return ("key" if all(item["matches_current_key"] for item in basis) else "account"), basis


def reconcile_kind(episode: str, kind: str, *, tasks_root: Path, now: datetime | None = None,
                   dry_run: bool = False) -> dict[str, Any]:
    now = now or utc_now()
    entries = lost_transactions(tasks_root, kind, episode)
    if not entries:
        return {"kind": kind, "status": "NOTHING_TO_RECONCILE", "lost": 0}
    grace = GRACE_SECONDS[kind]
    intents = [parse_utc(row.get("intent_recorded_at")) for _path, row in entries]
    if any(at is None for at in intents):
        return {"kind": kind, "status": "BLOCKED_INTENT_TIME_MISSING", "lost": len(entries),
                "task_keys": [row.get("task_key") for _p, row in entries]}
    newest = max(intents)
    ready_at = newest + timedelta(seconds=grace)
    if now < ready_at:
        return {"kind": kind, "status": "PENDING_GRACE", "lost": len(entries), "grace_seconds": grace,
                "eligible_at": iso(ready_at), "task_keys": [row.get("task_key") for _p, row in entries]}
    start = min(intents) - timedelta(seconds=WINDOW_LEAD_SECONDS)
    model = USAGE_MODELS[kind]
    key_listing = list_usage(scope="key", start=start, end=now, kind="media", model=model)
    key_ids = {str(r.get("request_id")) for r in key_listing["rows"]}
    group = [row for _path, row in entries]
    scope, scope_basis = _key_scope(group, bound_siblings(tasks_root, kind, episode), key_ids, key_fingerprint())
    listing = key_listing if scope == "key" else list_usage(scope="account", start=start, end=now,
                                                            kind="media", model=model)
    rows = [r for r in listing["rows"] if str(r.get("kind") or "media") == "media"
            and str(r.get("model") or model) == model and str(r.get("request_id") or "")]
    bound = bound_task_ids(tasks_root)
    # a row billed before the earliest lost POST's intent cannot be any of them (adopt() refuses it too); with
    # one key shared by the whole fleet it is another device's task.  Field device …0899 E01: one foreign row
    # 33 s before the lost intent held the episode at NEEDS_MANUAL_ATTRIBUTION with nothing to attribute.
    earliest_intent = min(intents)
    candidates = [r for r in rows if str(r["request_id"]) not in bound]
    pre_intent_foreign = [r for r in candidates
                          if (parse_utc(r.get("created_at")) or earliest_intent) < earliest_intent]
    unattributed = sorted((r for r in candidates if r not in pre_intent_foreign),
                          key=lambda r: str(r.get("created_at") or ""))
    own_attempts = {row.get("attempt_id") for row in group}
    overlapping_other_lost = [
        {"transaction": str(path), "task_key": row.get("task_key")}
        for path, row in lost_transactions(tasks_root, kind)
        if row.get("attempt_id") not in own_attempts
        and (parse_utc(row.get("intent_recorded_at")) or now) >= start - timedelta(seconds=OTHER_LOST_LOOKBACK_SECONDS)]
    adopt = None
    if not unattributed:
        decision = AUTO_WRITEOFF_STATE  # ruling A: nothing to bind -> written off at the reserved price
    elif (len(group) == 1 and len(unattributed) == 1 and not overlapping_other_lost
          and (parse_utc(unattributed[0].get("created_at")) or start) >= intents[0]):
        decision = BOUND_STATE
        adopt = unattributed[0]
    else:
        decision = AUTO_WRITEOFF_STATE
    evidence_base = {
        "schema": SCHEMA, "episode": episode, "kind": kind, "reconciled_at": iso(now),
        "decision": decision, "grace_seconds": grace, "query": listing["query"], "scope": scope,
        "scope_basis": scope_basis, "row_count": len(rows),
        "billed_task_ids": sorted(str(r["request_id"]) for r in rows),
        "unattributed_task_ids": [str(r["request_id"]) for r in unattributed],
        "unattributed_rows": [{k: r.get(k) for k in ("request_id", "model", "charge", "status", "created_at")}
                              | {"key_id": (r.get("key") or {}).get("id")} for r in unattributed],
        "pre_intent_foreign_task_ids": [str(r["request_id"]) for r in pre_intent_foreign],
        "bound_task_id_count": len(bound), "lost_transaction_count": len(group),
        "overlapping_other_lost": overlapping_other_lost, "dry_run": dry_run,
        "rule": ("rows billed before the earliest lost intent are foreign and ignored; exactly one lost POST and "
                 "one unattributed row billed after its intent -> adopt (bind + poll, never re-POST); otherwise "
                 "(no unattributed row, or rows that cannot be paired) -> written off at the reserved price, one "
                 "new attempt (line owner ruling A / K073)"),
        "no_billed_task_found": not unattributed,
    }
    results = []
    for (path, row), intent_at in zip(entries, intents):
        record = {**evidence_base, "transaction": str(path), "task_key": row.get("task_key"),
                  "attempt_id": row.get("attempt_id"), "previous_state": row.get("state"),
                  "intent_recorded_at": row.get("intent_recorded_at"),
                  "response_lost_at": row.get("response_lost_at"), "new_state": decision}
        if adopt is not None:
            record["adopted_task_id"] = str(adopt["request_id"])
            record["adopted_row"] = {k: adopt.get(k) for k in ("request_id", "charge", "status", "created_at")}

        def update(current: dict[str, Any], record=record) -> None:
            summary = {k: record[k] for k in ("reconciled_at", "decision", "scope", "row_count",
                                              "unattributed_task_ids", "grace_seconds")}
            summary["query"] = {k: record["query"].get(k) for k in ("endpoint", "scope", "kind", "model",
                                                                    "from", "to", "pages")}
            current.setdefault("usage_reconciliation_history", []).append(summary)
            current.setdefault("state_history", []).append(
                {"state": current.get("state"), "until": record["reconciled_at"]})
            if decision == VERIFIED_ZERO_STATE:
                current.update({
                    "state": VERIFIED_ZERO_STATE, "credit_status": "NOT_CHARGED_VERIFIED_BY_USAGE_API",
                    "credit": 0, "retry_guard": "RETRY_ALLOWED_NEW_ATTEMPT",
                    "reconciliation": {"method": "HOPSAPI_USAGE_API_NO_UNATTRIBUTED_BILLED_TASK",
                                       "credit": 0, "reconciled_at": record["reconciled_at"]}})
            elif decision == BOUND_STATE:
                charge = adopt.get("charge")
                current.update({
                    "state": BOUND_STATE, "task_id": record["adopted_task_id"],
                    "task_id_source": "HOPSAPI_USAGE_RECONCILIATION_ADOPTED",
                    "response_recorded_at": record["reconciled_at"],
                    "retry_guard": "DO_NOT_RESUBMIT_POLL_ADOPTED_TASK",
                    "reconciliation": {"method": "HOPSAPI_USAGE_API_SINGLE_UNATTRIBUTED_BILLED_TASK_ADOPTED",
                                       "adopted_row": record["adopted_row"],
                                       "reconciled_at": record["reconciled_at"]}})
                try:
                    current["provider_cost_credits"] = float(Decimal(str(charge)))
                    current["provider_cost_recorded_at"] = record["reconciled_at"]
                    current["provider_cost_source"] = "HOPSAPI_USAGE_ROW_CHARGE"
                except Exception:  # noqa: BLE001 - no charge: the poller records the settled cost
                    pass
            else:
                credits = reserved_credits(current, kind)
                record["written_off_credits"] = credits
                none_billed = bool(record.get("no_billed_task_found"))
                current.update({
                    "state": AUTO_WRITEOFF_STATE, "retry_guard": "RETRY_ALLOWED_NEW_ATTEMPT",
                    "credit_status": (NO_BILLED_TASK_CREDIT_STATUS if none_billed
                                      else "ASSUMED_CHARGED_UNATTRIBUTABLE_SHARED_KEY"),
                    "written_off_credits": credits, "written_off_at": record["reconciled_at"],
                    "unattributed_task_ids": record["unattributed_task_ids"],
                    "written_off_by_order": write_off_authority(record["reconciled_at"]),
                    "operator_note": (("no billed HopsAPI task can be bound to this lost POST after the grace period"
                                       if none_billed else
                                       "billed HopsAPI rows in the window cannot be told apart from other devices' "
                                       "tasks on the shared key")
                                      + ": written off at the reserved price (counted as spend), ONE new attempt "
                                        "may POST (line owner ruling A / K073)")})

        written = False if dry_run else _write_transaction(path, row, update)
        record["written"] = written
        if not dry_run:
            if not written:
                record["new_state"] = "SKIPPED_TRANSACTION_CHANGED"
            append_evidence(tasks_root, episode, {**record, "transaction_before": row})
            if written:
                log_reconciled(record, kind)
        results.append({k: record.get(k) for k in ("task_key", "transaction", "previous_state", "new_state",
                                                   "adopted_task_id", "written")})
    return {"kind": kind, "status": decision, "lost": len(group), "scope": scope, "row_count": len(rows),
            "window": {"from": listing["query"]["from"], "to": listing["query"]["to"]},
            "billed_task_ids": evidence_base["billed_task_ids"],
            "unattributed_task_ids": evidence_base["unattributed_task_ids"],
            "transactions": results}


def auto_enabled(environ: dict[str, str] | None = None) -> bool:
    """The kill switch: ``NALU_LOST_RESPONSE_AUTO_RECONCILE=0`` (or off/false/no) stops every automatic use."""
    value = str((os.environ if environ is None else environ).get(KILL_SWITCH_ENV, "1")).strip().lower()
    return value not in {"0", "off", "false", "no"}


def reserved_credits(row: dict[str, Any], kind: str) -> float:
    """What the lost POST reserved (its planned ``estimated_credits``); the kind's fallback without one."""
    planned = row.get("estimated_credits")
    if isinstance(planned, (int, float)) and not isinstance(planned, bool) and planned > 0:
        return float(planned)
    return WRITEOFF_FALLBACK_CREDITS.get(kind, 15.0)


def write_off_authority(recorded_at: str) -> dict[str, Any]:
    """The K073 order block tools/write_off_charged_losses.py records, for ruling A applied by the engine."""
    import write_off_charged_losses as k073  # noqa: PLC0415 - engine tool, no provider call
    return {**k073.RULING_A_AUTHORITY, "applied_by": "tools/hopsapi_usage.py (automatic)",
            "recorded_at_utc": recorded_at}


def log_reconciled(record: dict[str, Any], kind: str, stream: Any = None) -> str:
    """One grep-able line per settled transaction: ``LOST_RESPONSE_RECONCILED kind=BOUND|WRITTEN_OFF ...``."""
    decided = "BOUND" if record.get("decision") == BOUND_STATE else "WRITTEN_OFF"
    fields = [f"kind={decided}", f"episode={record.get('episode')}", f"store={kind}",
              f"task_key={record.get('task_key')}", f"attempt={record.get('attempt_id')}"]
    if decided == "BOUND":
        fields.append(f"task_id={record.get('adopted_task_id')}")
    else:
        fields += [f"credits={record.get('written_off_credits')}",
                   "reason=" + ("NO_BILLED_TASK_FOUND" if record.get("no_billed_task_found") else "UNATTRIBUTABLE"),
                   "resubmit=ONE_NEW_ATTEMPT"]
    line = "LOST_RESPONSE_RECONCILED " + " ".join(fields)
    print(line, file=stream or sys.stderr, flush=True)
    return line


def reconcile_episode(episode: str, *, kinds: Iterable[str] = ("video", "image"), tasks_root: Path | None = None,
                      now: datetime | None = None, dry_run: bool = False, auto: bool = False) -> dict[str, Any]:
    """Reconcile every lost HopsAPI transaction of the episode.  No lost transaction = no network.
    A usage read failure changes nothing and is reported (the ledger keeps refusing).  ``auto=True`` (the
    engine's own calls) honours the kill switch."""
    root = tasks_root or tasks_root_default()
    report: dict[str, Any] = {"schema": SCHEMA, "episode": episode, "kinds": {}}
    if auto and not auto_enabled():
        report.update(status="AUTO_RECONCILE_DISABLED", unresolved_remaining=bool(pending_lost(episode, root)))
        return report
    for kind in kinds:
        try:
            report["kinds"][kind] = reconcile_kind(episode, kind, tasks_root=root, now=now, dry_run=dry_run)
        except (UsageError, hops.HopsapiError, SystemExit) as exc:
            report["kinds"][kind] = {"kind": kind, "status": "USAGE_READ_FAILED_NOTHING_CHANGED",
                                     "error": str(exc)[:300]}
    statuses = {row.get("status") for row in report["kinds"].values()}
    report["unresolved_remaining"] = bool(statuses - {"NOTHING_TO_RECONCILE", VERIFIED_ZERO_STATE, BOUND_STATE,
                                                      AUTO_WRITEOFF_STATE})
    return report


def pending_lost(episode: str, tasks_root: Path | None = None) -> int:
    """Offline: how many HopsAPI transactions of the episode wait for usage reconciliation."""
    root = tasks_root or tasks_root_default()
    return sum(len(lost_transactions(root, kind, episode)) for kind in STORES)


def _store_identity(path: Any) -> tuple[str, str, str]:
    value = Path(str(path))
    return (value.parent.parent.name, value.parent.name, value.name)


def lost_response_wait(episode: str, *, failures: Iterable[Any], unresolved: Iterable[Any],
                       tasks_root: Path | None = None, now: datetime | None = None) -> dict[str, Any] | None:
    """Offline: is a budget refusal ONLY lost HopsAPI creates this tool will settle by itself?

    ``failures`` is the ledger's failure list, ``unresolved`` its ``unresolved_transactions`` rows (or paths).
    A dict (``blocker`` = ``HOPSAPI_LOST_RESPONSE_RECONCILING:...``) means: wait and re-run, the next run
    reconciles (grace elapsed) or retries the usage read; None means the refusal needs judgement (cap, other
    unresolved spend, kill switch) and stays a hard stop."""
    if not auto_enabled():
        return None
    failures = [str(f) for f in failures or []]
    if not failures or any(not f.startswith("UNRECONCILED_TRANSACTIONS") for f in failures):
        return None
    root = tasks_root or tasks_root_default()
    now = now or utc_now()
    lost = [(kind, path, row) for kind in STORES for path, row in lost_transactions(root, kind, episode)]
    if not lost:
        return None
    lost_ids = {_store_identity(path) for _kind, path, _row in lost}
    rows = [r.get("transaction") if isinstance(r, dict) else r for r in unresolved or []]
    if not rows or any(not r or _store_identity(r) not in lost_ids for r in rows):
        return None
    eligible = []
    for kind, _path, row in lost:
        intent = parse_utc(row.get("intent_recorded_at"))
        if intent is not None:
            eligible.append(intent + timedelta(seconds=GRACE_SECONDS[kind]))
    eligible_at = max(eligible) if eligible else now
    phase = "PENDING_GRACE" if now < eligible_at else "RECONCILE_DUE"
    return {"blocker": f"{WAIT_BLOCKER}:{len(lost)}:{phase}:eligible_at={iso(eligible_at)}",
            "lost": len(lost), "phase": phase, "eligible_at": iso(eligible_at),
            "task_keys": sorted(str(row.get("task_key")) for _k, _p, row in lost)}


def _retry_identity(row: dict[str, Any]) -> list[Any]:
    history = row.get("usage_reconciliation_history") or []
    stamp = (row.get("written_off_at") or (row.get("reconciliation") or {}).get("reconciled_at")
             or (history[-1].get("reconciled_at") if history and isinstance(history[-1], dict) else None)
             or row.get("ledger_reconciled_at") or "")
    return [row.get("attempt_id"), str(stamp), row.get("state")]


def auto_retry_open(path: Path, row: dict[str, Any]) -> bool:
    """True when an auto-reconciled row (written off / verified zero) may be followed by its ONE new attempt.

    Called by the submitters (the caller holds the transaction lock) right before a new intent replaces the
    row.  The row is archived verbatim beside the transaction (``RETRY_ARCHIVE_SUFFIX``, not ``*.json``: no live
    scan reads it; the budget ledger still counts its write-off).  The archive names the attempt it let through:
    the same row again (a run that stopped before its intent) is still open; a DIFFERENT auto-reconciled row of
    the same transaction -- the new attempt lost its response too and was written off -- is refused, so the
    engine never loops paid resubmits.  An unreadable archive fails closed."""
    if row.get("state") not in AUTO_RETRY_STATES:
        return False
    identity = _retry_identity(row)
    archive = path.with_name(path.name + RETRY_ARCHIVE_SUFFIX)
    if archive.is_file():
        try:
            kept = json.loads(archive.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return isinstance(kept, dict) and _retry_identity(kept) == identity
    temporary = archive.with_name(archive.name + ".part")
    temporary.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, archive)
    return True


def adopt(transaction: Path, task_id: str, *, tasks_root: Path | None = None,
          now: datetime | None = None) -> dict[str, Any]:
    """Operator attribution of a NEEDS_MANUAL_ATTRIBUTION / lost transaction to one billed task id:
    the id must be billed on this account (GET /usage/{id}) and bound to no other transaction."""
    root = tasks_root or tasks_root_default()
    now = now or utc_now()
    row = _load(transaction)
    if not row or row.get("state") not in RECONCILABLE_STATES or row.get("task_id"):
        raise SystemExit(f"{transaction} is not a lost / manual-attribution transaction")
    if task_id in bound_task_ids(root):
        raise SystemExit(f"{task_id} is already bound to a transaction")
    billed = usage_get(f"/account/usage/{task_id}", {})
    intent = parse_utc(row.get("intent_recorded_at"))
    created = parse_utc(billed.get("created_at"))
    if str(billed.get("request_id")) != task_id or (intent and created and created < intent):
        raise SystemExit(f"{task_id} usage row does not fit this transaction (billed before its intent)")
    episode = transaction.parent.name
    record = {"schema": SCHEMA, "episode": episode, "reconciled_at": iso(now), "decision": BOUND_STATE,
              "method": "OPERATOR_ADOPT", "transaction": str(transaction), "task_key": row.get("task_key"),
              "attempt_id": row.get("attempt_id"), "previous_state": row.get("state"),
              "adopted_task_id": task_id,
              "adopted_row": {k: billed.get(k) for k in ("request_id", "model", "charge", "status", "created_at")}}

    def update(current: dict[str, Any]) -> None:
        current.setdefault("state_history", []).append({"state": current.get("state"), "until": record["reconciled_at"]})
        current.setdefault("usage_reconciliation_history", []).append(
            {k: record[k] for k in ("reconciled_at", "decision", "method", "adopted_task_id")})
        current.update({"state": BOUND_STATE, "task_id": task_id, "task_id_source": "HOPSAPI_USAGE_OPERATOR_ADOPTED",
                        "response_recorded_at": record["reconciled_at"],
                        "retry_guard": "DO_NOT_RESUBMIT_POLL_ADOPTED_TASK",
                        "reconciliation": {"method": "OPERATOR_ADOPT", "adopted_row": record["adopted_row"]}})
        try:
            current["provider_cost_credits"] = float(Decimal(str(billed.get("charge"))))
            current["provider_cost_source"] = "HOPSAPI_USAGE_ROW_CHARGE"
            current["provider_cost_recorded_at"] = record["reconciled_at"]
        except Exception:  # noqa: BLE001
            pass

    record["written"] = _write_transaction(transaction, row, update)
    append_evidence(root, episode, {**record, "transaction_before": row})
    return record


# --------------------------------------------------------------------------- #
# summary
# --------------------------------------------------------------------------- #
def summarize(*, start: datetime, end: datetime, kind: str | None, scope: str = "key") -> dict[str, Any]:
    """Totals by model (calls, tokens, charge) for the window; windows > 31 days are split."""
    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    total_calls = 0
    total_charge = Decimal("0")
    cursor = start
    windows = []
    while cursor < end:
        stop = min(end, cursor + timedelta(days=31))
        body = usage_summary(scope=scope, start=cursor, end=stop, kind=kind, group_by="model")
        windows.append({"from": iso(cursor), "to": iso(stop)})
        for row in body.get("data") or []:
            key = (str(row.get("model")), str(row.get("channel")))
            bucket = buckets.setdefault(key, {"model": key[0], "channel": key[1], "calls": 0,
                                              "charge": Decimal("0"), "tokens": {}})
            bucket["calls"] += int(row.get("calls") or 0)
            bucket["charge"] += Decimal(str(row.get("charge") or "0"))
            for name, value in (row.get("tokens") or {}).items():
                bucket["tokens"][name] = bucket["tokens"].get(name, 0) + int(value or 0)
        total = body.get("total") or {}
        total_calls += int(total.get("calls") or 0)
        total_charge += Decimal(str(total.get("charge") or "0"))
        cursor = stop
    models = sorted(buckets.values(), key=lambda b: b["charge"], reverse=True)
    return {"schema": "qingshan.hopsapi_usage_summary.v1", "scope": scope, "kind": kind or "all",
            "from": iso(start), "to": iso(end), "windows": windows, "currency": "credits (100 = 1 USD)",
            "by_model": [{**b, "charge": str(b["charge"]), "usd": str((b["charge"] / 100).quantize(Decimal("0.0001")))}
                         for b in models],
            "total": {"calls": total_calls, "charge": str(total_charge),
                      "usd": str((total_charge / 100).quantize(Decimal("0.0001")))}}


def _time_arg(value: str | None, default: datetime) -> datetime:
    if not value:
        return default
    parsed = parse_utc(value)
    if parsed is None:
        raise SystemExit(f"not an ISO-8601 time: {value}")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="HopsAPI billing usage: reconcile lost creates, summarize spend "
                                                 "(GET only; key from HOPSAPI_API_KEY, never printed).")
    sub = parser.add_subparsers(dest="cmd", required=True)
    rec = sub.add_parser("reconcile", help="settle RESPONSE_LOST HopsAPI transactions of an episode")
    rec.add_argument("episode")
    rec.add_argument("--kinds", default="video,image")
    rec.add_argument("--dry-run", action="store_true", help="query and decide, write nothing")
    rec.add_argument("--tasks-root", type=Path)
    rec.add_argument("--auto", action="store_true",
                     help=f"engine call (paid_stage.sh): honours the kill switch {KILL_SWITCH_ENV}=0")
    wst = sub.add_parser("wait-state", help="offline: is a budget refusal only lost creates this tool settles? "
                                            "(exit 0 + JSON with the wait blocker, else exit 1)")
    wst.add_argument("episode")
    wst.add_argument("--budget-report", type=Path, required=True,
                     help="the ledger's --out report of the refused check")
    wst.add_argument("--tasks-root", type=Path)
    wst.add_argument("--blocker-only", action="store_true", help="print only the wait blocker (shell use)")
    adp = sub.add_parser("adopt", help="bind one billed task id to a lost / manual-attribution transaction")
    adp.add_argument("transaction", type=Path)
    adp.add_argument("--task-id", required=True)
    adp.add_argument("--tasks-root", type=Path)
    summ = sub.add_parser("summary", help="billed totals by model for a window")
    summ.add_argument("--from", dest="start", required=True)
    summ.add_argument("--to", dest="end")
    summ.add_argument("--kind", choices=("llm", "media"))
    summ.add_argument("--scope", choices=("key", "account"), default="key")
    args = parser.parse_args(argv)
    if args.cmd == "reconcile":
        episode = args.episode.upper() if args.episode.upper().startswith("E") else f"E{int(args.episode):02d}"
        kinds = [k.strip() for k in args.kinds.split(",") if k.strip()]
        unknown = [k for k in kinds if k not in STORES]
        if unknown:
            raise SystemExit(f"unknown kind(s): {unknown}")
        report = reconcile_episode(episode, kinds=kinds, tasks_root=args.tasks_root, dry_run=args.dry_run,
                                   auto=args.auto)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if report["unresolved_remaining"] else 0
    if args.cmd == "wait-state":
        budget = _load(args.budget_report) or {}
        stores = budget.get("durable_transaction_stores") or {}
        wait = lost_response_wait(args.episode, failures=budget.get("failures") or [],
                                  unresolved=stores.get("unresolved_transactions") or [],
                                  tasks_root=args.tasks_root)
        print(wait["blocker"] if wait and args.blocker_only else json.dumps(wait or {"wait": False}, ensure_ascii=False))
        return 0 if wait else 1
    if args.cmd == "adopt":
        print(json.dumps(adopt(args.transaction, args.task_id, tasks_root=args.tasks_root), ensure_ascii=False,
                         indent=2))
        return 0
    start = _time_arg(args.start, utc_now())
    print(json.dumps(summarize(start=start, end=_time_arg(args.end, utc_now()), kind=args.kind, scope=args.scope),
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
