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


ACCEPTED = "ACCEPTED_BY_LINE_OWNER_ORDER"
ACCEPTANCE_GATE_ID = "START-FRAME-SEMANTIC-EVIDENCE"


def _accepted_gaps(contract: dict[str, Any], payload: dict[str, Any] | None, *, label: str,
                   unit_id: str, reference_sha: Any) -> dict[str, Any]:
    """What a line-owner acceptance waives, or {} for a PASS contract.

    The receipt writer (nalu start_frame_evidence_writer) records an ACCEPTED_BY_LINE_OWNER_ORDER receipt
    only after matching an active, source-receipted GATE_FAIL_ACCEPTANCE order that names every gap and
    binds the start frame's sha256.  Here the record must be present, identical on contract and evidence,
    not self-issued, for this gate, this unit and this exact image; then exactly the named gaps are waived.
    """
    if contract.get("status") != ACCEPTED:
        return {}
    record = contract.get("line_owner_acceptance")
    if not isinstance(record, dict) or (payload is not None and payload.get("line_owner_acceptance") != record):
        raise ValueError(f"{label} acceptance record is missing or does not match its evidence")
    if (record.get("self_issued") is not False or record.get("gate_id") != ACCEPTANCE_GATE_ID
            or record.get("gate_status_kept") != "FAIL" or not record.get("order_seq")
            or record.get("media_item_id") != unit_id
            or not reference_sha or record.get("media_sha256") != reference_sha
            or record.get("media_sha256_bound_by_order") != reference_sha):
        raise ValueError(f"{label} acceptance record is not bound to this unit's exact start frame")
    gaps: dict[str, Any] = {"characters": set(), "props": set(), "anchors": set(), "flags": set()}
    for detector in record.get("accepted_detectors") or []:
        parts = str(detector).split(":")
        if len(parts) < 2 or parts[0] != unit_id:
            continue
        code = parts[1]
        item = ":".join(parts[2:])
        if code == "REQUIRED_CHARACTER_NOT_OBSERVED":
            gaps["characters"].add(item)
        elif code == "REQUIRED_PROP_NOT_OBSERVED":
            gaps["props"].add(item)
        elif code == "REQUIRED_SPACE_ANCHOR_NOT_OBSERVED":
            gaps["anchors"].add(item)
        else:
            gaps["flags"].add(code)
    return gaps


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
    if contract.get("status") not in ("PASS", ACCEPTED):
        raise ValueError(f"{label} is not PASS")
    gaps = _accepted_gaps(contract, None, label=label, unit_id=unit_id,
                          reference_sha=first_reference.get("sha256"))
    flags = gaps.get("flags") or set()
    if contract.get("reference_path") != first_reference.get("path"):
        raise ValueError(f"{label} reference path does not match the admitted first reference")
    if contract.get("reference_sha256") != first_reference.get("sha256"):
        raise ValueError(f"{label} reference SHA does not match the admitted first reference")
    if contract.get("camera_start_framing_match") is not True and "CAMERA_START_FRAMING_NOT_VERIFIED" not in flags:
        raise ValueError(f"{label} did not verify camera start framing: {camera_plan.get('start_framing')}")
    if contract.get("space_match") is not True and "MAPPED_START_SPACE_NOT_VERIFIED" not in flags:
        raise ValueError(f"{label} did not verify the mapped start space")

    expected_characters = _visible_characters(first_prompt_spec)
    expected_props = _visible_props(first_prompt_spec)
    observed_characters = sorted(set(contract.get("observed_visible_characters") or []))
    observed_props = sorted(set(contract.get("observed_visible_props") or []))
    observed_space = list(dict.fromkeys(contract.get("observed_space_anchors") or []))
    missing_characters = set(expected_characters) - set(observed_characters) - (gaps.get("characters") or set())
    missing_props = set(expected_props) - set(observed_props) - (gaps.get("props") or set())
    missing_anchors = set(required_space_anchors) - set(observed_space) - (gaps.get("anchors") or set())
    if missing_characters:
        raise ValueError(f"{label} is missing visible characters: {sorted(missing_characters)}")
    if missing_props:
        raise ValueError(f"{label} is missing visible props: {sorted(missing_props)}")
    if missing_anchors:
        raise ValueError(f"{label} is missing mapped space anchors: {sorted(missing_anchors)}")
    if (expected_characters and contract.get("empty_establishing_frame") is not False
            and "EMPTY_FRAME_CLAIMED_BUT_CAST_REQUIRED" not in flags):
        raise ValueError(f"{label} admits an empty frame although the initial beat requires visible cast")

    evidence = _resolve(root, str(contract.get("evidence_ref") or ""))
    if not evidence.is_file():
        raise ValueError(f"{label} evidence is missing: {contract.get('evidence_ref')}")
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    if payload.get("status") != contract.get("status"):
        raise ValueError(f"{label} evidence is not PASS")
    _accepted_gaps(contract, payload, label=label, unit_id=unit_id, reference_sha=first_reference.get("sha256"))
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
