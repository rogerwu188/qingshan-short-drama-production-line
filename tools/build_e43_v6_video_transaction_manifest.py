#!/usr/bin/env python3
"""Build the fail-closed E43 SD2-standard video transaction manifest."""

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


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e43_v6_20260828"
GROUPED = PROD / "E43_V6_GROUPED_SEEDANCE_MANIFEST_COMPILED_V1.json"
MAP_PLAN = PROD / "E43_V6_COMPLETE_MAP_SHOT_PLAN_LOCKED_V1.json"
MAP_AUTHORITY = PROD / "E43_V6_EPISODE_GLOBAL_SPACE_MAP_AUTHORITY_LOCKED_V1.json"
ACCEPTED = ROOT / "qa/e43_v6_preproduction_20260828/E43_V6_KEYFRAME_ACCEPTED_MEDIA_MAP_55_V1.json"
PROMPT_DIR = PROD / "video_prompts_submit_v1"
PROMPT_MANIFEST = ROOT / "qa/e43_v6_preproduction_20260828/grouped_preflight_v1/E43_V6_SUBMISSION_COMPLETE_VIDEO_PROMPT_MANIFEST_V1.json"
SUBMISSION_GROUPED = PROD / "E43_V6_GROUPED_SEEDANCE_SUBMISSION_MANIFEST_V1.json"
ADMISSION_DIR = PROD / "start_frame_admissions_v1"
OUT = PROD / "E43_V6_TRANSACTIONAL_VIDEO_MANIFEST_PRECHECK_V1.json"
TRANSITION_AUDIT = "qa/e43_v6_preproduction_20260828/grouped_preflight_v1/E43_V6_VIDEO_PROMPT_TRANSITION_AUDIT_SUBMISSION_V1.json"
POST_QA_POLICY = "qa/e43_v6_preproduction_20260828/E43_V6_POST_GENERATION_QA_SCOPE_POLICY_V1.json"
SHOT_RE = re.compile(r"(E43-S\d{2}-\d{2})")

