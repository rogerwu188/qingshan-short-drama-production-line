#!/usr/bin/env python3
"""Fail closed when soft identity references lack exact-output face evidence."""

from __future__ import annotations

from typing import Any


SCHEMA = "qingshan.keyframe_output_identity_gate.v1"


def evaluate(
    tasks: list[dict[str, Any]],
    accepted_items: list[dict[str, Any]],
    verification_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    accepted = {str(row.get("shot_id") or row.get("task_key")): row for row in accepted_items}
    evidence = {
        (str(row.get("shot_id") or row.get("task_key")), str(row.get("entity_id"))): row
        for row in verification_rows
    }
    failures: list[dict[str, Any]] = []
    checked = 0
    for task in tasks:
        contract = task.get("identity_reference_transport") or {}
        if contract.get("transport_guarantee") != "SOFT_REFERENCE_REQUIRES_EXACT_OUTPUT_GATE":
            continue
        shot = str(task.get("shot_id") or task.get("task_key") or "UNKNOWN")
        item = accepted.get(shot)
        if not item:
            failures.append({"shot_id": shot, "reason": "ACCEPTED_OUTPUT_MISSING"})
            continue
        output_sha = str(item.get("sha256") or "")
        for entity_id in sorted((contract.get("authority_map") or {}).keys()):
            checked += 1
            row = evidence.get((shot, entity_id))
            if not row:
                failures.append({"shot_id": shot, "entity_id": entity_id, "reason": "IDENTITY_OUTPUT_EVIDENCE_MISSING"})
                continue
            if row.get("method") != "INSIGHTFACE_COSINE_V1":
                failures.append({"shot_id": shot, "entity_id": entity_id, "reason": "IDENTITY_OUTPUT_METHOD_MISMATCH"})
            if row.get("output_sha256") != output_sha:
                failures.append({"shot_id": shot, "entity_id": entity_id, "reason": "IDENTITY_OUTPUT_SHA_MISMATCH"})
            if row.get("status") != "PASS" or row.get("threshold_pass") is not True:
                failures.append({"shot_id": shot, "entity_id": entity_id, "reason": "IDENTITY_OUTPUT_NOT_VERIFIED"})
    return {
        "schema": SCHEMA,
        "status": "PASS" if not failures else "FAIL",
        "checked_identity_output_count": checked,
        "failures": failures,
        "policy": "A flat/soft reference is not an identity lock until the exact accepted output SHA passes per-entity face verification.",
    }
