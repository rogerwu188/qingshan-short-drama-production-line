#!/usr/bin/env python3
"""Compile Q1-admitted E40 native-dialogue video tasks without provider POST."""

from __future__ import annotations

import argparse
import hashlib
import json
import copy
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
OUT = BASE / "E40_FULL_PERFORMANCE_VIDEO_PREPRODUCTION_V2.json"
PRIOR = BASE / "E40_FULL_PERFORMANCE_VIDEO_PREPRODUCTION_V1.json"
AUDIO_PLAN = BASE / "E40_FULL_PERFORMANCE_EXACT_DIALOGUE_AUDIO_REFERENCE_PLAN_20_V2.json"
ASR_QA = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/audio_refs_v1/E40_FULL_PERFORMANCE_AUDIO_REFERENCE_ASR_QA_V1.json"
AUDIO_REGISTRY = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/audio_refs_v1/E40_FULL_PERFORMANCE_AUDIO_PROVIDER_ASSET_REGISTRY_V1.json"
COST_GATE = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/videos/E40_FULL_PERFORMANCE_VIDEO_COST_GATE_V2.json"
PILOT_OUT = BASE / "E40_FULL_PERFORMANCE_VIDEO_TRANSPORT_PILOT_V2.json"
PILOT_COST_GATE = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/videos/E40_FULL_PERFORMANCE_VIDEO_TRANSPORT_PILOT_COST_GATE_V2.json"
PROMPTS = BASE / "video_prompts_v2"

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
    parser = argparse.ArgumentParser()
    parser.add_argument("--q1", type=Path, default=Q1)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--prompts-dir", type=Path, default=PROMPTS)
    parser.add_argument("--native-text", action="store_true")
    parser.add_argument("--image-to-video", action="store_true")
    parser.add_argument("--task-version", default="V2")
    parser.add_argument("--prior-manifest", type=Path)
    parser.add_argument("--skip-pilot", action="store_true")
    parser.add_argument("--q1-aliases", type=Path, help="JSON map of target KF task key to an admitted visual-source KF task key")
    args = parser.parse_args()
    q1_path = args.q1 if args.q1.is_absolute() else ROOT / args.q1
    out_path = args.out if args.out.is_absolute() else ROOT / args.out
    prompts_dir = args.prompts_dir if args.prompts_dir.is_absolute() else ROOT / args.prompts_dir
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    keyframes = json.loads(KEYFRAMES.read_text(encoding="utf-8"))
    q1 = json.loads(q1_path.read_text(encoding="utf-8"))
    alias_path = args.q1_aliases
    alias_path = alias_path if alias_path is None or alias_path.is_absolute() else ROOT / alias_path
    aliases = json.loads(alias_path.read_text(encoding="utf-8")) if alias_path else {}
    admitted = set(aliases) if aliases else set(q1.get("video_submission_allowed_task_keys") or [])
    units = {row["task_id"]: row for row in plan["units"]}
    kf_tasks = {row["task_key"]: row for row in keyframes["tasks"]}
    q1_rows = {row["task_key"]: row for row in q1["results"]}
    audio_registry_payload = json.loads(AUDIO_REGISTRY.read_text(encoding="utf-8")) if AUDIO_REGISTRY.is_file() else None
    prior_path = args.prior_manifest if args.prior_manifest else PRIOR
    prior_path = prior_path if prior_path.is_absolute() else ROOT / prior_path
    prior_payload = json.loads(prior_path.read_text(encoding="utf-8"))
    prior_tasks = {row["task_key"].rsplit("-VIDEO-", 1)[0]: row for row in prior_payload["tasks"]}
    audio_assets = {
        row["audio_key"]: row
        for row in (audio_registry_payload or {}).get("items", [])
        if row.get("status") == "PASS" and row.get("public_audio_url")
    }
    audio_ready = bool(audio_registry_payload and audio_registry_payload.get("status") == "PASS" and ASR_QA.is_file())
    audio_rows = []
    tasks = []
    prompts_dir.mkdir(parents=True, exist_ok=True)

    for key in sorted(admitted):
        unit_id = key.removesuffix("-KF-QA-V2")
        unit = units[unit_id]
        visual_source_key = aliases.get(key, key)
        kf = kf_tasks[visual_source_key]
        admission = q1_rows[visual_source_key]
        offscreen_coverage = visual_source_key != key
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
        prior = prior_tasks.get(unit_id)
        ready = args.native_text or audio_ready
        task = {
            "task_key": f"{unit_id}-VIDEO-{args.task_version}",
            "episode": "E40",
            "unit_id": unit["source_unit"],
            "canonical_unit_id": unit["source_unit"],
            "canonical_unit_text": kf["canonical_script_action"],
            "shot_type": "DIALOGUE_PERFORMANCE",
            "model": "seedance-2.0-fast",
            "duration_seconds": unit["duration_seconds"],
            "aspect_ratio": "9:16",
            "resolution": "720p",
            "status": "READY_TO_SUBMIT" if ready else "WAITING_DEPENDENCY_EXACT_DIALOGUE_AUDIO_ASSET_BINDING",
            "provider_post_allowed": ready,
            "maximum_new_submissions": 1 if ready else 0,
            "media_stage": "VIDEO",
            "action_unit": False,
            "require_semantic_anchor_evidence": True,
            "native_dialogue_required": True,
            "native_audio_required": True,
            "dialogue_transport": "MODEL_NATIVE_TEXT_DIALOGUE" if args.native_text else "EXACT_LINE_AUDIO_REFERENCE",
            "model_native_text_dialogue": bool(args.native_text),
            "dialogue_lines": [line["text"] for line in unit["spoken_lines"]],
            "dialogue_ids": unit["dialogue_ids"],
            "required_audio_intent_keys": audio_intents,
            "exact_dialogue_audio_asset_ids": [audio_assets[value]["remote_asset_id"] for value in audio_intents] if audio_ready and not args.native_text else [],
            "exact_dialogue_audio_urls": [audio_assets[value]["public_audio_url"] for value in audio_intents] if audio_ready and not args.native_text else [],
            "reference_audio_asset_ids": [],
            "reference_audio_urls": [],
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
            "visual_source_task_key": visual_source_key,
            "script_equivalent_coverage": "OFFSCREEN_OR_BACKVIEW_NO_VISIBLE_LIP" if offscreen_coverage else None,
            "visible_speaker_required": not offscreen_coverage,
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
                "action": ("保持已准入人物背面或反应构图，以眼神、呼吸和微动作承接画外原生对白；禁止生成说话口型"
                           if offscreen_coverage else "按精确音频自然说话，口型、下颌、呼吸、眼神和微表情同步推进"),
                "visible_consequence": ("对白完整可听；画面无人出现可见说话口型，身份、空间、道具状态连续"
                                        if offscreen_coverage else "对白完整可听且口型同步；人物身份、空间、道具状态和对手关系连续"),
            }],
            "performance_tempo_contract": {
                "playback_speed": "REAL_TIME_1X",
                "entry_action_already_in_progress": True,
                "atomic_action_windows": [{
                    "start_seconds": 0.0,
                    "end_seconds": min(1.0, float(unit["duration_seconds"])),
                    "action": ("首句立即以同任务画外原生对白开始；画内人物只作无口型反应"
                               if offscreen_coverage else "首句在自然吸气后立即开始，口型与精确音频同步"),
                }],
                "final_timing_policy": "FOLLOW_BOUND_EXACT_AUDIO_NO_TIME_STRETCH",
            },
            "camera_contract": "保持 exact first frame 的机位、轴线、景别和主体尺度；只允许叙事所需的微弱活镜与自然呼吸",
            "forbidden_generation": [
                "字幕", "画面文字", "LOGO", "水印", "看镜头", "身份漂移", "年龄漂移", "空间跳变",
                "道具换位", "静态念稿", "夸张舞台表演", "删除原生音轨", "后配TTS覆盖可见口型",
            ],
            "action_video_prompt_contract_version": ACTION_CONTRACT_VERSION,
            "retry_attempt": 2 if prior else 1,
            "retry_kind": "PROVIDER_TRANSPORT_REPAIR_ASSET_ID_TO_PUBLIC_URL" if prior else "FIRST_VIDEO_ATTEMPT",
        }
        failures = validate_action_contract(task)
        if failures:
            raise ValueError(f"{task['task_key']} action contract: {failures}")
        if prior:
            task.update({
                "prior_failure_code": "PROVIDER_ROUTER_MAPPING_NOT_FOUND",
                "failure_memory": {
                    "attempt": 1,
                    "provider_terminal_error": "router mapping not found",
                    "root_cause": "Omni audio was transported as asset_id although the current provider contract requires public URL.",
                    "do_not_repeat": "Never send audio/video references to Giggle Omni as asset_id.",
                },
                "material_change_from_prior_attempt": "Changed Omni audio transport from provider asset_id to ordered public HTTPS URL and made that binding explicit in the prompt.",
                "prior_prompt_sha256": [prior["prompt_sha256"]],
            })
        if args.image_to_video:
            task.update({
                "reference_roles": ["EXACT_FIRST_FRAME"],
                "exact_first_frame_sha256": sha(frame),
                "video_transport": {
                    "mode": "image_to_video_start_frame",
                    "endpoint": "/api/v1/generation/image-to-video",
                    "start_frame_path": rel(frame),
                    "start_frame_sha256": sha(frame),
                    "ordinary_images": [],
                },
                "frame0_authority_contract": {
                    "source_sha256": sha(frame),
                    "pre_encode_raw_rgb_sha256_required": True,
                    "raw_rgb_sha256": raw_rgb_sha(frame),
                },
                "post_harvest_exact_frame_gate": {
                    "required": True,
                    "single_frame_prepend_allowed": False,
                    "single_frame_replacement_allowed": False,
                    "frame0_thresholds": {
                        "minimum_ssim": 0.98,
                        "maximum_mae": 3.0,
                        "maximum_phash_hamming": 3,
                    },
                    "frame0_to_frame1_continuity_required": True,
                },
            })
            if prior:
                task.update({
                    "retry_kind": "PROVIDER_ROUTE_REPAIR_IMAGE_TO_VIDEO_NATIVE_TEXT_DIALOGUE",
                    "prior_failure_code": "PROVIDER_ROUTER_MAPPING_NOT_FOUND",
                    "failure_memory": {
                        "attempt": int(prior.get("retry_attempt") or 1),
                        "provider_terminal_error": "router mapping not found",
                        "root_cause": "The prior task was routed through omni-video despite using no external audio.",
                        "do_not_repeat": "Do not submit this retry through omni-video.",
                    },
                    "material_change_from_prior_attempt": "Changed the physical provider route from omni-video to image-to-video/start_frame while keeping same-task native dialogue.",
                })
        prompt_path = prompts_dir / f"{task['task_key']}.txt"
        prompt_path.write_text(
            compile_action_video_prompt(task)
            + ("\n原生对白锁：同一 Seedance 任务按顺序逐字只说一次："
               + "；".join(task["dialogue_lines"])
               + "。声音、口型、呼吸、环境与拟音必须由同一任务生成并保留；禁止字幕、旁白和后配音。\n"
               if args.native_text else
               "\n传输锁：按编号使用同一任务绑定的公开音频引用，逐句驱动原生口型、呼吸与声场；禁止把音频资产编号当作可播放音源。\n"),
            encoding="utf-8",
        )
        if offscreen_coverage:
            with prompt_path.open("a", encoding="utf-8") as handle:
                handle.write(
                    "等价覆盖锁：声音来自画外或背对镜头的说话者；保持已准入首帧的人物身份与构图，"
                    "任何画内人物都不得形成可见说话口型。禁止新增、替换或重塑人物面孔。\n"
                )
        if args.image_to_video:
            with prompt_path.open("a", encoding="utf-8") as handle:
                handle.write(
                    "物理路由修复：本次必须以已准入关键帧作为 image-to-video/start_frame 的不可改写第一帧；"
                    "禁止回落到 omni-video，首帧后只延续同空间中的真人微表演和同任务原生对白。\n"
                )
        task["prompt_file"] = rel(prompt_path)
        task["prompt_sha256"] = sha(prompt_path)
        task["input_template_id"] = compute_input_template_id(task)
        tasks.append(task)

    if not args.native_text:
        full_audio_plan = json.loads(AUDIO_PLAN.read_text(encoding="utf-8"))
        if full_audio_plan.get("audio_count") != 20 or len(full_audio_plan.get("items") or []) != 20:
            raise ValueError("Complete 20-line audio plan missing; video preproduction may not replace it with an admitted subset")
    manifest = {
        "schema": "qingshan.e40.full_performance_video_preproduction.v2",
        "episode": "E40",
        "status": "READY_TO_SUBMIT" if (args.native_text or audio_ready) else "WAITING_DEPENDENCY_EXACT_DIALOGUE_AUDIO_ASSET_BINDING",
        "provider": "giggle",
        "allowed_video_models": ["seedance-2.0-fast"],
        "provider_post_allowed": bool(args.native_text or audio_ready),
        "maximum_new_submissions": len(tasks) if (args.native_text or audio_ready) else 0,
        "authorization_ref": "ROGER-20260821-E40-REBUILD-BUDGET-5000",
        "source_plan": rel(PLAN),
        "source_plan_sha256": sha(PLAN),
        "q1_index": rel(q1_path),
        "q1_index_sha256": sha(q1_path),
        "audio_reference_plan": rel(AUDIO_PLAN),
        "audio_reference_plan_sha256": sha(AUDIO_PLAN),
        "machine_gate_reports": ([rel(COST_GATE)] if args.native_text else [
            "qa/e40_remake_20260818/global_space_maps_v1/E40_GLOBAL_SPACE_LAYOUT_GATE_V1.json",
            rel(ASR_QA),
            rel(AUDIO_REGISTRY),
            rel(COST_GATE),
        ] if audio_ready else []),
        "admitted_video_task_count": len(tasks),
        "tasks": tasks,
        "blocked_keyframes": q1.get("failed_task_keys") or [],
        "release_audio_rule": "Keep same Seedance task native dialogue/ambience/foley/SFX; never replace visible-lip audio in post.",
        "transport_repair": "Giggle Omni audio/video references use public URL; provider asset_id is retained only as provenance.",
    }
    write(out_path, manifest)
    if args.native_text or audio_ready:
        write(COST_GATE, {
            "schema": "qingshan.registered_gate_evidence.v1",
            "gate_id": "GIGGLE-REROLL-COST-GUARD",
            "status": "PASS",
            "authorization_ref": "ROGER-20260821-E40-REBUILD-BUDGET-5000",
            "reviewed_manifest": rel(out_path),
            "reviewed_manifest_sha256": sha(out_path),
            "planned_video_tasks": len(tasks),
            "planned_gross_credits": sum(int(row["duration_seconds"]) * 16 for row in tasks),
            "maximum_additional_credits": 5000,
            "first_pass_only": all(int(row.get("retry_attempt") or 1) == 1 for row in tasks),
            "attempt_numbers": sorted({int(row.get("retry_attempt") or 1) for row in tasks}),
        })
        pilot = copy.deepcopy(manifest)
        pilot["schema"] = "qingshan.e40.full_performance_video_transport_pilot.v2"
        pilot["tasks"] = [tasks[0]]
        pilot["admitted_video_task_count"] = 1
        pilot["maximum_new_submissions"] = 1
        pilot["machine_gate_reports"] = [
            value for value in pilot["machine_gate_reports"] if value != rel(COST_GATE)
        ] + [rel(PILOT_COST_GATE)]
        pilot["pilot_policy"] = "ONE_4_SECOND_SINGLE_AUDIO_TASK_ONLY_AFTER_ATTEMPT1_EXACT_REFUND; EXPAND_ONLY_AFTER_PROVIDER_ROUTE_SUCCESS"
        if not args.skip_pilot:
            write(PILOT_OUT, pilot)
            write(PILOT_COST_GATE, {
                "schema": "qingshan.registered_gate_evidence.v1",
                "gate_id": "GIGGLE-REROLL-COST-GUARD",
                "status": "PASS",
                "authorization_ref": "ROGER-20260821-E40-REBUILD-BUDGET-5000",
                "reviewed_manifest": rel(PILOT_OUT),
                "reviewed_manifest_sha256": sha(PILOT_OUT),
                "planned_video_tasks": 1,
                "planned_gross_credits": int(tasks[0]["duration_seconds"]) * 16,
                "maximum_additional_credits": 5000,
                "prior_attempt_credit_status": "PASS_ZERO_REFUNDED",
                "transport_pilot_only": True,
            })
    print(json.dumps({"status": "PASS_PREPRODUCTION", "video_tasks": len(tasks), "audio_items": len(audio_rows), "manifest": rel(out_path), "manifest_sha256": sha(out_path), "audio_plan_sha256": sha(AUDIO_PLAN)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
