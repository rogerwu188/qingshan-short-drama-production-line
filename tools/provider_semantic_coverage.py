#!/usr/bin/env python3
"""Fail-closed provider semantic coverage receipts.

The shared execution SHA proves that both renderers received the same plan.  It
does not prove that either renderer emitted every required fact.  This module
checks the rendered text itself and records one row per required execution
fact, keyed by a model-neutral fact id.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


SCHEMA = "qingshan.provider_semantic_coverage.v1_rendered_clause_evidence"


def _sha(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normal(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip()


def required_fact_ids(plan: dict[str, Any]) -> list[str]:
    ids = ["ANCHOR.IDENTITY_PROP", "ANCHOR.SPACE_WEATHER", "CAMERA.PLAN"]
    if plan.get("interaction_topology_required"):
        ids.append("PHYSICAL.INTERACTION_TOPOLOGY")
    if plan.get("combat_execution_required"):
        ids.append("COMBAT.EXECUTION_RULE")
    transition = plan.get("transition") or {}
    if transition.get("incoming"):
        ids.append("TRANSITION.INCOMING")
    if transition.get("outgoing"):
        ids.append("TRANSITION.OUTGOING")
    beats = (plan.get("action_ir") or {}).get("causal_chains") or plan.get("beats") or []
    for index, beat in enumerate(beats, 1):
        prefix = f"BEAT.{index}"
        ids.extend((
            f"{prefix}.ENTRY", f"{prefix}.FORCE_ORIGIN", f"{prefix}.ACTION",
            f"{prefix}.EXIT",
        ))
        if str(beat.get("interaction_mode") or "NONE") != "NONE":
            ids.append(f"{prefix}.INTERACTION_MODE")
        if beat.get("contact_time_seconds") is not None:
            ids.append(f"{prefix}.CONTACT_TIME")
        if beat.get("contact_point"):
            ids.append(f"{prefix}.CONTACT_POINT")
        if beat.get("primary_feedback"):
            ids.append(f"{prefix}.PRIMARY_FEEDBACK")
        for secondary_index, _ in enumerate(beat.get("secondary_feedback") or [], 1):
            ids.append(f"{prefix}.SECONDARY_FEEDBACK.{secondary_index}")
        if beat.get("dialogue"):
            ids.append(f"{prefix}.DIALOGUE")
        if beat.get("microexpression_cue"):
            ids.append(f"{prefix}.MICROEXPRESSION")
        if beat.get("body_sync_cue"):
            ids.append(f"{prefix}.BODY_SYNC")
        if beat.get("internal_transition_after"):
            ids.append(f"{prefix}.INTERNAL_TRANSITION_AFTER")
    for key in ("ambience", "foley", "action_sound"):
        for index, _ in enumerate((plan.get("sounds") or {}).get(key) or [], 1):
            ids.append(f"SOUND.{key.upper()}.{index}")
    for index, _ in enumerate(plan.get("environment_motion") or [], 1):
        ids.append(f"ENVIRONMENT_MOTION.{index}")
    for index, _ in enumerate(plan.get("voice_bindings") or [], 1):
        ids.append(f"VOICE_BINDING.{index}")
    return ids


def build_semantic_coverage_receipt(
    *,
    plan: dict[str, Any],
    prompt_text: str,
    model_family: str,
    clause_evidence: dict[str, str],
) -> dict[str, Any]:
    required = required_fact_ids(plan)
    rows = []
    failures = []
    normalized_prompt = _normal(prompt_text)
    for fact_id in required:
        evidence = str(clause_evidence.get(fact_id) or "").strip()
        covered = bool(evidence) and _normal(evidence) in normalized_prompt
        if not covered:
            failures.append(f"PROVIDER_SEMANTIC_FACT_UNCOVERED:{plan.get('unit_id')}:{fact_id}")
        rows.append({
            "fact_id": fact_id,
            "provider_clause_id": fact_id,
            "evidence_sha256": _sha(evidence) if evidence else None,
            "covered": covered,
        })
    fact_set = sorted(required)
    return {
        "schema": SCHEMA,
        "status": "PASS" if not failures else "FAIL",
        "unit_id": str(plan.get("unit_id") or "UNKNOWN"),
        "model_family": model_family,
        "execution_semantics_sha256": plan.get("execution_semantics_sha256"),
        "required_fact_count": len(required),
        "covered_fact_count": sum(row["covered"] for row in rows),
        "required_fact_set_sha256": _sha(fact_set),
        "coverage_rows": rows,
        "failures": failures,
    }


def assert_equivalent_required_fact_sets(*receipts: dict[str, Any]) -> None:
    hashes = {row.get("required_fact_set_sha256") for row in receipts}
    if len(hashes) != 1 or any(row.get("status") != "PASS" for row in receipts):
        raise ValueError("PROVIDER_SEMANTIC_COVERAGE_SET_MISMATCH")
