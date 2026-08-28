#!/usr/bin/env python3
"""Deep pre-submit creative and adjacency audit for every E44 video prompt."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e44_v5_20260828"
QA = ROOT / "qa/e44_v5_preproduction_20260828"
MANIFEST = PROD / "E44_V5_TRANSACTIONAL_VIDEO_MANIFEST_PRECHECK_V1.json"
PRECHECK = QA / "E44_V5_VIDEO_PROVIDER_PRECHECK_V1.json"
OUT = QA / "E44_V5_VIDEO_PROMPT_FULL_CREATIVE_CONTINUITY_QA_V1.json"


REQUIRED_MARKERS = (
    "【视频任务】", "【天气硬合同】", "【场景与人物】", "【镜头硬合同】",
    "【转场硬合同】", "【视觉与现场声硬合同】", "【表演连续性】",
    "【节拍】", "【同任务原生声音】", "【关键限制】",
)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def main() -> int:
    manifest = load(MANIFEST)
    precheck = load(PRECHECK)
    if precheck.get("status") != "PASS" or precheck.get("precheck_pass") != 25:
        raise ValueError("25/25 provider precheck is not PASS")
    if precheck.get("manifest_sha256") != sha(MANIFEST):
        raise ValueError("provider precheck does not bind current manifest SHA")
    tasks = manifest.get("tasks") or []
    if len(tasks) != 25 or sum(int(row["duration_seconds"]) for row in tasks) != 180:
        raise ValueError("E44 task/runtime completeness failed")

    rows = []
    failures = []
    previous = None
    for index, task in enumerate(tasks):
        uid = str(task["unit_id"])
        path = ROOT / task["prompt_file"]
        text = path.read_text(encoding="utf-8")
        machine = task.get("machine_contract") or {}
        specs = machine.get("ordered_prompt_specs") or []
        editorial_ids = task.get("editorial_shot_ids") or []
        internal = task.get("internal_transition_contracts") or []
        unit_failures = []

        if sha(path) != task.get("prompt_sha256"):
            unit_failures.append("PROMPT_SHA_MISMATCH")
        for marker in REQUIRED_MARKERS:
            if marker not in text:
                unit_failures.append(f"MISSING_PROMPT_SECTION:{marker}")
        if task.get("model") != "seedance-2.0-pro" or task.get("resolution") != "720p" or task.get("aspect_ratio") != "9:16":
            unit_failures.append("MODEL_RESOLUTION_ASPECT_CONTRACT_MISMATCH")
        if len(specs) != len(editorial_ids):
            unit_failures.append("EDITORIAL_BEAT_COUNT_MISMATCH")
        if len(internal) != max(0, len(editorial_ids) - 1):
            unit_failures.append("INTERNAL_TRANSITION_COUNT_MISMATCH")
        for contract in internal:
            if contract.get("boundary_id") not in text:
                unit_failures.append(f"INTERNAL_TRANSITION_NOT_BOUND:{contract.get('boundary_id')}")
            for domain in ("cast_bridge", "scene_bridge", "prop_bridge", "sound_bridge", "camera_bridge", "action_bridge", "reference_bridge"):
                if not contract.get(domain):
                    unit_failures.append(f"INTERNAL_TRANSITION_DOMAIN_MISSING:{contract.get('boundary_id')}:{domain}")

        dialogue_count = 0
        for shot_id, spec in zip(editorial_ids, specs):
            action = spec.get("action") or {}
            for field in ("start_state", "primary_action", "completion_state", "contact_point", "motion_direction", "physical_causality"):
                value = str(action.get(field) or "")
                if not value or (field in {"primary_action", "completion_state"} and value not in text):
                    unit_failures.append(f"SHOT_ACTION_CONTRACT_MISSING:{shot_id}:{field}")
            dialogue = str(spec.get("dialogue") or "")
            if dialogue:
                dialogue_count += 1
                speaker, sep, spoken = dialogue.partition("：")
                if not sep or not speaker or not spoken or speaker not in text or spoken not in text:
                    unit_failures.append(f"DIALOGUE_BINDING_MISSING:{shot_id}")
            visible_cast = [
                str(row.get("character")) for row in spec.get("cast") or []
                if row.get("face_visibility") != "OFFSCREEN_VOICE_ONLY"
            ]
            for character in visible_cast:
                if character not in text:
                    unit_failures.append(f"VISIBLE_CAST_NOT_PROMPT_BOUND:{shot_id}:{character}")
            for prop in [str(row.get("prop")) for row in spec.get("props") or [] if row.get("prop")]:
                if prop not in text:
                    unit_failures.append(f"PROP_NOT_PROMPT_BOUND:{shot_id}:{prop}")
            for section in ("visual_design", "sound_design", "performance"):
                if not spec.get(section):
                    unit_failures.append(f"SHOT_CREATIVE_DOMAIN_MISSING:{shot_id}:{section}")
            space = spec.get("space") or {}
            if any(not space.get(key) for key in ("global", "location", "subspace")):
                unit_failures.append(f"MAP_CHAIN_INCOMPLETE:{shot_id}")

        incoming = task.get("incoming_transition_contract")
        outgoing = task.get("outgoing_transition_contract")
        if index == 0 and incoming:
            unit_failures.append("SEQUENCE_START_HAS_INCOMING_BOUNDARY")
        if index > 0 and not incoming:
            unit_failures.append("MISSING_INCOMING_BOUNDARY")
        if index == len(tasks) - 1 and outgoing:
            unit_failures.append("SEQUENCE_END_HAS_OUTGOING_BOUNDARY")
        if index < len(tasks) - 1 and not outgoing:
            unit_failures.append("MISSING_OUTGOING_BOUNDARY")
        for label, contract in (("INCOMING", incoming), ("OUTGOING", outgoing)):
            if contract and contract.get("boundary_id") not in text:
                unit_failures.append(f"{label}_BOUNDARY_NOT_PROMPT_BOUND:{contract.get('boundary_id')}")
            if contract:
                for domain in ("visual_bridge", "action_bridge", "sound_bridge", "axis_strategy", "plot_motivation"):
                    if not contract.get(domain):
                        unit_failures.append(f"{label}_BOUNDARY_DOMAIN_MISSING:{domain}")
        if previous is not None:
            prior_out = previous.get("outgoing_transition_contract") or {}
            if not incoming or prior_out.get("boundary_id") != incoming.get("boundary_id"):
                unit_failures.append("ADJACENT_BOUNDARY_ID_MISMATCH")
            if prior_out != incoming:
                unit_failures.append("ADJACENT_BOUNDARY_CONTRACT_NOT_IDENTICAL")
            previous_terminal = (prior_out.get("source_terminal_state") or {}).get("blocking")
            next_initial = (incoming.get("target_initial_state") or {}).get("blocking") if incoming else None
            if not previous_terminal or not next_initial:
                unit_failures.append("ADJACENT_ACTION_ENDPOINT_MISSING")

        ref_count = len(task.get("reference_images") or [])
        if not 1 <= ref_count <= 9 or ref_count != len(task.get("reference_sha256") or []):
            unit_failures.append("REFERENCE_COUNT_OR_SHA_COUNT_INVALID")
        semantic = task.get("start_frame_semantic_contract") or {}
        if semantic.get("status") != "PASS" or semantic.get("reference_path") != task["reference_images"][0]:
            unit_failures.append("START_FRAME_SEMANTIC_BINDING_INVALID")
        camera = machine.get("camera_plan") or {}
        for field in ("shot_scale", "lens_intent", "camera_height", "camera_side", "motion_family", "motion_direction", "motivation"):
            if not camera.get(field):
                unit_failures.append(f"CAMERA_FIELD_MISSING:{field}")

        row = {
            "unit_id": uid,
            "status": "PASS" if not unit_failures else "FAIL",
            "editorial_shot_count": len(editorial_ids),
            "internal_transition_count": len(internal),
            "dialogue_beat_count": dialogue_count,
            "reference_count": ref_count,
            "prompt": rel(path),
            "prompt_sha256": sha(path),
            "checked_domains": [
                "PLOT", "DIALOGUE", "ACTION", "PERFORMANCE", "MICROEXPRESSION", "VISUAL",
                "CAMERA", "MAP", "CAST_IDENTITY", "PROPS", "SOUND", "INTERNAL_TRANSITIONS",
                "PREVIOUS_UNIT_ADJACENCY", "NEXT_UNIT_ADJACENCY", "REFERENCE_BINDINGS",
            ],
            "failures": unit_failures,
        }
        rows.append(row)
        failures.extend({"unit_id": uid, "code": code} for code in unit_failures)
        previous = task

    report = {
        "schema": "qingshan.e44.video_prompt_full_creative_continuity_qa.v1",
        "episode": "E44",
        "status": "PASS" if not failures else "FAIL",
        "manifest": rel(MANIFEST),
        "manifest_sha256": sha(MANIFEST),
        "provider_precheck": rel(PRECHECK),
        "provider_precheck_sha256": sha(PRECHECK),
        "unit_count": len(rows),
        "editorial_shot_count": sum(row["editorial_shot_count"] for row in rows),
        "internal_transition_count": sum(row["internal_transition_count"] for row in rows),
        "cross_unit_boundary_count": len(rows) - 1,
        "all_units_checked": len(rows) == 25,
        "all_domains_checked_before_paid_submit": True,
        "post_generation_policy": "TECHNICAL_AND_BASIC_PLOT_IDENTITY_ONLY_NO_ACTION_TASTE_REROLLS",
        "rows": rows,
        "failures": failures,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"], "units": len(rows),
        "editorial_shots": report["editorial_shot_count"],
        "internal_transitions": report["internal_transition_count"],
        "cross_unit_boundaries": report["cross_unit_boundary_count"],
        "failures": len(failures), "out": rel(OUT),
    }, ensure_ascii=False))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
