#!/usr/bin/env python3
"""Paid-boundary proof that a unit opens from scene start or previous real tail."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any


POLICY = "opening_anchor_is_previous_unit_final_frame_or_scene_first_unit"


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
    if contract.get("policy") != POLICY:
        failures.append(f"OPENING_ANCHOR_CHAIN_POLICY_INVALID:{unit_id}")
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
