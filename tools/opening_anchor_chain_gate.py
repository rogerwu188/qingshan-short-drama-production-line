#!/usr/bin/env python3
"""Paid-boundary proof that a unit opens from scene start or previous real tail."""

from __future__ import annotations

import hashlib
import json
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
AUDIT_ONLY_PREDECESSOR_TAIL = "AUDIT_ONLY_NOT_PROVIDER_VISIBLE"
STRUCTURED_STATE_ONLY = "STRUCTURED_STATE_ONLY_NOT_PROVIDER_VISIBLE"


def _exact_population_clean_opening(task: dict[str, Any]) -> bool:
    references = task.get("reference_images") or []
    reference_shas = task.get("reference_sha256") or []
    if not references or not reference_shas or len(references) != len(reference_shas):
        return False
    opening_path = str(references[0])
    opening_sha = str(reference_shas[0])
    semantic = (task.get("machine_contract") or {}).get(
        "start_frame_semantic_contract"
    ) or task.get("start_frame_semantic_contract") or {}
    if semantic.get("reference_path") != opening_path or semantic.get("reference_sha256") != opening_sha:
        return False
    admission_ref = str(task.get("start_frame_admission_ref") or "")
    if not admission_ref:
        return False
    admission_path = Path(admission_ref).expanduser()
    if not admission_path.is_absolute():
        admission_path = Path(__file__).resolve().parents[1] / admission_path
    if not admission_path.is_file():
        return False
    try:
        admission = json.loads(admission_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    population = admission.get("population_scope_verification") or {}
    return all((
        admission.get("status") == "ADMITTED",
        admission.get("downstream_status") == "ADMITTED_FOR_VIDEO_SUBMIT",
        admission.get("asset_path") == opening_path,
        admission.get("asset_sha256") == opening_sha,
        admission.get("exact_sha_verified") is True,
        population.get("status") == "PASS",
        population.get("reviewed_asset_sha256") == opening_sha,
        int(population.get("observed_background_population_count", -1)) == 0,
        int(population.get("observed_unbound_living_entity_count", -1)) == 0,
    ))


def _allows_audit_only_predecessor_tail(
    task: dict[str, Any],
    *,
    contract: dict[str, Any],
    tail_path: str,
    tail_sha: str,
) -> bool:
    """Prove a contaminated tail was replaced, not silently omitted.

    A motivated cut normally transports the predecessor tail as an image.  If
    exact review found that tail unsafe (for example, it contains an extra
    person), it may remain audit evidence only when a separately admitted,
    population-clean continuity-derived keyframe is the first provider image.
    """
    if contract.get("previous_state_reference_transport") != AUDIT_ONLY_PREDECESSOR_TAIL:
        return False
    evidence_rows = task.get("continuity_state_evidence") or []
    matching = [
        row for row in evidence_rows
        if isinstance(row, dict)
        and str(row.get("path") or "") == tail_path
        and str(row.get("sha256") or "") == tail_sha
        and row.get("admission_status") == "ACCEPTED"
        and row.get("provider_transport") == AUDIT_ONLY_PREDECESSOR_TAIL
        and str(row.get("admission_ref") or "").strip()
    ]
    if len(matching) != 1:
        return False
    return _exact_population_clean_opening(task)


def _allows_structured_state_only_motivated_cut(
    task: dict[str, Any], *, contract: dict[str, Any]
) -> bool:
    """Allow a cast-isolating H3 cut without transporting unsafe prior pixels.

    This is narrower than a new-event anchor.  The story event remains
    continuous, while a source-bound shot handoff and exact-cast keyframe carry
    the state across an authored camera change.  It exists for models that turn
    every provider-visible identity card or predecessor person into a new actor.
    """
    if contract.get("previous_state_reference_transport") != STRUCTURED_STATE_ONLY:
        return False
    decision = task.get("event_boundary_decision") or (task.get("machine_contract") or {}).get("event_boundary_decision") or {}
    if not all((
        decision.get("boundary_class") == "MOTIVATED_CUT",
        decision.get("same_continuous_event") is True,
        str(contract.get("previous_unit_id") or "").strip(),
        str(contract.get("source") or "") == "CONTINUITY_DERIVED_KEYFRAME",
    )):
        return False
    rows = [
        row for row in task.get("continuity_state_evidence") or []
        if isinstance(row, dict)
        and row.get("schema") == "qingshan.structured_shot_handoff_evidence.v1"
        and row.get("status") == "PASS"
        and row.get("previous_unit_id") == contract.get("previous_unit_id")
        and row.get("same_continuous_event") is True
        and row.get("state_inheritance_status") == "PASS"
        and str(row.get("from_shot_id") or "").strip()
        and str(row.get("to_shot_id") or "").strip()
        and str(row.get("source_ref") or "").strip()
        and str(row.get("camera_change_reason") or "").strip()
    ]
    if len(rows) != 1:
        return False
    source_path = Path(str(rows[0]["source_ref"])).expanduser()
    if not source_path.is_absolute():
        source_path = Path(__file__).resolve().parents[1] / source_path
    source_sha = str(rows[0].get("source_ref_sha256") or "")
    if not source_path.is_file() or not source_sha:
        return False
    if hashlib.sha256(source_path.read_bytes()).hexdigest() != source_sha:
        return False
    return _exact_population_clean_opening(task)


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
            if _allows_structured_state_only_motivated_cut(task, contract=contract):
                return list(dict.fromkeys(failures))
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
                if tail_path not in bound_paths and not _allows_audit_only_predecessor_tail(
                    task,
                    contract=contract,
                    tail_path=tail_path,
                    tail_sha=tail_sha,
                ):
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
