#!/usr/bin/env python3
"""Paid-boundary proof that a unit opens from scene start or previous real tail."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

try:
    from tools.event_boundary_continuity_contract import (
        POLICY as EVENT_POLICY,
        strict_required,
        validate_task_boundary,
    )
except ModuleNotFoundError:
    from event_boundary_continuity_contract import (
        POLICY as EVENT_POLICY,
        strict_required,
        validate_task_boundary,
    )

LEGACY_POLICY = "opening_anchor_is_previous_unit_final_frame_or_scene_first_unit"


def validate_opening_anchor_chain(task: dict[str, Any]) -> list[str]:
    if not task.get("semantic_video_unit"):
        return []
    episode = str(
        task.get("episode")
        or (task.get("machine_contract") or {}).get("episode")
        or task.get("unit_id")
        or task.get("task_key")
        or ""
    )
    match = re.search(r"(?:^|[^A-Z])E(\d+)", episode.upper())
    digits = match.group(1) if match else ""
    # The new contract is prospective from E51.  Earlier immutable release
    # manifests remain readable but cannot be used as templates for E51+.
    if digits and int(digits) < 51:
        return []
    machine = task.get("machine_contract") or {}
    contract = machine.get("opening_anchor_contract") or task.get("opening_anchor_contract")
    unit_id = str(task.get("unit_id") or task.get("task_key") or "UNKNOWN")
    if not isinstance(contract, dict):
        return [f"OPENING_ANCHOR_CHAIN_MISSING:{unit_id}"]
    failures: list[str] = []
    required_policy = EVENT_POLICY if strict_required(task) else LEGACY_POLICY
    if contract.get("policy") != required_policy:
        failures.append(f"OPENING_ANCHOR_CHAIN_POLICY_INVALID:{unit_id}")
    continuity_task = dict(task)
    for key in (
        "event_boundary_decision", "persistent_state_contract", "shot_state_contracts",
        "editorial_shot_ids", "internal_transition_contracts",
    ):
        if continuity_task.get(key) is None and machine.get(key) is not None:
            continuity_task[key] = machine[key]
    failures.extend(validate_task_boundary(continuity_task))
    if strict_required(task):
        decision = task.get("event_boundary_decision") or machine.get("event_boundary_decision") or {}
        boundary_class = decision.get("boundary_class")
        source = contract.get("source")
        if boundary_class == "NEW_EVENT_ANCHOR":
            if source != "NEW_EVENT_GENERATED_KEYFRAME" or contract.get("previous_unit_id"):
                failures.append(f"NEW_EVENT_OPENING_SOURCE_INVALID:{unit_id}")
            return list(dict.fromkeys(failures))
        if boundary_class == "MOTIVATED_CUT":
            if source != "CONTINUITY_DERIVED_KEYFRAME" or not contract.get("previous_unit_id"):
                failures.append(f"MOTIVATED_CUT_OPENING_SOURCE_INVALID:{unit_id}")
            tail_path = str(contract.get("previous_state_reference_path") or "")
            tail_sha = str(contract.get("previous_state_reference_sha256") or "")
            if not tail_path or not tail_sha:
                failures.append(f"MOTIVATED_CUT_PREVIOUS_STATE_REFERENCE_MISSING:{unit_id}")
            else:
                resolved = Path(tail_path).expanduser()
                if not resolved.is_absolute():
                    resolved = Path(__file__).resolve().parents[1] / resolved
                if not resolved.is_file() or hashlib.sha256(resolved.read_bytes()).hexdigest() != tail_sha:
                    failures.append(f"MOTIVATED_CUT_PREVIOUS_STATE_REFERENCE_SHA_INVALID:{unit_id}")
                bound_paths = [
                    str(value.get("path") or value.get("url") or "") if isinstance(value, dict) else str(value)
                    for value in task.get("reference_images") or []
                ]
                if tail_path not in bound_paths:
                    failures.append(f"MOTIVATED_CUT_PREVIOUS_STATE_REFERENCE_NOT_BOUND:{unit_id}")
            return list(dict.fromkeys(failures))
        if boundary_class != "HARD_CONTINUATION":
            failures.append(f"EVENT_BOUNDARY_CLASS_INVALID:{unit_id}")
            return list(dict.fromkeys(failures))
    scene_first = machine.get("scene_first_unit")
    if scene_first is None:
        scene_first = task.get("scene_first_unit")
    source = contract.get("source")
    if scene_first is True:
        if source != "SCENE_FIRST_GENERATED_KEYFRAME":
            failures.append(f"SCENE_FIRST_OPENING_SOURCE_INVALID:{unit_id}")
        return failures
    if scene_first is not False:
        failures.append(f"SCENE_FIRST_FLAG_MISSING:{unit_id}")
        return failures
    if source != "PREVIOUS_UNIT_REAL_FINAL_FRAME" or not contract.get("previous_unit_id"):
        failures.append(f"PREVIOUS_REAL_FINAL_FRAME_SOURCE_MISSING:{unit_id}")
    path_value = str(contract.get("materialized_path") or "")
    sha = str(contract.get("sha256") or "")
    references = task.get("reference_images") or []
    reference_shas = task.get("reference_sha256") or []
    if not path_value or not sha:
        failures.append(f"PREVIOUS_REAL_FINAL_FRAME_NOT_MATERIALIZED:{unit_id}")
        return failures
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[1] / path
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != sha:
        failures.append(f"PREVIOUS_REAL_FINAL_FRAME_SHA_INVALID:{unit_id}")
    if not references or str(references[0]) != path_value:
        failures.append(f"PREVIOUS_REAL_FINAL_FRAME_NOT_FIRST_REFERENCE:{unit_id}")
    if not reference_shas or str(reference_shas[0]) != sha:
        failures.append(f"PREVIOUS_REAL_FINAL_FRAME_SHA_NOT_FIRST_REFERENCE:{unit_id}")
    return failures
