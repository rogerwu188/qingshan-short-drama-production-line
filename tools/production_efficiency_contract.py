#!/usr/bin/env python3
"""Fail-closed efficiency plan for next-episode short-drama production."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


POLICY_VERSION = "qingshan.production_efficiency.v1_e47_default"
H3_MODELS = {"minimax-h3", "minimax_h3", "h3"}
DEFAULT_WAVE_SIZE = 6


def _dialogues(unit: dict[str, Any]) -> list[str]:
    prompt_dialogues = [
        str(spec.get("dialogue") or "").strip()
        for spec in unit.get("ordered_prompt_specs") or []
        if str(spec.get("dialogue") or "").strip()
    ]
    direct_dialogues = [str(value).strip() for value in unit.get("dialogue_lines") or [] if str(value).strip()]
    return direct_dialogues or prompt_dialogues


def generation_cache_key(task: dict[str, Any]) -> str:
    """Stable content key; remote task IDs and mutable status never participate."""
    image_digests = {str(value) for value in task.get("reference_sha256") or [] if str(value)}
    for row in task.get("reference_images") or []:
        if isinstance(row, dict):
            digest = str(row.get("sha256") or row.get("media_sha256") or "")
            if digest:
                image_digests.add(digest)
    audio_digests: set[str] = set()
    for row in task.get("reference_audios") or []:
        if isinstance(row, dict):
            digest = str(row.get("sha256") or "")
            if digest:
                audio_digests.add(digest)
    for row in task.get("dialogue_audio_assets") or []:
        if isinstance(row, dict):
            digest = str(row.get("sha256") or "")
            if digest:
                audio_digests.add(digest)
    payload = {
        "model": task.get("model"),
        "duration_seconds": task.get("duration_seconds"),
        "aspect_ratio": task.get("aspect_ratio"),
        "resolution": task.get("resolution"),
        "prompt_sha256": task.get("prompt_sha256"),
        "reference_image_sha256s": sorted(image_digests),
        "reference_audio_sha256s": sorted(audio_digests),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def evaluate_grouped_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    rows: list[dict[str, Any]] = []
    units = manifest.get("units") or manifest.get("tasks") or []
    for index, unit in enumerate(units):
        unit_id = str(unit.get("unit_id") or unit.get("task_key") or f"UNIT-{index + 1:03d}")
        duration = float(unit.get("duration_seconds") or 0)
        dialogue_count = len(_dialogues(unit))
        model = str(unit.get("model") or manifest.get("model") or "").strip().lower()
        family = "minimax-h3" if model in H3_MODELS else "seedance2"
        unit_failures: list[str] = []
        exception = str(unit.get("efficiency_exception_reason") or "").strip()
        if family == "minimax-h3":
            if duration < 3 or duration > 15:
                unit_failures.append("H3_DURATION_OUTSIDE_3_TO_15_SECONDS")
            if dialogue_count and duration > 10 and not exception:
                unit_failures.append("H3_DIALOGUE_UNIT_OVER_10_SECONDS")
            if dialogue_count > 2 and not exception:
                unit_failures.append("H3_DIALOGUE_UNIT_OVER_TWO_LINES")
        if unit_failures:
            failures.extend(f"{unit_id}:{reason}" for reason in unit_failures)
        cache_key = generation_cache_key(unit)
        rows.append({
            "unit_id": unit_id,
            "model_family": family,
            "duration_seconds": duration,
            "dialogue_line_count": dialogue_count,
            "recommended_lane": "DIALOGUE_6_TO_10_SECONDS" if dialogue_count else "ACTION_OR_SILENT_UP_TO_15_SECONDS",
            "efficiency_exception_reason": exception or None,
            "status": "PASS" if not unit_failures else "FAIL",
            "failures": unit_failures,
            "generation_cache_key": cache_key,
        })
    cache_owners: dict[str, str] = {}
    for row in rows:
        cache_key = row["generation_cache_key"]
        previous = cache_owners.get(cache_key)
        if previous:
            reason = f"{row['unit_id']}:DUPLICATE_EXACT_GENERATION_REQUEST_REUSE_{previous}"
            failures.append(reason)
            row["status"] = "FAIL"
            row["failures"].append("DUPLICATE_EXACT_GENERATION_REQUEST_IN_BATCH")
        else:
            cache_owners[cache_key] = row["unit_id"]
    waves = [
        {
            "wave_index": wave_index + 1,
            "unit_ids": [row["unit_id"] for row in rows[start:start + DEFAULT_WAVE_SIZE]],
            "submit_policy": "SUBMIT_ONLY_AFTER_EXACT_UNIT_PREFLIGHT_AND_TRANSACTION_BINDING",
            "harvest_policy": "HARVEST_COMPLETED_HANDLES_IMMEDIATELY_WITHOUT_WAITING_FOR_WAVE",
            "qa_policy": "START_TECHNICAL_AND_BOUNDARY_PRECHECK_AS_EACH_UNIT_COMPLETES",
        }
        for wave_index, start in enumerate(range(0, len(rows), DEFAULT_WAVE_SIZE))
    ]
    return {
        "schema": POLICY_VERSION,
        "episode": manifest.get("episode"),
        "status": "PASS" if not failures else "FAIL",
        "quality_gates_preserved": [
            "MAP", "IDENTITY", "WARDROBE", "PROP", "SOUND", "TRANSITION",
            "PREPAID_PROMPT_QA", "REMOTE_TASK_BINDING", "REAL_MEDIA_BOUNDARY",
        ],
        "post_generation_qa_scope": "TECHNICAL_AND_BASIC_PLOT_ONLY",
        "keyframe_policy": {
            "mode": "SEMANTIC_NOVELTY_ONLY_WITH_CROSS_EPISODE_REUSE",
            "generate_new_only_for": [
                "NEW_CHARACTER_IDENTITY", "NEW_LOCATION_OR_SUBSPACE", "NEW_WARDROBE_STATE",
                "NON_INTERPOLABLE_PROP_OR_BODY_STATE", "TRANSITION_CRITICAL_TERMINAL_STATE",
            ],
            "reuse_by_exact_sha": True,
            "one_keyframe_per_editorial_shot_forbidden": True,
        },
        "cache_policy": {
            "key": "MODEL_DURATION_ASPECT_RESOLUTION_PROMPT_SHA_REFERENCE_SHAS",
            "reuse_completed_exact_match": True,
            "remote_task_id_excluded_from_key": True,
            "never_duplicate_post": True,
        },
        "rolling_execution": {
            "wave_size": DEFAULT_WAVE_SIZE,
            "waves": waves,
            "generation_harvest_and_qa_overlap": True,
        },
        "release_encoding": {
            "preferred_encoder": "h264_videotoolbox",
            "fallback_encoder": "libx264",
            "segment_normalization_cache": True,
            "final_composite_passes": 1,
            "delivery_resolution": "1440x2560",
            "native_resolution_must_remain_honestly_labeled": True,
        },
        "units": rows,
        "failures": failures,
    }


def episode_number(value: Any) -> int | None:
    text = str(value or "").strip().upper()
    if text.startswith("E") and text[1:].isdigit():
        return int(text[1:])
    return None


def require_e47_efficiency_contract(manifest: dict[str, Any]) -> dict[str, Any]:
    """Apply the contract automatically to E47+ paid video manifests."""
    number = episode_number(manifest.get("episode"))
    if number is None or number < 47:
        return {"schema": POLICY_VERSION, "status": "N_A", "episode": manifest.get("episode")}
    report = evaluate_grouped_manifest(manifest)
    if report["status"] != "PASS":
        raise ValueError("E47+ production efficiency gate failed: " + ",".join(report["failures"]))
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = evaluate_grouped_manifest(json.loads(args.manifest.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "failures": report["failures"]}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
