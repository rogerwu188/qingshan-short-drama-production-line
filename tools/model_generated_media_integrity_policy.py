#!/usr/bin/env python3
"""Reject semantic post-repairs that conceal model-generation defects.

Provider media may be accepted as generated or replaced by a separately
authorized regeneration.  Normal release transformations remain allowed, but
an accepted-media map must not point at a derivative that masks captions,
replaces native speech, clones frames, or fabricates a bridge to conceal a
model defect.
"""

from __future__ import annotations

from typing import Any


POLICY = "qingshan.model_generated_media_integrity.v1_no_semantic_postrepair"

FORBIDDEN_MODEL_DEFECT_REPAIRS = (
    "AUDIO_REPLACEMENT",
    "ROOM_TONE_REPLACEMENT",
    "DIALOGUE_REPLACEMENT",
    "SUBTITLE_MASK",
    "TEXT_MASK",
    "CROP_TO_REMOVE_TEXT",
    "INPAINT_TO_REMOVE_TEXT",
    "FRAME_CLONE",
    "GENERATED_BRIDGE",
    "SEMANTIC_POSTREPAIR",
)

FORBIDDEN_PATH_MARKERS = (
    "native_audio_sanitized",
    "audio_sanitized",
    "subtitle_masked",
    "text_masked",
    "cropped_to_remove_text",
    "generated_bridge",
    "semantic_postrepair",
)


def _flatten(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        result: list[str] = []
        for key, item in value.items():
            result.append(str(key))
            result.extend(_flatten(item))
        return result
    if isinstance(value, (list, tuple, set)):
        result = []
        for item in value:
            result.extend(_flatten(item))
        return result
    return [str(value)]


def evaluate_accepted_media_row(row: dict[str, Any]) -> dict[str, Any]:
    """Fail closed when a candidate advertises a forbidden semantic repair."""
    failures: list[str] = []
    path = str(row.get("media_path") or row.get("path") or "").lower()
    for marker in FORBIDDEN_PATH_MARKERS:
        if marker in path:
            failures.append(f"MODEL_DEFECT_POSTREPAIR_PATH_FORBIDDEN:{marker}")

    declared_values: list[str] = []
    for field in (
        "postprocess_operations",
        "transformations_applied",
        "repair_operations",
        "semantic_postprocess",
        "model_defect_disposition",
        "derivation",
    ):
        declared_values.extend(_flatten(row.get(field)))
    normalized = "\n".join(declared_values).upper().replace("-", "_").replace(" ", "_")
    for operation in FORBIDDEN_MODEL_DEFECT_REPAIRS:
        if operation in normalized:
            failures.append(f"MODEL_DEFECT_POSTREPAIR_OPERATION_FORBIDDEN:{operation}")
    if row.get("model_defect_postprocessed") is True:
        failures.append("MODEL_DEFECT_POSTPROCESSED_FLAG_FORBIDDEN")
    return {
        "policy": POLICY,
        "status": "PASS" if not failures else "FAIL",
        "media_path": path,
        "failures": sorted(set(failures)),
    }
