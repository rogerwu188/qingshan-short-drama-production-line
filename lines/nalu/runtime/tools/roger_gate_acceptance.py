#!/usr/bin/env python3
"""roger_gate_acceptance.py — a registered gate may stay FAIL and the stage still continue ONLY on an
explicit Roger order (SUPERVISOR_ORDERS seq=25「加接受机制」, 2026-09-17).

This is not a waiver the pipeline can issue for itself (FINAL-CUT-NO-SELF-WAIVER stays): the gate result
keeps its FAIL row and its evidence; what changes is that the stage records WHO accepted WHAT, verbatim,
bound to the media sha256, and only for the detectors the order names.  Anything outside the order —
another gate, another episode, a new failing detector, a different final cut — is not accepted.

Order shape (SUPERVISOR_ORDERS.json entry):
    {"seq": 24, "issued_by": "Roger", "status": "active", "order": "「1」…",
     "decision": {"kind": "GATE_FAIL_ACCEPTANCE", "episode": "E04",
                  "gate_id": "FINAL-CUT-AUDIENCE-DETECTORS",
                  "detectors": ["voice_distinctness", "emotion_dynamics", "loudness"],
                  "media_sha256": null | "<sha of the accepted final cut>"}}
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

KIND = "GATE_FAIL_ACCEPTANCE"


def _orders(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if isinstance(payload, dict):
        payload = payload.get("orders") or payload.get("entries") or []
    return [row for row in payload if isinstance(row, dict)]


def find_acceptance(orders: list[dict[str, Any]], *, episode: str, gate_id: str,
                    failing: list[str], media_sha256: str | None) -> dict[str, Any] | None:
    """The newest active Roger order whose decision covers every failing detector of this gate."""
    match = None
    for row in orders:
        dec = row.get("decision") or {}
        if (str(row.get("issued_by") or "") != "Roger" or str(row.get("status") or "") != "active"
                or dec.get("kind") != KIND or str(dec.get("episode") or "") != episode
                or str(dec.get("gate_id") or "") != gate_id):
            continue
        allowed = {str(x) for x in dec.get("detectors") or []}
        if not set(failing) <= allowed:
            continue
        bound = dec.get("media_sha256")
        if bound and media_sha256 and str(bound) != str(media_sha256):
            continue
        if match is None or int(row.get("seq") or 0) > int(match.get("seq") or 0):
            match = row
    return match


def acceptance_record(order: dict[str, Any], *, episode: str, gate_id: str, failing: list[str],
                      media_sha256: str | None, gate_result_path: str) -> dict[str, Any]:
    dec = order.get("decision") or {}
    return {
        "schema": "qingshan.roger_gate_acceptance.v1",
        "episode": episode, "gate_id": gate_id,
        "gate_status_kept": "FAIL",
        "accepted_detectors": sorted(failing),
        "order_seq": order.get("seq"), "order_id": order.get("id"),
        "issued_by": order.get("issued_by"), "order_verbatim": order.get("order"),
        "order_ts_utc": order.get("ts_utc"),
        "media_sha256": media_sha256,
        "media_sha256_bound_by_order": dec.get("media_sha256"),
        "gate_result": gate_result_path,
        "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "self_issued": False,
        "note": "The gate row stays FAIL with its evidence; the stage continued on this explicit Roger order only.",
    }


def failing_detectors(gate_result: dict[str, Any]) -> list[str]:
    """Detector names from a final_cut_audience_gate.py result ({detectors: {name: status}, failures: [...]})."""
    names = [str(k) for k, v in (gate_result.get("detectors") or {}).items() if str(v) == "FAIL"]
    if names:
        return sorted(names)
    return sorted({str(f).split(":")[0] for f in gate_result.get("failures") or []})
