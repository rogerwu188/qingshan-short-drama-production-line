#!/usr/bin/env python3
"""Compile grouped Seedance units into the deployed mixed-transport contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

import cv2

try:
    from tools.shot_media_admission_gate import compute_input_template_id
    from tools.grouped_internal_continuity_contract import validate_internal_transition_sequence
except ModuleNotFoundError:
    from shot_media_admission_gate import compute_input_template_id
    from grouped_internal_continuity_contract import validate_internal_transition_sequence


ROOT = Path(__file__).resolve().parents[1]
SHOT_RE = re.compile(r"(E\d+-S\d{2}-\d{2})")


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


def resolve(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def raw_rgb_sha(path: Path) -> str:
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError(f"cannot decode {path}")
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    height, width = rgb.shape[:2]
    return hashlib.sha256(width.to_bytes(8, "big") + height.to_bytes(8, "big") + rgb.tobytes()).hexdigest()


def portrait_dimensions(path: Path) -> tuple[int, int]:
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError(f"cannot decode {path}")
    height, width = bgr.shape[:2]
    if width >= height:
        raise ValueError(
            f"VERTICAL_SHORT_DRAMA_REFERENCE_NOT_PORTRAIT: {rel(path)} is {width}x{height}"
        )
    return width, height


def entity_id(kind: str, name: str) -> str:
    return f"{kind}-E41-{name}"


def shot_id(path: str) -> str:
    match = SHOT_RE.search(path)
    if not match:
        raise ValueError(f"reference path has no shot id: {path}")
    return match.group(1)


def latest_q1(shot: str, expected_sha: str) -> Path:
    matches: list[tuple[int, Path]] = []
    for path in (ROOT / "qa/e41_v17_keyframes").glob(f"{shot}-Q1-V*.json"):
        try:
            row = load(path)
            version = int(re.search(r"-V(\d+)\.json$", path.name).group(1))
        except (AttributeError, ValueError, json.JSONDecodeError):
            continue
        if row.get("status") == "PASS" and row.get("candidate_sha256") == expected_sha:
            matches.append((version, path))
    if not matches:
        raise ValueError(f"no exact-SHA PASS Q1 for {shot}:{expected_sha}")
    return max(matches)[1]


def allocate_integer_durations(units: list[dict[str, Any]], target: int) -> dict[str, int]:
    floors = {row["unit_id"]: math.floor(float(row["duration_seconds"])) for row in units}
    remaining = target - sum(floors.values())
    order = sorted(
        units,
        key=lambda row: (float(row["duration_seconds"]) - floors[row["unit_id"]], row["unit_id"]),
        reverse=True,
    )
    for row in order[:remaining]:
        floors[row["unit_id"]] += 1
    if sum(floors.values()) != target or any(not 3 <= value <= 12 for value in floors.values()):
        raise ValueError("integer duration allocation violates 180s/3-12s contract")
    return floors


def block(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "characters": [
            {
                "character_id": entity_id("CHAR", str(row["character"])),
                "screen_slot": row.get("screen_slot") or "UNSPECIFIED",
                "depth_plane": row.get("depth_plane") or "UNSPECIFIED",
            }
            for row in spec.get("cast") or []
        ],
        "props": [
            {
                "prop_id": entity_id("PROP", str(row["prop"])),
                "screen_slot": row.get("anchor") or "UNSPECIFIED",
            }
            for row in spec.get("props") or []
        ],
        "state": str((spec.get("action") or {}).get("start_state") or "CONTINUOUS_SCENE_STATE"),
    }


def standard_reference_transport() -> dict[str, str]:
    """Return the only operator-visible SD2 standard reference route."""
    return {
        "mode": "standard_multi_reference",
        "endpoint": "/api/v1/generation/omni-video",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--grouped", required=True)
    parser.add_argument("--base-config", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--admission-dir", required=True)
    parser.add_argument(
        "--unit-id", action="append", default=[],
        help="Compile only the named already-admissible unit; repeat to stream a safe subset.",
    )
    args = parser.parse_args()
    grouped_path = resolve(args.grouped)
    base_path = resolve(args.base_config)
    grouped = load(grouped_path)
    base = load(base_path)
    base_tasks = {row["unit_id"]: row for row in base.get("tasks") or []}
    all_units = grouped.get("units") or []
    durations = allocate_integer_durations(all_units, 180)
    if args.unit_id:
        requested = set(args.unit_id)
        available = {str(row["unit_id"]) for row in all_units}
        unknown = sorted(requested - available)
        if unknown:
            raise ValueError(f"unknown grouped unit ids: {unknown}")
        units = [row for row in all_units if str(row["unit_id"]) in requested]
    else:
        units = all_units
    admission_dir = resolve(args.admission_dir)
    admission_dir.mkdir(parents=True, exist_ok=True)
    tasks: list[dict[str, Any]] = []

    orientation_failures: list[str] = []
    for unit in units:
        uid = str(unit["unit_id"])
        for ref in unit.get("reference_images") or []:
            path = resolve(str(ref["path"]))
            if not path.is_file():
                orientation_failures.append(f"{uid}:REFERENCE_MISSING:{rel(path)}")
                continue
            if sha(path) != str(ref["sha256"]):
                orientation_failures.append(f"{uid}:REFERENCE_SHA_MISMATCH:{rel(path)}")
                continue
            try:
                portrait_dimensions(path)
            except ValueError as exc:
                orientation_failures.append(f"{uid}:{exc}")
    if orientation_failures:
        raise ValueError("VERTICAL_SHORT_DRAMA_REFERENCE_GATE_FAILED | " + " | ".join(orientation_failures))

    for unit in units:
        uid = str(unit["unit_id"])
        unit["internal_transition_contracts"] = validate_internal_transition_sequence(unit)
        original = dict(base_tasks[uid])
        refs = unit.get("reference_images") or []
        specs = unit.get("ordered_prompt_specs") or []
        if not refs or not specs:
            raise ValueError(f"{uid} missing references or prompt specs")
        first_ref = refs[0]
        first_shot = shot_id(str(first_ref["path"]))
        q1_path = latest_q1(first_shot, str(first_ref["sha256"]))
        admission_path = admission_dir / f"{uid}_START_FRAME_ADMISSION_V1.json"
        admission = {
            "schema": "qingshan.video_start_frame_admission.v1",
            "episode": "E41",
            "unit_id": uid,
            "status": "ADMITTED",
            "downstream_status": "ADMITTED_FOR_VIDEO_SUBMIT",
            "asset_path": first_ref["path"],
            "asset_sha256": first_ref["sha256"],
            "source_q1_ref": rel(q1_path),
            "source_q1_sha256": sha(q1_path),
        }
        admission_path.write_text(json.dumps(admission, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        all_characters = sorted({
            entity_id("CHAR", str(row["character"]))
            for spec in specs for row in spec.get("cast") or []
            if str(row.get("face_visibility") or "") != "OFFSCREEN_VOICE_ONLY"
        })
        all_props = sorted({
            entity_id("PROP", str(row["prop"]))
            for spec in specs for row in spec.get("props") or []
        })
        by_shot = {shot_id(str(ref["path"])): ref for ref in refs}
        bindings: list[dict[str, Any]] = []
        bound: set[str] = set()
        editorial_ids = unit.get("editorial_shot_ids") or []
        for source_shot, spec in zip(editorial_ids, specs):
            ref = by_shot.get(str(source_shot))
            if not ref:
                continue
            for row in spec.get("cast") or []:
                if str(row.get("face_visibility") or "") == "OFFSCREEN_VOICE_ONLY":
                    continue
                eid = entity_id("CHAR", str(row["character"]))
                if eid not in bound:
                    bindings.append({"entity_id": eid, "role": "CHARACTER_REFERENCE", "path": ref["path"], "sha256": ref["sha256"]})
                    bound.add(eid)
            for row in spec.get("props") or []:
                eid = entity_id("PROP", str(row["prop"]))
                if eid not in bound:
                    bindings.append({"entity_id": eid, "role": "PROP_REFERENCE", "path": ref["path"], "sha256": ref["sha256"]})
                    bound.add(eid)
        if set(all_characters + all_props) != bound:
            missing = sorted(set(all_characters + all_props) - bound)
            raise ValueError(f"{uid} semantic anchor plan did not bind {missing}")

        first, last = specs[0], specs[-1]
        first_action = first.get("action") or {}
        last_action = last.get("action") or {}
        start_time = float(first_action.get("t0_seconds") or 0.0)
        windows = [
            {
                "start_seconds": round(float((spec.get("action") or {}).get("t0_seconds") or 0.0) - start_time, 3),
                "end_seconds": round(float((spec.get("action") or {}).get("t1_seconds") or 0.0) - start_time, 3),
                "action": str((spec.get("action") or {}).get("primary_action") or "CONTINUOUS_PERFORMANCE"),
            }
            for spec in specs
        ]
        trajectories = [
            {
                "entity_id": eid,
                "from": str(first_action.get("start_state") or "UNIT_START_STATE"),
                "to": str(last_action.get("completion_state") or "UNIT_COMPLETION_STATE"),
                "action": unit.get("narrative_beat") or "CONTINUOUS_ORDERED_EDITORIAL_BEATS",
                "visible_consequence": str(last_action.get("completion_state") or "ORDERED_BEATS_COMPLETE"),
            }
            for eid in all_characters + all_props
        ]
        if not trajectories:
            trajectories = [{
                "entity_id": f"SPACE-{unit['scene_id']}",
                "from": str(first_action.get("start_state") or "UNIT_START_STATE"),
                "to": str(last_action.get("completion_state") or "UNIT_COMPLETION_STATE"),
                "action": unit.get("narrative_beat") or "CONTINUOUS_ORDERED_EDITORIAL_BEATS",
                "visible_consequence": str(last_action.get("completion_state") or "ORDERED_BEATS_COMPLETE"),
            }]
        start_block = block(first)
        end_block = {**block(last), "state": str(last_action.get("completion_state") or "UNIT_COMPLETION_STATE")}
        represented_characters = {row["character_id"] for row in start_block["characters"] + end_block["characters"]}
        represented_props = {row["prop_id"] for row in start_block["props"] + end_block["props"]}
        start_block["characters"].extend(
            {"character_id": eid, "screen_slot": "LATER_ORDERED_APPEARANCE", "depth_plane": "DEFINED_BY_EDITORIAL_BEAT"}
            for eid in all_characters if eid not in represented_characters
        )
        start_block["props"].extend(
            {"prop_id": eid, "screen_slot": "LATER_ORDERED_APPEARANCE"}
            for eid in all_props if eid not in represented_props
        )
        dialogue_lines = [str(row["spoken_text"]) for row in original.get("dialogue") or []]
        task = {
            **original,
            "episode": "E41",
            "provider": "giggle",
            "duration_seconds": durations[uid],
            "source_duration_seconds": unit["duration_seconds"],
            "aspect_ratio": "9:16",
            "model": "seedance-2.0-pro",
            "resolution": "720p",
            "reference_images": [str(row["path"]) for row in refs],
            "reference_sha256": [str(row["sha256"]) for row in refs],
            "reference_roles": ["SEMANTIC_REFERENCE"] * len(refs),
            "reference_image_sequence": bindings,
            "reference_bindings": bindings,
            "canonical_characters": all_characters,
            "canonical_props": all_props,
            "media_stage": "VIDEO",
            "require_semantic_anchor_evidence": True,
            "start_frame_sha256": first_ref["sha256"],
            "start_frame_admission_ref": rel(admission_path),
            "shot_type": "SEMANTIC_GROUPED_SCENE_PERFORMANCE",
            "semantic_video_unit": True,
            "scene_id": unit["scene_id"],
            "incoming_transition_contract": unit.get("incoming_transition_contract"),
            "outgoing_transition_contract": unit.get("outgoing_transition_contract"),
            "internal_transition_contracts": unit.get("internal_transition_contracts"),
            "start_frame_semantic_contract": unit.get("start_frame_semantic_contract"),
            "action_unit": True,
            "blocking": start_block,
            "action_end_blocking": end_block,
            "trajectory_overlays": trajectories,
            "space_chain_id": "->".join(str((first.get("space") or {}).get(key) or "UNSPECIFIED") for key in ("global", "location", "subspace")),
            "performance_tempo_contract": {
                "playback_speed": "REAL_TIME_1X",
                "atomic_action_windows": windows,
                "grouped_editorial_beat_count": len(windows),
                "result_hold_seconds": 0.0,
            },
            "dialogue_lines": dialogue_lines,
            "native_dialogue_required": bool(dialogue_lines),
            "dialogue_transport": "MODEL_NATIVE_TEXT_DIALOGUE" if dialogue_lines else "SAME_TASK_NATIVE_AMBIENCE_FOLEY_ACTION_SOUND",
            "model_native_text_dialogue": bool(dialogue_lines),
            "source_subtitle_policy": "FORBID",
            "retry_attempt": 1,
            "creative_attempt_ordinal": 1,
            "paid_attempt": 0,
            "provider_post_allowed": False,
            "vertical_short_drama_contract": {
                "required": True,
                "aspect_ratio": "9:16",
                "all_reference_images_portrait": True,
            },
        }
        machine_contract = dict(task.get("machine_contract") or {})
        machine_contract.update({
            "scene_id": unit["scene_id"],
            "camera_plan": unit.get("camera_plan"),
            "ordered_prompt_specs": specs,
            "incoming_transition_contract": unit.get("incoming_transition_contract"),
            "outgoing_transition_contract": unit.get("outgoing_transition_contract"),
            "internal_transition_contracts": unit.get("internal_transition_contracts"),
            "start_frame_semantic_contract": unit.get("start_frame_semantic_contract"),
        })
        task["machine_contract"] = machine_contract
        task["video_transport"] = standard_reference_transport()
        task["input_template_id"] = compute_input_template_id(task)
        tasks.append(task)

    manifest = {
        "schema": "qingshan.giggle_video_transaction_manifest.v1",
        "episode": "E41",
        "provider": "giggle",
        "format_contract": {
            "vertical_short_drama_required": True,
            "aspect_ratio": "9:16",
            "all_reference_images_portrait": True,
        },
        "allowed_video_models": ["seedance-2.0-pro"],
        "source_grouped_manifest": rel(grouped_path),
        "source_grouped_manifest_sha256": sha(grouped_path),
        "source_base_config": rel(base_path),
        "source_base_config_sha256": sha(base_path),
        "video_unit_count": len(tasks),
        "source_video_unit_count": len(all_units),
        "excluded_unit_ids": [str(row["unit_id"]) for row in all_units if row not in units],
        "reference_image_count": sum(len(row["reference_images"]) for row in tasks),
        "runtime_seconds": sum(row["duration_seconds"] for row in tasks),
        "machine_gate_reports": [
            "qa/e41_v17_keyframes/E41_CAPABILITY_REFERENCES_IDENTITY_ADMISSION_REPORT_V3.json",
            "qa/e41_v17_video_units/E41_V17_VIDEO_UNIT_ANCHOR_COUNT_GATE_V2.json",
            "qa/e41_v17_grouped_video_preflight/E41_V17_COMPLETE_VIDEO_PROMPT_MANIFEST_GATE_V1.json",
            "qa/e41_v17_grouped_video_preflight/E41_V17_DIALOGUE_MANIFEST_COVERAGE_GATE_V1.json",
            "qa/e41_v17_grouped_video_preflight/E41_V17_ACTION_DENSITY_REPORT_V1.json",
            "qa/e41_v17_grouped_video_preflight/E41_V17_GENERATION_FIRST_PASS_POLICY_GATE_V1.json",
        ],
        "tasks": tasks,
    }
    out = resolve(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "tasks": len(tasks), "references": manifest["reference_image_count"], "runtime": manifest["runtime_seconds"], "out": rel(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
