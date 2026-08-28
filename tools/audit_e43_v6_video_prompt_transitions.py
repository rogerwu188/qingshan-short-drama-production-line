#!/usr/bin/env python3
"""Audit every E43 video prompt for transition, performance and AV completeness."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(
    manifest: dict[str, Any],
    prompt_manifest: dict[str, Any],
    map_plan: dict[str, Any],
    accepted_media: dict[str, Any],
    generation_contract: dict[str, Any],
) -> dict[str, Any]:
    failures: list[str] = []
    rows: list[dict[str, Any]] = []
    boundary_rows: list[dict[str, Any]] = []
    boundary_prompt_counts: Counter[str] = Counter()
    prompt_by_unit = {str(row["unit_id"]): row for row in prompt_manifest.get("rows") or []}
    map_by_shot = {str(row["unit_id"]): row for row in map_plan.get("tasks") or []}
    accepted = {
        (str(row.get("path")), str(row.get("sha256"))): row
        for row in accepted_media.get("rows") or [] if row.get("status") == "ACCEPTED"
    }
    canonical_by_shot = {str(row["shot_id"]): row for row in generation_contract.get("shots") or []}
    scene_state = {str(row["scene_id"]): row for row in generation_contract.get("scene_states") or []}
    units = manifest.get("units") or []
    observed_dialogue: list[tuple[str, str]] = []
    required_phrases = (
        "竖屏9:16", "720p", "seedance-2.0-pro（SD2 标准版）",
        "【镜头硬合同】", "【转场硬合同】", "入场边界=", "入场预留=",
        "出场边界=", "片尾转场预留=", "出场交棒=", "片尾剧情动作=",
        "末态必须保持=", "声尾=", "剧情动机=", "【视觉与现场声硬合同】",
        "【节拍】", "物理动作链：", "表演硬锁：", "表情弧=", "微动作=",
        "事件反应=", "身体同步=", "【同任务原生声音】",
    )
    forbidden_phrases = (
        "seedance-2.0-fast", "16:9", "镜头随主要动作平稳调整景别",
        "缓慢推镜", "缓慢推进", "静止等待", "保持站位", "保持不动",
    )
    for index, unit in enumerate(units):
        unit_id = str(unit.get("unit_id"))
        prompt_row = prompt_by_unit.get(unit_id)
        unit_failures: list[str] = []
        if not prompt_row:
            unit_failures.append("PROMPT_MANIFEST_ROW_MISSING")
            rows.append({"unit_id": unit_id, "status": "FAIL", "failures": unit_failures})
            failures.extend(f"{unit_id}:{item}" for item in unit_failures)
            continue
        prompt_path = resolve(str(prompt_row["prompt_path"]))
        if not prompt_path.is_file():
            unit_failures.append("PROMPT_FILE_MISSING")
            text = ""
        else:
            text = prompt_path.read_text(encoding="utf-8")
            if sha256(prompt_path) != prompt_row.get("prompt_sha256"):
                unit_failures.append("PROMPT_SHA_MISMATCH")
        for phrase in required_phrases:
            if phrase not in text:
                unit_failures.append(f"REQUIRED_PROMPT_FIELD_MISSING:{phrase}")
        for phrase in forbidden_phrases:
            if phrase in text:
                unit_failures.append(f"FORBIDDEN_PROMPT_LANGUAGE:{phrase}")
        for marker in ("【镜头硬合同】", "【转场硬合同】", "入场边界=", "出场边界=", "片尾转场预留="):
            if text.count(marker) != 1:
                unit_failures.append(f"PROMPT_MARKER_COUNT:{marker}:{text.count(marker)}")

        specs = unit.get("ordered_prompt_specs") or []
        editorial_ids = unit.get("editorial_shot_ids") or []
        if len(specs) != len(editorial_ids):
            unit_failures.append("EDITORIAL_SHOT_SPEC_COUNT_MISMATCH")
        beat_section = text.partition("【节拍】")[2].partition("【同任务原生声音】")[0]
        for shot_id, spec in zip(editorial_ids, specs):
            canonical = canonical_by_shot.get(str(shot_id))
            mapped = map_by_shot.get(str(shot_id))
            if not canonical:
                unit_failures.append(f"CANONICAL_SHOT_MISSING:{shot_id}")
                continue
            action = spec.get("action") or {}
            if str(action.get("primary_action") or "") != str(canonical.get("frame_content") or ""):
                unit_failures.append(f"CANONICAL_PLOT_ACTION_MISMATCH:{shot_id}")
            if str(spec.get("dialogue") or "") != str(canonical.get("dialogue") or ""):
                unit_failures.append(f"CANONICAL_DIALOGUE_MISMATCH:{shot_id}")
            dialogue = str(spec.get("dialogue") or "")
            if dialogue:
                speaker, sep, spoken = dialogue.partition("：")
                if not sep or beat_section.count(f"{speaker}说：“{spoken}”") != 1:
                    unit_failures.append(f"DIALOGUE_BEAT_EXACT_OCCURRENCE_FAILED:{shot_id}")
                observed_dialogue.append((str(shot_id), dialogue))
            if not mapped:
                unit_failures.append(f"COMPLETE_MAP_SHOT_MISSING:{shot_id}")
                continue
            space = spec.get("space") or {}
            expected_scene = scene_state.get(str(canonical.get("scene_id"))) or {}
            if mapped.get("scene_id") != canonical.get("scene_id"):
                unit_failures.append(f"MAP_SCENE_MISMATCH:{shot_id}")
            if space.get("subspace") != (mapped.get("subspace_layout") or {}).get("subspace_id"):
                unit_failures.append(f"MAP_SUBSPACE_MISMATCH:{shot_id}")
            if space.get("location") != expected_scene.get("location_id"):
                unit_failures.append(f"MAP_LOCATION_MISMATCH:{shot_id}")
            for field in ("episode_global_space_map_id", "global_space_map_id", "room_id", "zone_id", "angle_id"):
                if not str(mapped.get(field) or "").strip():
                    unit_failures.append(f"MAP_BINDING_FIELD_MISSING:{shot_id}:{field}")
        for reference in unit.get("reference_images") or []:
            key = (str(reference.get("path")), str(reference.get("sha256")))
            accepted_row = accepted.get(key)
            reference_path = resolve(key[0])
            if not accepted_row:
                unit_failures.append(f"REFERENCE_NOT_IN_ACCEPTED_MEDIA_MAP:{key[0]}")
            elif int(accepted_row.get("width", 0)) >= int(accepted_row.get("height", 0)):
                unit_failures.append(f"REFERENCE_NOT_PORTRAIT:{key[0]}")
            if not reference_path.is_file() or sha256(reference_path) != key[1]:
                unit_failures.append(f"REFERENCE_FILE_OR_SHA_FAILED:{key[0]}")
        semantic = unit.get("start_frame_semantic_contract") or {}
        if semantic.get("status") != "PASS" or semantic.get("space_match") is not True or semantic.get("camera_start_framing_match") is not True:
            unit_failures.append("START_FRAME_SEMANTIC_CONTRACT_FAILED")

        incoming = unit.get("incoming_transition_contract")
        outgoing = unit.get("outgoing_transition_contract")
        incoming_id = str(incoming["boundary_id"]) if incoming else "SEQUENCE_START"
        outgoing_id = str(outgoing["boundary_id"]) if outgoing else "SEQUENCE_END"
        for boundary_id in (incoming_id, outgoing_id):
            if text.count(boundary_id) != 1:
                unit_failures.append(f"BOUNDARY_BINDING_COUNT:{boundary_id}:{text.count(boundary_id)}")
            if boundary_id.startswith("BND-"):
                boundary_prompt_counts[boundary_id] += text.count(boundary_id)
        if index == 0 and incoming is not None:
            unit_failures.append("FIRST_UNIT_MUST_USE_SEQUENCE_START")
        if index > 0 and incoming is None:
            unit_failures.append("INTERIOR_UNIT_INCOMING_CONTRACT_MISSING")
        if index == len(units) - 1 and outgoing is not None:
            unit_failures.append("LAST_UNIT_MUST_USE_SEQUENCE_END")
        if index < len(units) - 1 and outgoing is None:
            unit_failures.append("INTERIOR_UNIT_OUTGOING_CONTRACT_MISSING")
        for direction, contract in (("incoming", incoming), ("outgoing", outgoing)):
            if not contract:
                continue
            handle_key = "incoming_handle_seconds" if direction == "incoming" else "outgoing_handle_seconds"
            handle = float(contract.get(handle_key, -1))
            if not 0.6 <= handle <= 1.5:
                unit_failures.append(f"TRANSITION_HANDLE_OUT_OF_RANGE:{direction}:{handle}")
            for key in ("plot_motivation", "visual_bridge", "action_bridge", "sound_bridge", "axis_strategy"):
                if not str(contract.get(key) or "").strip():
                    unit_failures.append(f"TRANSITION_CONTRACT_FIELD_MISSING:{direction}:{key}")
        if outgoing and index + 1 < len(units):
            next_incoming = units[index + 1].get("incoming_transition_contract") or {}
            if outgoing.get("boundary_id") != next_incoming.get("boundary_id"):
                unit_failures.append("ADJACENT_BOUNDARY_ID_MISMATCH")
            if outgoing != next_incoming:
                unit_failures.append("ADJACENT_TRANSITION_CONTRACT_NOT_IDENTICAL")
            previous_last = (specs[-1].get("action") or {}) if specs else {}
            next_specs = units[index + 1].get("ordered_prompt_specs") or []
            next_first = (next_specs[0].get("action") or {}) if next_specs else {}
            terminal = str(previous_last.get("completion_state") or "")
            initial = str(next_first.get("start_state") or "")
            boundary_failures: list[str] = []
            if terminal not in str(outgoing.get("visual_bridge") or "") or initial not in str(outgoing.get("visual_bridge") or ""):
                boundary_failures.append("VISUAL_BRIDGE_DOES_NOT_BIND_TERMINAL_AND_INITIAL_STATE")
            if terminal not in str(outgoing.get("action_bridge") or "") or initial not in str(outgoing.get("action_bridge") or ""):
                boundary_failures.append("ACTION_BRIDGE_DOES_NOT_BIND_TERMINAL_AND_INITIAL_STATE")
            previous_primary = str(previous_last.get("primary_action") or "").strip("。！？； ")
            next_primary = str(next_first.get("primary_action") or "").strip("。！？； ")
            motivation = str(outgoing.get("plot_motivation") or "")
            if previous_primary not in motivation or next_primary not in motivation:
                boundary_failures.append("PLOT_MOTIVATION_DOES_NOT_BIND_ADJACENT_BEATS")
            source_space = outgoing.get("source_terminal_state", {}).get("space")
            target_space = outgoing.get("target_initial_state", {}).get("space")
            if source_space != (specs[-1].get("space") if specs else None):
                boundary_failures.append("SOURCE_TERMINAL_MAP_SPACE_MISMATCH")
            if target_space != (next_specs[0].get("space") if next_specs else None):
                boundary_failures.append("TARGET_INITIAL_MAP_SPACE_MISMATCH")
            previous_camera = unit.get("camera_plan") or {}
            next_camera = units[index + 1].get("camera_plan") or {}
            if outgoing.get("source_terminal_state", {}).get("camera_framing") != previous_camera.get("end_framing"):
                boundary_failures.append("SOURCE_CAMERA_END_FRAMING_MISMATCH")
            if outgoing.get("target_initial_state", {}).get("camera_framing") != next_camera.get("start_framing"):
                boundary_failures.append("TARGET_CAMERA_START_FRAMING_MISMATCH")
            axis = str(outgoing.get("axis_strategy") or "")
            if str(previous_camera.get("camera_side")) not in axis or str(next_camera.get("camera_side")) not in axis:
                boundary_failures.append("AXIS_STRATEGY_DOES_NOT_BIND_BOTH_CAMERA_SIDES")
            boundary_rows.append({
                "boundary_id": outgoing.get("boundary_id"),
                "from_unit_id": unit_id,
                "to_unit_id": units[index + 1].get("unit_id"),
                "status": "PASS" if not boundary_failures else "FAIL",
                "plot_dialogue_action_visual_map_camera_sound_continuity_checked": True,
                "terminal_action_state": terminal,
                "initial_action_state": initial,
                "source_space": source_space,
                "target_space": target_space,
                "transition_device": outgoing.get("transition_device"),
                "failures": boundary_failures,
            })
            unit_failures.extend(f"BOUNDARY:{item}" for item in boundary_failures)

        failures.extend(f"{unit_id}:{item}" for item in unit_failures)
        rows.append({
            "unit_id": unit_id,
            "status": "PASS" if not unit_failures else "FAIL",
            "prompt_path": str(prompt_path.resolve().relative_to(ROOT)) if prompt_path.exists() else str(prompt_path),
            "prompt_sha256": sha256(prompt_path) if prompt_path.is_file() else None,
            "incoming_boundary_id": incoming_id,
            "outgoing_boundary_id": outgoing_id,
            "transition_prompt_present": "【转场硬合同】" in text,
            "outgoing_plot_transition_present": "片尾剧情动作=" in text,
            "camera_contract_present": "【镜头硬合同】" in text,
            "physical_action_design_present": "物理动作链：" in text,
            "microexpression_design_present": all(x in text for x in ("表情弧=", "微动作=", "事件反应=")),
            "native_av_contract_present": "【同任务原生声音】" in text,
            "failures": unit_failures,
        })

    expected_boundaries = max(0, len(units) - 1)
    if len(boundary_prompt_counts) != expected_boundaries:
        failures.append(f"BOUNDARY_UNIQUE_COUNT:{len(boundary_prompt_counts)}!={expected_boundaries}")
    for boundary_id, count in sorted(boundary_prompt_counts.items()):
        if count != 2:
            failures.append(f"BOUNDARY_PROMPT_OCCURRENCE_COUNT:{boundary_id}:{count}!=2")
    if len(rows) != 26:
        failures.append(f"E43_VIDEO_UNIT_COUNT:{len(rows)}!=26")
    canonical_dialogue = [
        (str(row["shot_id"]), str(row["dialogue"]))
        for row in generation_contract.get("shots") or [] if str(row.get("dialogue") or "")
    ]
    if observed_dialogue != canonical_dialogue:
        failures.append("GLOBAL_DIALOGUE_ORDER_OR_COVERAGE_MISMATCH")
    return {
        "schema": "qingshan.e43_v6_video_prompt_transition_audit.v1",
        "episode": "E43",
        "status": "PASS" if not failures else "FAIL",
        "video_unit_count": len(rows),
        "transition_boundary_count": len(boundary_prompt_counts),
        "all_video_prompts_have_incoming_and_outgoing_transition_information": not failures,
        "policy": {
            "outgoing_plot_transition_required_per_video": True,
            "transition_handle_seconds": {"minimum": 0.6, "maximum": 1.5},
            "camera_action_microexpression_native_av_required": True,
            "model": "seedance-2.0-pro",
            "resolution": "720p",
            "aspect_ratio": "9:16",
        },
        "rows": rows,
        "boundary_rows": boundary_rows,
        "boundary_prompt_counts": dict(sorted(boundary_prompt_counts.items())),
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--prompt-manifest", type=Path, required=True)
    parser.add_argument("--map-plan", type=Path, required=True)
    parser.add_argument("--accepted-media", type=Path, required=True)
    parser.add_argument("--generation-contract", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = audit(
        load(args.manifest), load(args.prompt_manifest), load(args.map_plan),
        load(args.accepted_media), load(args.generation_contract),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "video_unit_count": result["video_unit_count"],
        "transition_boundary_count": result["transition_boundary_count"],
        "failure_count": len(result["failures"]),
        "out": str(args.out),
    }, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
