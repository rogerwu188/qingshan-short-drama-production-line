#!/usr/bin/env python3
"""Detect a finished action being restarted by the next unit.

The scene split is a production wrapper, not a story beat.  When a scene becomes
several generated units, a unit may re-open with the motion the previous unit
already completed — the actor "starts over" at every cut.  This module compares
*structured* declarations only:

  unit["action_event_contract"] = {
      "event_id": "E66-S09-04-TELL-PASSWORD",   # what is happening
      "phase": "START" | "CONTINUE" | "COMPLETE",
      "continues_event_id": "...",               # required when phase=CONTINUE
      "authorized_repeat": {"writer_authorized": true, "source_ref": "..",
                            "reason": ".."}      # a deliberate restaging
  }

No text similarity is used: character overlap misreads a legitimate continuation
and misses a restatement in different words.  A unit with no declaration returns
NOT_APPLICABLE and blocks nothing — absence is not a violation.
"""

from __future__ import annotations

from typing import Any

SCHEMA = "qingshan.unit_action_continuity.v1"
PHASES = {"START", "CONTINUE", "COMPLETE"}


def _contract(unit: dict[str, Any]) -> dict[str, Any]:
    value = unit.get("action_event_contract")
    return value if isinstance(value, dict) else {}


def _authorized_repeat(contract: dict[str, Any]) -> str:
    row = contract.get("authorized_repeat") or {}
    if (
        row.get("writer_authorized") is True
        and str(row.get("source_ref") or "").strip()
        and str(row.get("reason") or "").strip()
    ):
        return str(row.get("reason") or "").strip()
    return ""


def evaluate(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    """Return a verdict for one adjacent unit boundary; never raises."""
    current_contract = _contract(current)
    previous_contract = _contract(previous or {})
    uid = str(current.get("unit_id") or "UNKNOWN")
    event_id = str(current_contract.get("event_id") or "").strip()
    previous_event = str(previous_contract.get("event_id") or "").strip()
    phase = str(current_contract.get("phase") or "").strip().upper()
    previous_phase = str(previous_contract.get("phase") or "").strip().upper()
    continues = str(current_contract.get("continues_event_id") or "").strip()
    if not event_id and not previous_event:
        return {
            "schema": SCHEMA,
            "status": "NOT_APPLICABLE",
            "unit_id": uid,
            "reason": "no action_event_contract declared on either unit",
            "failures": [],
        }
    failures: list[str] = []
    if phase and phase not in PHASES:
        failures.append(f"ACTION_EVENT_PHASE_INVALID:{uid}:{phase}")
    if phase == "CONTINUE" and event_id:
        if continues and continues != event_id:
            failures.append(f"ACTION_EVENT_CONTINUES_MISMATCH:{uid}:{continues}!={event_id}")
        if previous_event and previous_event != event_id:
            failures.append(f"ACTION_EVENT_CONTINUES_UNRELATED:{uid}:{event_id} after {previous_event}")
        if previous_phase == "COMPLETE":
            failures.append(f"ACTION_EVENT_CONTINUES_COMPLETED:{uid}:{event_id}")
    if phase == "START":
        repeat_reason = _authorized_repeat(current_contract)
        if previous_event and previous_event == event_id and previous_phase in {"START", "CONTINUE", "COMPLETE"}:
            code = "COMPLETED_ACTION_RESTARTED" if previous_phase == "COMPLETE" else "EVENT_STARTED_TWICE"
            if not repeat_reason:
                failures.append(f"{code}:{uid}:{event_id}")
    return {
        "schema": SCHEMA,
        "status": "FAIL" if failures else "PASS",
        "unit_id": uid,
        "previous_unit_id": str((previous or {}).get("unit_id") or ""),
        "event_id": event_id,
        "phase": phase,
        "previous_event_id": previous_event,
        "previous_phase": previous_phase,
        "authorized_repeat": bool(_authorized_repeat(current_contract)),
        "failures": failures,
    }
