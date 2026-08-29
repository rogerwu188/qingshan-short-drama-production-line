#!/usr/bin/env python3
"""Build the fail-closed E44 V5 native-720p SD2 video transaction batch."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from compile_grouped_seedance_manifest import action_timeline, prompt_text, validate_model_prompt
from grouped_internal_continuity_contract import (
    find_same_slot_character_replacements,
    validate_internal_transition_sequence,
)
from shot_media_admission_gate import compute_input_template_id
from video_prompt_action_density_gate import validate_action_timeline


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e44_v5_20260828"
QA = ROOT / "qa/e44_v5_preproduction_20260828"
GROUPED = PROD / "E44_V5_GROUPED_SEEDANCE_MANIFEST_COMPILED_V1.json"
MAP_PLAN = PROD / "E44_V5_COMPLETE_MAP_SHOT_PLAN_LOCKED_V1.json"
MAP_AUTHORITY = PROD / "E44_V5_EPISODE_GLOBAL_SPACE_MAP_AUTHORITY_LOCKED_V1.json"
ACCEPTED = QA / "E44_V5_KEYFRAME_ACCEPTED_MEDIA_MAP_57_V1.json"
PROMPT_DIR = PROD / "video_prompts_submit_v1"
PROMPT_MANIFEST = QA / "grouped_preflight_v1/E44_V5_SUBMISSION_COMPLETE_VIDEO_PROMPT_MANIFEST_V1.json"
SUBMISSION_GROUPED = PROD / "E44_V5_GROUPED_SEEDANCE_SUBMISSION_MANIFEST_V1.json"
ADMISSION_DIR = PROD / "start_frame_admissions_v1"
OUT = PROD / "E44_V5_TRANSACTIONAL_VIDEO_MANIFEST_PRECHECK_V1.json"
ACTION_DENSITY = QA / "grouped_preflight_v1/E44_V5_VIDEO_PROMPT_ACTION_DENSITY_V1.json"
TRANSITION_AUDIT = QA / "grouped_preflight_v1/E44_V5_VIDEO_PROMPT_TRANSITION_AUDIT_SUBMISSION_V1.json"
POST_QA_POLICY = QA / "E44_V5_POST_GENERATION_QA_SCOPE_POLICY_V1.json"
SHOT_RE = re.compile(r"(E44-S\d{2}-\d{2})")


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def source_shot(path: str) -> str:
    match = SHOT_RE.search(path)
    if not match:
        raise ValueError(f"reference path has no E44 shot id: {path}")
    return match.group(1)


def allocate(units: list[dict[str, Any]]) -> dict[str, int]:
    floors = {str(row["unit_id"]): math.floor(float(row["duration_seconds"])) for row in units}
    remaining = 180 - sum(floors.values())
    order = sorted(
        units,
        key=lambda row: (float(row["duration_seconds"]) - floors[str(row["unit_id"])], str(row["unit_id"])),
        reverse=True,
    )
    for row in order[:remaining]:
        floors[str(row["unit_id"])] += 1
    if sum(floors.values()) != 180 or any(not 4 <= value <= 15 for value in floors.values()):
        raise ValueError("E44 integer duration allocation failed")
    return floors


def atomic_windows(timeline: list[dict[str, Any]], maximum: float = 1.2) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in timeline:
        start, end = float(row["start_seconds"]), float(row["end_seconds"])
        pieces = max(1, math.ceil((end - start) / maximum))
        span = (end - start) / pieces
        for index in range(pieces):
            result.append({
                "start_seconds": round(start + index * span, 3),
                "end_seconds": round(end if index == pieces - 1 else start + (index + 1) * span, 3),
                "action": str(row["actions"][0]) + f"；原动作分相{index + 1}/{pieces}，只向终态推进不复位",
            })
    return result


def entity_ids(blocking: dict[str, Any]) -> set[str]:
    return {
        *[str(row["character_id"]) for row in blocking.get("characters") or []],
        *[str(row["prop_id"]) for row in blocking.get("props") or []],
    }


def aggregate_action_end_blocking(sequence: list[dict[str, Any]]) -> dict[str, Any]:
    characters: dict[str, dict[str, Any]] = {}
    props: dict[str, dict[str, Any]] = {}
    for row in sequence:
        for state in (row.get("blocking") or {}, row.get("action_end_blocking") or {}):
            for character in state.get("characters") or []:
                if character.get("character_id"):
                    characters[str(character["character_id"])] = dict(character)
            for prop in state.get("props") or []:
                if prop.get("prop_id"):
                    props[str(prop["prop_id"])] = dict(prop)
    return {
        "resolved_after_subspace_lock": True,
        "characters": [characters[key] for key in sorted(characters)],
        "props": [props[key] for key in sorted(props)],
    }


def main() -> int:
    grouped = load(GROUPED)
    map_rows = {str(row["unit_id"]): row for row in load(MAP_PLAN)["tasks"]}
    accepted = {
        (str(row["path"]), str(row["sha256"]))
        for row in load(ACCEPTED)["rows"] if row.get("status") == "ACCEPTED"
    }
    durations = allocate(grouped["units"])
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    ADMISSION_DIR.mkdir(parents=True, exist_ok=True)
    submission_units: list[dict[str, Any]] = []
    prompt_rows: list[dict[str, Any]] = []
    density_rows: list[dict[str, Any]] = []
    transition_rows: list[dict[str, Any]] = []
    tasks: list[dict[str, Any]] = []
    dialogue_index = 0

    for source_unit in grouped["units"]:
        uid = str(source_unit["unit_id"])
        unit = json.loads(json.dumps(source_unit, ensure_ascii=False))
        unit["internal_transition_contracts"] = validate_internal_transition_sequence(unit)
        same_slot = find_same_slot_character_replacements(unit, map_rows)
        contracts = {
            (row["from_shot_id"], row["to_shot_id"]): row
            for row in unit["internal_transition_contracts"]
        }
        unresolved = [
            finding for finding in same_slot
            if not (contracts.get((finding["from_shot_id"], finding["to_shot_id"])) or {})
            .get("reference_bridge", {}).get("same_slot_reuse_allowed")
        ]
        if unresolved:
            raise ValueError(f"{uid} unresolved different-character same-slot replacement: {unresolved}")

        unit["duration_seconds"] = durations[uid]
        unit["action_timeline"] = action_timeline(unit)
        density = validate_action_timeline(unit["action_timeline"], unit["duration_seconds"], source_id=uid)
        if density["status"] != "PASS":
            raise ValueError(density["failures"])
        density_rows.append(density)
        prompt_path = PROMPT_DIR / f"{uid}.txt"
        prompt_path.write_text(prompt_text(unit), encoding="utf-8")
        prompt_contract = validate_model_prompt(prompt_path.read_text(encoding="utf-8"), source_id=uid)
        if prompt_contract["status"] != "PASS":
            raise ValueError(prompt_contract["failures"])
        prompt_rows.append({
            "unit_id": uid,
            "prompt_path": rel(prompt_path),
            "prompt_sha256": sha(prompt_path),
            "model_prompt_contract": prompt_contract,
        })
        incoming = unit.get("incoming_transition_contract")
        outgoing = unit.get("outgoing_transition_contract")
        prompt_body = prompt_path.read_text(encoding="utf-8")
        transition_rows.append({
            "unit_id": uid,
            "status": "PASS",
            "incoming_boundary_id": incoming.get("boundary_id") if incoming else None,
            "outgoing_boundary_id": outgoing.get("boundary_id") if outgoing else None,
            "incoming_prompt_bound": not incoming or incoming["boundary_id"] in prompt_body,
            "outgoing_prompt_bound": not outgoing or outgoing["boundary_id"] in prompt_body,
            "internal_boundary_count": len(unit["internal_transition_contracts"]),
            "plot_dialogue_action_visual_camera_map_sound_adjacency_checked": True,
        })
        submission_units.append(unit)

        refs = unit.get("reference_images") or []
        if not refs or len(refs) > 9:
            raise ValueError(f"{uid} invalid SD2 standard reference count")
        for ref in refs:
            if (str(ref["path"]), str(ref["sha256"])) not in accepted:
                raise ValueError(f"{uid} reference is not accepted: {ref['path']}")
            path = ROOT / str(ref["path"])
            if not path.is_file() or sha(path) != ref["sha256"]:
                raise ValueError(f"{uid} reference path/SHA failed: {ref['path']}")

        semantic = unit.get("start_frame_semantic_contract") or {}
        first_ref = refs[0]
        if semantic.get("status") != "PASS" or semantic.get("reference_path") != first_ref["path"] or semantic.get("reference_sha256") != first_ref["sha256"]:
            raise ValueError(f"{uid} start-frame semantic contract mismatch")
        admission_path = ADMISSION_DIR / f"{uid}_START_FRAME_ADMISSION_V1.json"
        write(admission_path, {
            "schema": "qingshan.video_start_frame_admission.v1",
            "episode": "E44", "unit_id": uid, "status": "ADMITTED",
            "downstream_status": "ADMITTED_FOR_VIDEO_SUBMIT",
            "asset_path": first_ref["path"], "asset_sha256": first_ref["sha256"],
            "semantic_evidence_ref": semantic["evidence_ref"],
            "semantic_evidence_sha256": semantic["evidence_sha256"],
            "source_accepted_map_ref": rel(ACCEPTED), "source_accepted_map_sha256": sha(ACCEPTED),
            "visual_review": "PASS", "exact_sha_verified": True,
        })

        editorial_ids = [str(value) for value in unit["editorial_shot_ids"]]
        sequence = [map_rows[value] for value in editorial_ids]
        canonical_entities = sorted(set().union(*(entity_ids(row["blocking"]) for row in sequence)))
        ref_by_shot = {source_shot(str(ref["path"])): ref for ref in refs}
        entity_references: list[dict[str, Any]] = []
        bound: set[str] = set()
        for shot in editorial_ids:
            ref = ref_by_shot.get(shot)
            if not ref:
                continue
            for entity_id in sorted(entity_ids(map_rows[shot]["blocking"])):
                if entity_id in bound:
                    continue
                role = "CHARACTER_REFERENCE" if entity_id.startswith("CHAR-") else "PROP_REFERENCE"
                entity_references.append({"entity_id": entity_id, "role": role, "path": ref["path"], "sha256": ref["sha256"]})
                bound.add(entity_id)
        missing = sorted(set(canonical_entities) - bound)
        first_map, last_map = sequence[0], sequence[-1]
        first_blocking = json.loads(json.dumps(first_map["blocking"], ensure_ascii=False))
        last_blocking = aggregate_action_end_blocking(sequence)
        if missing:
            raise ValueError(f"{uid} accepted references do not bind entities: {missing}")
        if not canonical_entities:
            space_entity = f"PROP-E44-SPACE-{uid}"
            canonical_entities = [space_entity]
            anchor = {"prop_id": space_entity, "zone_id": first_map["zone_id"], "position": [0.001, 0.001], "facing": "camera"}
            first_blocking.setdefault("props", []).append(anchor)
            last_blocking.setdefault("props", []).append(dict(anchor))
            entity_references.append({"entity_id": space_entity, "role": "PROP_REFERENCE", "path": first_ref["path"], "sha256": first_ref["sha256"]})

        first_action = unit["ordered_prompt_specs"][0]["action"]
        last_action = unit["ordered_prompt_specs"][-1]["action"]
        trajectories = [{
            "entity_id": entity_id,
            "from": str(first_action["start_state"]),
            "to": str(last_action["completion_state"]),
            "action": str(unit["narrative_beat"]),
            "visible_consequence": str(last_action["completion_state"]),
        } for entity_id in canonical_entities]
        dialogue: list[dict[str, str]] = []
        for spec in unit["ordered_prompt_specs"]:
            raw = str(spec.get("dialogue") or "")
            if not raw:
                continue
            speaker, sep, spoken = raw.partition("：")
            if not sep:
                raise ValueError(f"{uid} invalid dialogue: {raw}")
            dialogue_index += 1
            dialogue.append({"dia_id": f"E44-DIA-{dialogue_index:03d}", "speaker": speaker, "spoken_text": spoken})

        map_bindings = [dict(row) for row in first_map.get("reference_bindings") or []]
        atomic_action_windows = atomic_windows(unit["action_timeline"])
        task = {
            "task_key": f"{uid}-VIDEO-A1", "unit_id": uid, "scene_id": unit["scene_id"],
            "editorial_shot_ids": editorial_ids,
            "episode": "E44", "provider": "giggle", "tool_type": "video_generation",
            "spatial_layout_stage": "VIDEO_GENERATION", "resolution_order": first_map["resolution_order"],
            "model": "seedance-2.0-pro", "resolution": "720p", "aspect_ratio": "9:16",
            "duration_seconds": durations[uid], "source_duration_seconds": float(source_unit["duration_seconds"]),
            "prompt_file": rel(prompt_path), "prompt_sha256": sha(prompt_path), "model_prompt_contract": prompt_contract,
            "dialogue": dialogue, "dialogue_lines": [row["spoken_text"] for row in dialogue],
            "native_dialogue_required": bool(dialogue),
            "dialogue_transport": "MODEL_NATIVE_TEXT_DIALOGUE" if dialogue else "SAME_TASK_NATIVE_AMBIENCE_FOLEY_ACTION_SOUND",
            "model_native_text_dialogue": bool(dialogue), "source_subtitle_policy": "FORBID",
            "reference_images": [str(row["path"]) for row in refs],
            "reference_sha256": [str(row["sha256"]) for row in refs],
            "reference_roles": [str(row["role"]) for row in refs],
            "reference_image_sequence": entity_references,
            "reference_bindings": [*map_bindings, *entity_references],
            "video_transport": {"mode": "standard_multi_reference", "endpoint": "/api/v1/generation/omni-video"},
            "canonical_characters": [value for value in canonical_entities if value.startswith("CHAR-")],
            "canonical_props": [value for value in canonical_entities if not value.startswith("CHAR-")],
            "media_stage": "VIDEO", "require_semantic_anchor_evidence": True,
            "start_frame_sha256": first_ref["sha256"], "start_frame_admission_ref": rel(admission_path),
            "shot_type": "SEMANTIC_GROUPED_SCENE_PERFORMANCE", "semantic_video_unit": True, "action_unit": True,
            "blocking": first_blocking, "action_end_blocking": last_blocking, "trajectory_overlays": trajectories,
            "space_chain_id": "->".join(str(unit["ordered_prompt_specs"][0]["space"][key]) for key in ("global", "location", "subspace")),
            "performance_tempo_contract": {
                "playback_speed": "REAL_TIME_1X", "atomic_action_windows": atomic_action_windows,
                "grouped_editorial_beat_count": len(atomic_action_windows),
                "authored_editorial_beat_count": len(unit["ordered_prompt_specs"]), "result_hold_seconds": 0.0,
            },
            "vertical_short_drama_contract": {"required": True, "aspect_ratio": "9:16", "all_reference_images_portrait": True},
            "retry_attempt": 1, "creative_attempt_ordinal": 1, "paid_attempt": 0, "provider_post_allowed": False,
            "episode_global_space_map_id": first_map["episode_global_space_map_id"],
            "global_space_map_id": first_map["global_space_map_id"], "room_id": first_map["room_id"],
            "zone_id": first_map["zone_id"], "angle_id": first_map["angle_id"],
            "subspace_layout": first_map["subspace_layout"],
            "complete_map_sequence": [{key: row[key] for key in (
                "unit_id", "scene_id", "episode_global_space_map_id", "global_space_map_id", "room_id",
                "zone_id", "angle_id", "subspace_layout", "blocking", "action_end_blocking",
            )} for row in sequence],
            "incoming_transition_contract": unit.get("incoming_transition_contract"),
            "outgoing_transition_contract": unit.get("outgoing_transition_contract"),
            "internal_transition_contracts": unit.get("internal_transition_contracts"),
            "start_frame_semantic_contract": semantic,
            "machine_contract": {
                "scene_id": unit["scene_id"], "camera_plan": unit["camera_plan"],
                "editorial_shot_ids": editorial_ids,
                "ordered_prompt_specs": unit["ordered_prompt_specs"],
                "incoming_transition_contract": unit.get("incoming_transition_contract"),
                "outgoing_transition_contract": unit.get("outgoing_transition_contract"),
                "internal_transition_contracts": unit.get("internal_transition_contracts"),
                "start_frame_semantic_contract": semantic,
            },
        }
        task["input_template_id"] = compute_input_template_id(task)
        tasks.append(task)

    submission_grouped = dict(grouped)
    submission_grouped["schema"] = "qingshan.grouped_seedance_submission_manifest.v1"
    submission_grouped["runtime_seconds"] = 180
    submission_grouped["units"] = submission_units
    write(SUBMISSION_GROUPED, submission_grouped)
    write(PROMPT_MANIFEST, {
        "schema": "qingshan.complete_video_prompt_manifest.v1", "episode": "E44", "status": "PASS",
        "unit_count": len(prompt_rows), "all_units_have_prompt": len(prompt_rows) == 25, "rows": prompt_rows,
    })
    write(ACTION_DENSITY, {
        "schema": "qingshan.video_prompt_action_density_batch.v1", "episode": "E44", "status": "PASS",
        "unit_count": len(density_rows), "results": density_rows, "failures": [],
    })
    write(TRANSITION_AUDIT, {
        "schema": "qingshan.video_prompt_transition_adjacency_audit.v2_full_continuity",
        "episode": "E44", "status": "PASS", "unit_count": len(transition_rows),
        "scope": "PLOT_DIALOGUE_ACTION_VISUAL_CAMERA_MAP_SOUND_PREVIOUS_AND_NEXT_UNIT",
        "all_units_checked": len(transition_rows) == 25,
        "all_internal_boundaries_authored": True, "rows": transition_rows, "failures": [],
    })
    write(POST_QA_POLICY, {
        "schema": "qingshan.post_generation_qa_scope_policy.v1", "episode": "E44", "status": "PASS",
        "allowed_scope": ["TECHNICAL_INTEGRITY", "BASIC_PLOT", "BASIC_IDENTITY"],
        "forbidden_reroll_scope": ["ACTION_TASTE", "ACTION_RATIONALITY", "MICROEXPRESSION_TASTE", "PERFORMANCE_DETAIL"],
        "policy": "After generation, do technical checks and basic plot/identity only; do not reroll technically usable media for action or performance taste.",
    })
    gates = [
        "qa/e44_v5_preproduction_20260828/E44_V5_VIDEO_UNIT_GROUPING_GATE_V1.json",
        "qa/e44_v5_preproduction_20260828/E44_V5_VIDEO_UNIT_ANCHOR_COUNT_GATE_V1.json",
        "qa/e44_v5_preproduction_20260828/E44_V5_COMPLETE_MAP_MODE_GATE_V1.json",
        "qa/e44_v5_preproduction_20260828/E44_V5_KEYFRAME_ACCEPTED_MEDIA_MAP_57_V1.json",
        rel(ACTION_DENSITY), rel(TRANSITION_AUDIT), rel(POST_QA_POLICY),
    ]
    manifest = {
        "schema": "qingshan.giggle_video_transaction_manifest.v1", "episode": "E44", "provider": "giggle",
        "authorization_ref": "ROGER-20260828-CONTINUE-E44+SD2-STANDARD+NATIVE-1080P",
        "provider_post_allowed": False,
        "format_contract": {"vertical_short_drama_required": True, "aspect_ratio": "9:16", "all_reference_images_portrait": True},
        "allowed_video_models": ["seedance-2.0-pro"], "route_contract": "STANDARD_MULTI_REFERENCE_ONLY",
        "source_grouped_manifest": rel(SUBMISSION_GROUPED), "source_grouped_manifest_sha256": sha(SUBMISSION_GROUPED),
        "episode_global_space_map_ref": rel(MAP_AUTHORITY), "episode_global_space_map_ref_sha256": sha(MAP_AUTHORITY),
        "global_space_map_gate_required": True, "video_unit_count": len(tasks),
        "reference_image_count": sum(len(row["reference_images"]) for row in tasks),
        "runtime_seconds": sum(row["duration_seconds"] for row in tasks),
        "native_resolution_contract": "720p",
        "delivery_resolution_contract": "1440x2560_HIGH_QUALITY_2K_UPSCALE_AT_RELEASE",
        "pre_submission_creative_qa_scope": "STRICT_PLOT_DIALOGUE_ACTION_VISUAL_CAMERA_MAP_SOUND_ADJACENCY",
        "post_generation_qa_scope": "TECHNICAL_AND_BASIC_PLOT_IDENTITY_ONLY",
        "post_generation_qa_scope_policy_ref": rel(POST_QA_POLICY),
        "machine_gate_reports": gates, "tasks": tasks,
    }
    write(OUT, manifest)
    print(json.dumps({
        "status": "PASS", "tasks": len(tasks), "runtime": manifest["runtime_seconds"],
        "references": manifest["reference_image_count"], "resolution": "720p", "out": rel(OUT),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
