#!/usr/bin/env python3
"""Bind the admitted start image to the actual first-beat composition."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def _resolve(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _visible_characters(spec: dict[str, Any]) -> list[str]:
    return sorted({
        str(row.get("character") or "").strip()
        for row in spec.get("cast") or []
        if row.get("character") and str(row.get("face_visibility") or "") != "OFFSCREEN_VOICE_ONLY"
    })


def _visible_props(spec: dict[str, Any]) -> list[str]:
    return sorted({str(row.get("prop") or "").strip() for row in spec.get("props") or [] if row.get("prop")})


def validate_start_anchor_semantics(
    contract: Any,
    *,
    unit_id: str,
    first_reference: dict[str, Any],
    first_prompt_spec: dict[str, Any],
    camera_plan: dict[str, Any],
    required_space_anchors: list[str],
    root: Path,
) -> dict[str, Any]:
    label = f"{unit_id} start_frame_semantic_contract"
    if not required_space_anchors or any(not str(value).strip() for value in required_space_anchors):
        raise ValueError(f"{label} requires at least one mapped start-space anchor")
    if not isinstance(contract, dict):
        raise ValueError(f"{label} is required")
    required = {
        "status", "reference_path", "reference_sha256", "evidence_ref",
        "observed_visible_characters", "observed_visible_props", "observed_space_anchors",
        "camera_start_framing_match", "space_match", "empty_establishing_frame",
    }
    missing = sorted(required - set(contract))
    if missing:
        raise ValueError(f"{label} missing fields: {missing}")
    if contract.get("status") != "PASS":
        raise ValueError(f"{label} is not PASS")
    if contract.get("reference_path") != first_reference.get("path"):
        raise ValueError(f"{label} reference path does not match the admitted first reference")
    if contract.get("reference_sha256") != first_reference.get("sha256"):
        raise ValueError(f"{label} reference SHA does not match the admitted first reference")
    if contract.get("camera_start_framing_match") is not True:
        raise ValueError(f"{label} did not verify camera start framing: {camera_plan.get('start_framing')}")
    if contract.get("space_match") is not True:
        raise ValueError(f"{label} did not verify the mapped start space")

    expected_characters = _visible_characters(first_prompt_spec)
    expected_props = _visible_props(first_prompt_spec)
    observed_characters = sorted(set(contract.get("observed_visible_characters") or []))
    observed_props = sorted(set(contract.get("observed_visible_props") or []))
    observed_space = list(dict.fromkeys(contract.get("observed_space_anchors") or []))
    if not set(expected_characters).issubset(observed_characters):
        raise ValueError(f"{label} is missing visible characters: {sorted(set(expected_characters) - set(observed_characters))}")
    if not set(expected_props).issubset(observed_props):
        raise ValueError(f"{label} is missing visible props: {sorted(set(expected_props) - set(observed_props))}")
    if not set(required_space_anchors).issubset(observed_space):
        raise ValueError(f"{label} is missing mapped space anchors: {sorted(set(required_space_anchors) - set(observed_space))}")
    if expected_characters and contract.get("empty_establishing_frame") is not False:
        raise ValueError(f"{label} admits an empty frame although the initial beat requires visible cast")

    evidence = _resolve(root, str(contract.get("evidence_ref") or ""))
    if not evidence.is_file():
        raise ValueError(f"{label} evidence is missing: {contract.get('evidence_ref')}")
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    if payload.get("status") != "PASS":
        raise ValueError(f"{label} evidence is not PASS")
    if payload.get("reference_path") != first_reference.get("path"):
        raise ValueError(f"{label} evidence reference path mismatch")
    if payload.get("reference_sha256") != first_reference.get("sha256"):
        raise ValueError(f"{label} evidence reference SHA mismatch")
    evidence_characters = sorted(set(payload.get("observed_visible_characters") or []))
    evidence_props = sorted(set(payload.get("observed_visible_props") or []))
    evidence_space = list(dict.fromkeys(payload.get("observed_space_anchors") or []))
    if evidence_characters != observed_characters:
        raise ValueError(f"{label} observed character claims do not match evidence")
    if evidence_props != observed_props:
        raise ValueError(f"{label} observed prop claims do not match evidence")
    if evidence_space != observed_space:
        raise ValueError(f"{label} observed space-anchor claims do not match evidence")
    for key in ("camera_start_framing_match", "space_match", "empty_establishing_frame"):
        if payload.get(key) is not contract.get(key):
            raise ValueError(f"{label} {key} claim does not match evidence")

    normalized = dict(contract)
    normalized.update({
        "required_visible_characters": expected_characters,
        "required_visible_props": expected_props,
        "required_space_anchors": list(dict.fromkeys(required_space_anchors)),
        "observed_visible_characters": observed_characters,
        "observed_visible_props": observed_props,
        "observed_space_anchors": observed_space,
        "evidence_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
    })
    return normalized