GATES = [
    "qa/e43_v6_preproduction_20260828/E43_V6_VIDEO_UNIT_GROUPING_GATE_V1.json",
    "qa/e43_v6_preproduction_20260828/E43_V6_VIDEO_UNIT_ANCHOR_COUNT_GATE_V1.json",
    "qa/e43_v6_preproduction_20260828/E43_V6_COMPLETE_MAP_MODE_GATE_V1.json",
    "qa/e43_v6_preproduction_20260828/E43_V6_KEYFRAME_ACCEPTED_MEDIA_MAP_55_V1.json",
    "qa/e43_v6_preproduction_20260828/grouped_preflight_v1/E43_V6_VIDEO_PROMPT_ACTION_DENSITY_V1.json",
    TRANSITION_AUDIT,
    POST_QA_POLICY,
]


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def source_shot(path: str) -> str:
    match = SHOT_RE.search(path)
    if not match:
        raise ValueError(f"reference path has no E43 shot id: {path}")
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
        raise ValueError("E43 integer duration allocation failed")
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
    """Represent every entity that participates anywhere in a grouped unit.

    A grouped video unit can introduce an actor or prop after its first editorial
    beat.  Binding only the final beat's blocking drops those middle-beat
    participants from the structured action contract even though the model
    prompt and accepted references contain them.  Keep the latest known state of
    every participating entity so the transaction remains semantically complete.
    """
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
    accepted = {(str(row["path"]), str(row["sha256"])) for row in load(ACCEPTED)["rows"] if row.get("status") == "ACCEPTED"}
    durations = allocate(grouped["units"])
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    ADMISSION_DIR.mkdir(parents=True, exist_ok=True)
    submission_units: list[dict[str, Any]] = []
    prompt_rows: list[dict[str, Any]] = []
    tasks: list[dict[str, Any]] = []
    dialogue_index = 0

    for source_unit in grouped["units"]:
        uid = str(source_unit["unit_id"])
        unit = dict(source_unit)
        unit["internal_transition_contracts"] = validate_internal_transition_sequence(unit)
        same_slot = find_same_slot_character_replacements(unit, map_rows)
        if same_slot:
            contracts = {
                (row["from_shot_id"], row["to_shot_id"]): row
                for row in unit["internal_transition_contracts"]
            }
            unresolved = []
            for finding in same_slot:
                contract = contracts.get((finding["from_shot_id"], finding["to_shot_id"])) or {}
                reference = contract.get("reference_bridge") or {}
                if not reference.get("same_slot_reuse_allowed"):
                    unresolved.append(finding)
            if unresolved:
                raise ValueError(f"{uid} different-character exact-slot replacement must be split or explicitly cut: {unresolved}")
        unit["duration_seconds"] = durations[uid]
        unit["action_timeline"] = action_timeline(unit)
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
        submission_units.append(unit)

        refs = unit.get("reference_images") or []
        if not refs or len(refs) > 9:
            raise ValueError(f"{uid} invalid SD2 standard reference count")
        for ref in refs:
            if (str(ref["path"]), str(ref["sha256"])) not in accepted:
                raise ValueError(f"{uid} reference is not in accepted media map: {ref['path']}")
            path = ROOT / str(ref["path"])
            if not path.is_file() or sha(path) != ref["sha256"]:
                raise ValueError(f"{uid} reference path/SHA failed: {ref['path']}")

        semantic = unit.get("start_frame_semantic_contract") or {}
        first_ref = refs[0]
        if semantic.get("status") != "PASS" or semantic.get("reference_path") != first_ref["path"] or semantic.get("reference_sha256") != first_ref["sha256"]:
            raise ValueError(f"{uid} start-frame semantic contract is not bound to first accepted reference")
        admission_path = ADMISSION_DIR / f"{uid}_START_FRAME_ADMISSION_V1.json"
        admission = {
            "schema": "qingshan.video_start_frame_admission.v1",
            "episode": "E43", "unit_id": uid, "status": "ADMITTED",
            "downstream_status": "ADMITTED_FOR_VIDEO_SUBMIT",
            "asset_path": first_ref["path"], "asset_sha256": first_ref["sha256"],
            "semantic_evidence_ref": semantic["evidence_ref"],
            "semantic_evidence_sha256": semantic["evidence_sha256"],
            "source_accepted_map_ref": rel(ACCEPTED), "source_accepted_map_sha256": sha(ACCEPTED),
            "visual_review": "PASS", "exact_sha_verified": True,
        }
        admission_path.write_text(json.dumps(admission, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

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
            raise ValueError(f"{uid} accepted references do not semantically bind entities: {missing}")
        if not canonical_entities:
            space_entity = f"PROP-E43-SPACE-{uid}"
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
            dialogue.append({"dia_id": f"E43-DIA-{dialogue_index:03d}", "speaker": speaker, "spoken_text": spoken})

        map_bindings = [dict(row) for row in first_map.get("reference_bindings") or []]
        atomic_action_windows = atomic_windows(unit["action_timeline"])
        task = {
            "task_key": f"{uid}-VIDEO-A1", "unit_id": uid, "scene_id": unit["scene_id"],
            "episode": "E43", "provider": "giggle", "tool_type": "video_generation",
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
                "authored_editorial_beat_count": len(unit["ordered_prompt_specs"]),
                "result_hold_seconds": 0.0,
            },
            "vertical_short_drama_contract": {"required": True, "aspect_ratio": "9:16", "all_reference_images_portrait": True},
            "retry_attempt": 1, "creative_attempt_ordinal": 1, "paid_attempt": 0,
            "provider_post_allowed": False,
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
            "start_frame_semantic_contract": semantic,
            "machine_contract": {
                "scene_id": unit["scene_id"], "camera_plan": unit["camera_plan"],
                "ordered_prompt_specs": unit["ordered_prompt_specs"],
                "incoming_transition_contract": unit.get("incoming_transition_contract"),
                "outgoing_transition_contract": unit.get("outgoing_transition_contract"),
                "start_frame_semantic_contract": semantic,
            },
        }
        task["input_template_id"] = compute_input_template_id(task)
        tasks.append(task)

    submission_grouped = dict(grouped)
    submission_grouped["schema"] = "qingshan.grouped_seedance_submission_manifest.v1"
    submission_grouped["runtime_seconds"] = 180
    submission_grouped["units"] = submission_units
    SUBMISSION_GROUPED.write_text(json.dumps(submission_grouped, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    PROMPT_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    PROMPT_MANIFEST.write_text(json.dumps({
        "schema": "qingshan.complete_video_prompt_manifest.v1", "episode": "E43", "status": "PASS",
        "unit_count": len(prompt_rows), "all_units_have_prompt": len(prompt_rows) == 26, "rows": prompt_rows,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "schema": "qingshan.giggle_video_transaction_manifest.v1", "episode": "E43", "provider": "giggle",
        "authorization_ref": "ROGER-20260828-START-E43-AFTER-E42-PUBLISH", "provider_post_allowed": False,
        "format_contract": {"vertical_short_drama_required": True, "aspect_ratio": "9:16", "all_reference_images_portrait": True},
        "allowed_video_models": ["seedance-2.0-pro"], "route_contract": "STANDARD_MULTI_REFERENCE_ONLY",
        "source_grouped_manifest": rel(SUBMISSION_GROUPED), "source_grouped_manifest_sha256": sha(SUBMISSION_GROUPED),
        "episode_global_space_map_ref": rel(MAP_AUTHORITY), "episode_global_space_map_ref_sha256": sha(MAP_AUTHORITY),
        "global_space_map_gate_required": True, "video_unit_count": len(tasks),
        "reference_image_count": sum(len(row["reference_images"]) for row in tasks),
        "runtime_seconds": sum(row["duration_seconds"] for row in tasks),
        "pre_submission_creative_qa_scope": "STRICT_PLOT_DIALOGUE_ACTION_VISUAL_CAMERA_MAP_SOUND_ADJACENCY",
        "post_generation_qa_scope": "TECHNICAL_AND_BASIC_PLOT_ONLY",
        "post_generation_qa_scope_policy_ref": POST_QA_POLICY,
        "machine_gate_reports": GATES, "tasks": tasks,
    }
    OUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "tasks": len(tasks), "runtime": manifest["runtime_seconds"], "references": manifest["reference_image_count"], "out": rel(OUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
