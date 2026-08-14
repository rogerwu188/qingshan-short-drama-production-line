#!/usr/bin/env python3
import copy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
SOURCE = PROD / "E36_U12_EPISODE_PARALLEL_BATCH_V1.json"
PLAN = PROD / "E36_NATURAL_VIDEO_UNITS_AND_ANCHOR_PLAN_V1.json"
PROMPT = PROD / "video_prompts_repair_v3/E36-CW-U10-R1.txt"
ANCHOR = ROOT / "working_assets/e36_v2_stills_20260728/repair_v2_candidates/E36_E36-CW-U10-A1-STILL-V2_dfa4a764-90b3-453a-a31e-ba4c4118e334.png"
JIAOTU = ROOT / "working_assets/e32_reference_single_subject_20260723/jiaotu_front_single.jpg"
OUT = PROD / "E36_U10_EPISODE_PARALLEL_BATCH_V1.json"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


config = json.loads(SOURCE.read_text())
plan = json.loads(PLAN.read_text())
unit = next(row for row in plan["units"] if row["unit_id"] == "U10")
task = copy.deepcopy(config["tasks"][0])

config.update({
    "status": "READY_INCREMENTAL_UNITS",
    "concurrency": 1,
    "max_retries": 0,
    "targeted_unit_replacement": True,
    "qa_dir": "qa/e36_v2_stills_repair_20260729/u10_video_runtime",
    "mechanical_default_plan_ref": "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/E36_NATURAL_VIDEO_UNITS_AND_ANCHOR_PLAN_V1.json",
    "anchor_count_plan_ref": "qa/e36_v2_stills_repair_20260729/u10_video_runtime/E36_U10_ANCHOR_COUNT_PLAN_V1.json",
    "common_sense_causality_plan_ref": "qa/e36_v2_stills_repair_20260729/u10_video_runtime/E36_U10_COMMON_SENSE_CAUSALITY_PLAN_V1.json",
    "period_lock_plan_ref": "qa/e36_v2_stills_repair_20260729/u10_video_runtime/E36_U10_PERIOD_LOCK_PLAN_V1.json"
})

task.update({
    "task_key": "E36-CW-U10-VIDEO-V1",
    "source_id": "E36-CW-U10",
    "batch_id": "E36-U10-VIDEO-V1",
    "unit_id": "U10",
    "scene_id": "E36-CW-S02",
    "visual_zone": "E36-U10-CANONICAL",
    "duration": 10,
    "duration_seconds": 10,
    "edit_target_duration_seconds": 10,
    "prompt_file": str(PROMPT.relative_to(ROOT)),
    "prompt_path": str(PROMPT.relative_to(ROOT)),
    "prompt_sha256": sha(PROMPT),
    "reference_images": [str(JIAOTU.relative_to(ROOT)), str(ANCHOR.relative_to(ROOT))],
    "reference_image_sequence": [{
        "asset_label": "@图片1",
        "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE",
        "path": str(JIAOTU.relative_to(ROOT)),
        "sha256": sha(JIAOTU),
        "state_id": "CHAR-皎兔-古装",
        "identity_reference": True
    }, {
        "asset_label": "@图片2",
        "role": "START_MOTION_ACTION_ANCHOR",
        "path": str(ANCHOR.relative_to(ROOT)),
        "sha256": sha(ANCHOR),
        "state_id": "E36-CW-U10-A1",
        "identity_reference": False
    }],
    "planned_reference_image_count": 1,
    "state_reference_minimum": 1,
    "dialogue": [],
    "native_dialogue_required": False,
    "reference_audios": [],
    "reference_audio_asset_ids": [],
    "dialogue_audio_assets": [],
    "performance_spec": {
        "schema": "qingshan.performance_generation_spec.v2",
        "episode": "E36",
        "unit_id": "U10",
        "duration_seconds": 10,
        "prop_ownership": {"阴神": "皎兔眉心血痕引出，只贴近递信人耳侧而不接触"},
        "motion_beats": [{
            **unit["physical_beats"][0],
            "intent": "辨明递信人是否知道皎兔真实身份",
            "visible_causality": "阖眼和血痕亮起之后，阴神才由皎兔方向延伸至递信人耳侧",
            "expression": "皎兔由专注探查转为冷静确认，递信人紧张僵住",
            "viewer_read": "阴神完成辨谎，递信人的供词可以继续采信"
        }]
    },
    "keyframe_interpolation_gate": {
        "status": "PASS",
        "stage": "CANDIDATE_PREFLIGHT",
        "anchor_count": 1,
        "checked_adjacent_pairs": 0,
        "candidate_recheck_required": False,
        "reason": "单一进行态首帧支撑同空间连续辨谎动作。"
    },
    "visual_entity_ids": ["jiaotu", "courier"],
    "multimodal_entity_bindings": [{
        "entity_id": "jiaotu",
        "character_name": "皎兔",
        "registry_id": "CHAR-皎兔-古装",
        "visual_reference": str(JIAOTU.relative_to(ROOT)),
        "visual_reference_sha256": sha(JIAOTU),
        "identity_image_slot": "@图片1",
        "voice_reference_asset_id": "x2ucerh9xoo",
        "dialogue_audio_slots": [],
        "visible_speaker": False,
        "lip_sync": False,
        "prop_owners": {"眉心血痕": "皎兔激活并控制亮度"},
        "ability_owners": ["阴神辨谎"]
    }],
    "qa_dir": "qa/e36_v2_stills_repair_20260729/u10_video_runtime",
    "status": "READY_TO_SUBMIT",
    "dependencies_ready": True,
    "audio_reference_optional": True,
    "inherits_establishing_coverage": True,
    "targeted_unit_replacement": True,
    "effect_provenance": [{
        "effect": "阴神",
        "source_type": "CLAUDE_SCRIPT",
        "source_ref": "workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md#9-2"
    }]
})

task["multimodal_binding_sha256"] = hashlib.sha256(
    json.dumps(task["multimodal_entity_bindings"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()

config["tasks"] = [task]
OUT.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
print(OUT)
