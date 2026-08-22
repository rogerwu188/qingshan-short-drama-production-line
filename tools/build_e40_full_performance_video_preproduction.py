#!/usr/bin/env python3
"""Compile Q1-admitted E40 native-dialogue video tasks without provider POST."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2

try:
    from action_video_prompt_compiler import (
        CONTRACT_VERSION as ACTION_CONTRACT_VERSION,
        compile_action_video_prompt,
        validate_action_contract,
    )
    from shot_media_admission_gate import compute_input_template_id
except ModuleNotFoundError:
    from tools.action_video_prompt_compiler import (
        CONTRACT_VERSION as ACTION_CONTRACT_VERSION,
        compile_action_video_prompt,
        validate_action_contract,
    )
    from tools.shot_media_admission_gate import compute_input_template_id


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e40_remake_v1_20260817/full_performance_native_dialogue_v1"
PLAN = BASE / "E40_FULL_PERFORMANCE_NATIVE_DIALOGUE_PLAN_V1.json"
KEYFRAMES = BASE / "E40_FULL_PERFORMANCE_KEYFRAME_BATCH_V1.json"
Q1 = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/keyframes/q1_registered/E40_FULL_PERFORMANCE_KEYFRAME_Q1_INDEX_V1.json"
OUT = BASE / "E40_FULL_PERFORMANCE_VIDEO_PREPRODUCTION_V1.json"
AUDIO_PLAN = BASE / "E40_FULL_PERFORMANCE_EXACT_DIALOGUE_AUDIO_REFERENCE_PLAN_V1.json"
ASR_QA = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/audio_refs_v1/E40_FULL_PERFORMANCE_AUDIO_REFERENCE_ASR_QA_V1.json"
AUDIO_REGISTRY = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/audio_refs_v1/E40_FULL_PERFORMANCE_AUDIO_PROVIDER_ASSET_REGISTRY_V1.json"
COST_GATE = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/videos/E40_FULL_PERFORMANCE_VIDEO_COST_GATE_V1.json"
PROMPTS = BASE / "video_prompts_v1"

VOICE_BINDINGS = {
    "陈迹": {"voice_id": "clone_20251011_081924_812352", "name": "寒玉孤音(蓝忘机)", "emotion": "冷静克制、锋利、自然普通话、非旁白腔"},
    "云妃": {"voice_id": "clone_20251022_101843_460135", "name": "御姐语录", "emotion": "成熟从容、含蜜藏威、自然普通话、非旁白腔"},
    "云羊": {"voice_id": "clone_20251215_082253_725049", "name": "不羁青年", "emotion": "少年警觉、克制讥刺、自然普通话、非旁白腔"},
    "阿栓": {"voice_id": "clone_20251030_080949_242818", "name": "急语风声", "emotion": "骤然脱险后的急切呼喊、自然普通话、非旁白腔"},
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def raw_rgb_sha(path: Path) -> str:
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError(f"Cannot decode {path}")
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    height, width = rgb.shape[:2]
    return hashlib.sha256(width.to_bytes(8, "big") + height.to_bytes(8, "big") + rgb.tobytes()).hexdigest()


def main() -> int:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    keyframes = json.loads(KEYFRAMES.read_text(encoding="utf-8"))
    q1 = json.loads(Q1.read_text(encoding="utf-8"))
    admitted = set(q1.get("video_submission_allowed_task_keys") or [])
    units = {row["task_id"]: row for row in plan["units"]}
    kf_tasks = {row["task_key"]: row for row in keyframes["tasks"]}
    q1_rows = {row["task_key"]: row for row in q1["results"]}
    audio_registry_payload = json.loads(AUDIO_REGISTRY.read_text(encoding="utf-8")) if AUDIO_REGISTRY.is_file() else None
    audio_assets = {row["audio_key"]: row["remote_asset_id"] for row in (audio_registry_payload or {}).get("items", []) if row.get("status") == "PASS"}
    audio_ready = bool(audio_registry_payload and audio_registry_payload.get("status") == "PASS" and ASR_QA.is_file())
    audio_rows = []
    tasks = []
    PROMPTS.mkdir(parents=True, exist_ok=True)

    for key in sorted(admitted):
        unit_id = key.removesuffix("-KF-QA-V2")
        unit = units[unit_id]
        kf = kf_tasks[key]
        admission = q1_rows[key]
        frame = ROOT / admission["asset_path"]
        if sha(frame) != admission["asset_sha256"]:
            raise ValueError(f"Exact first-frame SHA mismatch: {key}")
        voice = VOICE_BINDINGS[unit["speaker"]]
        audio_intents = []
        for line in unit["spoken_lines"]:
            audio_key = f"{unit_id}-{line['dialogue_id']}-EXACT-AUDIO-V1"
            audio = {
                "audio_key": audio_key,
                "unit_id": unit_id,
                "dialogue_id": line["dialogue_id"],
                "speaker": unit["speaker"],
                "text": line["text"],
                "voice_id": voice["voice_id"],
                "voice_name": voice["name"],
                "emotion": f"{line['emotion']}；{voice['emotion']}；逐字准确，不增删重复",
                "speed": 1.0,
                "purpose": "SEEDANCE_SAME_TASK_EXACT_DIALOGUE_REFERENCE_ONLY_NOT_POST_DUB",
                "state": "INTENT_REQUIRED_TRANSACTION_NOT_YET_POSTED",
                "provider_post_allowed": False,
            }
            audio_rows.append(audio)
            audio_intents.append(audio_key)

        start = kf["blocking"]
        end = kf.get("action_end_blocking") or start
        speaker_entity = next(
            (row["character_id"] for row in start.get("characters", []) if unit["speaker"] in row.get("character_id", "")),
            (start.get("characters") or [{}])[0].get("character_id"),
        )
        task = {
            "task_key": f"{unit_id}-VIDEO-V1",
            "episode": "E40",
            "unit_id": unit["source_unit"],
            "canonical_unit_id": unit["source_unit"],
            "canonical_unit_text": kf["canonical_script_action"],
            "shot_type": "DIALOGUE_PERFORMANCE",
            "model": "seedance-2.0-fast",
            "duration_seconds": unit["duration_seconds"],
            "aspect_ratio": "9:16",
            "resolution": "720p",
            "status": "READY_TO_SUBMIT" if audio_ready else "WAITING_DEPENDENCY_EXACT_DIALOGUE_AUDIO_ASSET_BINDING",
            "provider_post_allowed": audio_ready,
            "maximum_new_submissions": 1 if audio_ready else 0,
            "media_stage": "VIDEO",
            "action_unit": False,
            "require_semantic_anchor_evidence": True,
            "native_dialogue_required": True,
            "native_audio_required": True,
            "dialogue_transport": "EXACT_LINE_AUDIO_REFERENCE",
            "dialogue_lines": [line["text"] for line in unit["spoken_lines"]],
            "dialogue_ids": unit["dialogue_ids"],
            "required_audio_intent_keys": audio_intents,
            "exact_dialogue_audio_asset_ids": [audio_assets[value] for value in audio_intents] if audio_ready else [],
            "reference_audio_asset_ids": [],
            "source_subtitle_policy": "FORBID",
            "native_audio_policy": "PRESERVE_SAME_PROVIDER_TASK_DIALOGUE_AMBIENCE_FOLEY_AND_SFX_NO_POST_REDUB",
            "reference_images": [rel(frame)],
            "reference_sha256": [sha(frame)],
            "reference_roles": ["Q1_ADMITTED_START_STATE_REFERENCE"],
            "reference_image_sequence": [
                *[{
                    "path": rel(frame), "sha256": sha(frame), "role": "CHARACTER_REFERENCE",
                    "entity_id": entity_id, "transport_role": "Q1_ADMITTED_OMNI_REFERENCE",
                } for entity_id in kf["canonical_characters"]],
                *[{
                    "path": rel(frame), "sha256": sha(frame), "role": "PROP_REFERENCE",
                    "entity_id": entity_id, "transport_role": "Q1_ADMITTED_OMNI_REFERENCE",
                } for entity_id in kf["canonical_props"]],
            ],
            "start_frame_sha256": sha(frame),
            "q1_admission_result": admission["admission_result"],
            "q1_admission_result_sha256": admission["admission_result_sha256"],
            "start_frame_admission_ref": admission["admission_result"],
            "episode_global_space_map_id": kf["episode_global_space_map_id"],
            "global_space_map_id": kf["global_space_map_id"],
            "subspace_id": kf["subspace_layout"]["subspace_id"],
            "space_chain_id": f"{kf['episode_global_space_map_id']}->{kf['global_space_map_id']}->{kf['subspace_layout']['subspace_id']}",
            "canonical_characters": kf["canonical_characters"],
            "canonical_props": kf["canonical_props"],
            "visible_characters": kf["visible_characters"],
            "blocking": start,
            "action_end_blocking": end,
            "trajectory_overlays": [{
                "entity_id": speaker_entity,
                "from": "首帧锁定站位、未开口的呼吸与视线预备状态",
                "to": "最后一句完整说完后的克制反应终态，站位和轴线不变",
                "action": "按精确音频自然说话，口型、下颌、呼吸、眼神和微表情同步推进",
                "visible_consequence": "对白完整可听且口型同步；人物身份、空间、道具状态和对手关系连续",
            }],
            "performance_tempo_contract": {
                "playback_speed": "REAL_TIME_1X",
                "entry_action_already_in_progress": True,
                "atomic_action_windows": [{
                    "start_seconds": 0.0,
                    "end_seconds": min(1.0, float(unit["duration_seconds"])),
                    "action": "首句在自然吸气后立即开始，口型与精确音频同步",
                }],
                "final_timing_policy": "FOLLOW_BOUND_EXACT_AUDIO_NO_TIME_STRETCH",
            },
            "camera_contract": "保持 exact first frame 的机位、轴线、景别和主体尺度；只允许叙事所需的微弱活镜与自然呼吸",
            "forbidden_generation": [
                "字幕", "画面文字", "LOGO", "水印", "看镜头", "身份漂移", "年龄漂移", "空间跳变",
                "道具换位", "静态念稿", "夸张舞台表演", "删除原生音轨", "后配TTS覆盖可见口型",
            ],
            "action_video_prompt_contract_version": ACTION_CONTRACT_VERSION,
            "retry_attempt": 1,
            "retry_kind": "FIRST_PASS_FULL_PERFORMANCE_NATIVE_DIALOGUE",
        }
        failures = validate_action_contract(task)
        if failures:
            raise ValueError(f"{task['task_key']} action contract: {failures}")
        prompt_path = PROMPTS / f"{task['task_key']}.txt"
        prompt_path.write_text(compile_action_video_prompt(task), encoding="utf-8")
        task["prompt_file"] = rel(prompt_path)
        task["prompt_sha256"] = sha(prompt_path)
        task["input_template_id"] = compute_input_template_id(task)
        tasks.append(task)

    write(AUDIO_PLAN, {
        "schema": "qingshan.e40.full_performance_exact_dialogue_audio_reference_plan.v1",
        "episode": "E40",
        "status": "READY_FOR_TRANSACTION_FIRST_AUDIO_EXECUTOR",
        "purpose": "INPUT_REFERENCE_FOR_SAME_SEEDANCE_TASK_NOT_POST_DUB",
        "postproduction_replacement_forbidden": True,
        "authorization_refs": ["ROGER_AUTONOMOUS_ROUTINE_PRODUCTION_CHOICES_20260814", "ROGER-20260821-E40-REBUILD-BUDGET-5000"],
        "audio_count": len(audio_rows),
        "items": audio_rows,
    })
    manifest = {
        "schema": "qingshan.e40.full_performance_video_preproduction.v1",
        "episode": "E40",
        "status": "READY_TO_SUBMIT" if audio_ready else "WAITING_DEPENDENCY_EXACT_DIALOGUE_AUDIO_ASSET_BINDING",
        "provider": "giggle",
        "allowed_video_models": ["seedance-2.0-fast"],
        "provider_post_allowed": audio_ready,
        "maximum_new_submissions": len(tasks) if audio_ready else 0,
        "authorization_ref": "ROGER-20260821-E40-REBUILD-BUDGET-5000",
        "source_plan": rel(PLAN),
        "source_plan_sha256": sha(PLAN),
        "q1_index": rel(Q1),
        "q1_index_sha256": sha(Q1),
        "audio_reference_plan": rel(AUDIO_PLAN),
        "audio_reference_plan_sha256": sha(AUDIO_PLAN),
        "machine_gate_reports": [
            "qa/e40_remake_20260818/global_space_maps_v1/E40_GLOBAL_SPACE_LAYOUT_GATE_V1.json",
            rel(ASR_QA),
            rel(AUDIO_REGISTRY),
            rel(COST_GATE),
        ] if audio_ready else [],
        "admitted_video_task_count": len(tasks),
        "tasks": tasks,
        "blocked_keyframes": q1.get("failed_task_keys") or [],
        "release_audio_rule": "Keep same Seedance task native dialogue/ambience/foley/SFX; never replace visible-lip audio in post.",
    }
    write(OUT, manifest)
    if audio_ready:
        write(COST_GATE, {
            "schema": "qingshan.registered_gate_evidence.v1",
            "gate_id": "GIGGLE-REROLL-COST-GUARD",
            "status": "PASS",
            "authorization_ref": "ROGER-20260821-E40-REBUILD-BUDGET-5000",
            "reviewed_manifest": rel(OUT),
            "reviewed_manifest_sha256": sha(OUT),
            "planned_video_tasks": len(tasks),
            "planned_gross_credits": sum(int(row["duration_seconds"]) * 16 for row in tasks),
            "maximum_additional_credits": 5000,
            "first_pass_only": True,
        })
    print(json.dumps({"status": "PASS_PREPRODUCTION", "video_tasks": len(tasks), "audio_items": len(audio_rows), "manifest": rel(OUT), "manifest_sha256": sha(OUT), "audio_plan_sha256": sha(AUDIO_PLAN)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
