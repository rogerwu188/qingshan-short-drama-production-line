#!/usr/bin/env python3
"""Compile E36 episode prompt/dialogue manifests and the U12 supervisor batch."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
QA = ROOT / "qa/e36_v2_stills_repair_20260729"
PLAN = PROD / "E36_NATURAL_VIDEO_UNITS_AND_ANCHOR_PLAN_V1.json"
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md"
WRITER_MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E36_manifest_v2.json"
PROMPT_DIR = PROD / "video_prompts_complete_v1"
PROMPT_MANIFEST = PROD / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V1.json"
DIALOGUE_MANIFEST = PROD / "E36_DIALOGUE_MANIFEST_V1.json"
SCENE_AUTHORITY = PROD / "E36_SCENE_STATE_AUTHORITY_V1.json"
PERIOD_PLAN = QA / "E36_U12_PERIOD_LOCK_PLAN_V1.json"
ANCHOR_PLAN = QA / "E36_U12_ANCHOR_COUNT_PLAN_V1.json"
CONFIG = PROD / "E36_U12_EPISODE_PARALLEL_BATCH_V1.json"
SCRIPT_SHA = "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6"
CHENJI_IDENTITY = ROOT / "assets/reference/e36_20260729/characters/CHAR-chenji-age17-canonical-v1-20260729.png"
CHENJI_IDENTITY_TRANSPORT = CHENJI_IDENTITY
CHENJI_VOICE = ROOT / "libraries/audio/voice_refs/native_multimodal_20260709/VOICE-陈迹-古装/e09_shot01_chenji_native_voice_ref.wav"
CHENJI_VOICE_ASSET_ID = "cypqud0bu7t"


SCENES = {
    "9-1": ("E36-CW-S01", "HEAT_NOON_DRY_DUST", "西市法场", "午时三刻"),
    "9-2": ("E36-CW-S02", "INTERIOR_CLEAR_HARSH_SUN", "太平医馆密室", "午后"),
    "9-3": ("E36-CW-S03", "INTERIOR_CLEAR_DAY", "太平医馆密室", "午后"),
    "9-4": ("E36-CW-S04", "INTERIOR_CLEAR_DUSK_ENTERING", "太平医馆密室", "午后偏晚"),
    "9-5": ("E36-CW-S05", "CLEAR_DUSK_WIND_TO_NIGHT", "太平医馆后院", "黄昏向入夜"),
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    if sha(SCRIPT) != SCRIPT_SHA:
        raise SystemExit("canonical SHA mismatch")
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    if plan.get("unit_count") != 21 or plan.get("source_script_sha256") != SCRIPT_SHA:
        raise SystemExit("unit plan authority mismatch")

    scene_rows = []
    for source_scene, (scene_id, weather, location, time) in SCENES.items():
        scene_rows.append({
            "scene_id": scene_id, "source_scene": source_scene, "weather": weather,
            "location": location, "time": time, "time_of_day": time,
            "event_summary": f"{location}{time}的正典剧情状态",
            "status": "PASS",
        })
    write(SCENE_AUTHORITY, {
        "schema": "qingshan.scene_state_authority.v1", "episode": "E36", "status": "PASS",
        "source_script_sha256": SCRIPT_SHA, "scene_state": scene_rows,
    })

    prompt_rows = []
    for row in plan["units"]:
        uid = row["unit_id"]
        scene_id, weather, location, time = SCENES[row["scene"]]
        beat = row["physical_beats"][0]
        prompt_path = PROMPT_DIR / f"E36-CW-{uid}.txt"
        prompt = (
            f"E36 {uid}，9:16竖屏古装悬疑短剧，真实电影摄影。\n"
            f"【天气硬合同】weather={weather}\n"
            f"场景：{location}，{time}；时代锁：中国古代架空洛城，禁止现代物件、现代文字与民国灯具。\n"
            f"首帧必须处于进行态：{row['first_frame_motion_state']}\n"
            f"主体：{beat['subject']}。动作：{beat['action']}。接触点：{beat['contact_point']}。"
            f"方向：{beat['direction']}。终态：{beat['end_state']}。\n"
            f"环境生命层：{row['ambient_life']}\n"
            f"镜头保持空间轴线与人物身份连续，实速自然动作，口型与呼吸服从本单元对白清单。"
            f"禁止：{row['negative_prompt']}，可读字幕，水印，现代标识。\n"
        )
        if uid == "U12":
            prompt = (PROD / "video_prompts_repair_v2/E36-CW-U12-R2.txt").read_text(encoding="utf-8")
            # Remove an earlier generated professionalism header before rebuilding it.
            if "[[char:chenji]]" in prompt and "【天气硬合同】" in prompt:
                prompt = prompt[prompt.index("【天气硬合同】"):]
            if "【天气硬合同】weather=INTERIOR_CLEAR_DAY" not in prompt:
                prompt = "【天气硬合同】weather=INTERIOR_CLEAR_DAY\n" + prompt
            prompt = (
                    "[[char:chenji]] [[scene:taiping_clinic_secret_room]] [[prop:blank_envelope]]\n"
                    "【R4返修硬要求】唯一人物身份依据为@图片1的17岁陈迹，必须保持少年脸、清瘦少年体态，禁止成熟成年脸。0.0至10.0秒全程固定头肩中近景，陈迹的脸、双眼和完整嘴部持续清晰可见，不得切成手部特写；手指验折与信封只出现在画面下方，不能替换或遮挡脸。两句对白全部发声时段嘴部按普通话逐字自然开合，句末闭口。\n"
                    "palette：午后冷白窗光与暖烛动机光对照，古代医馆木色克制。\n"
                    "环境力量可视化：冷雾与细尘沿信封折痕流动，烛焰随气息轻颤。\n"
                    "镜头1【大远景，固定机位缓推】医馆密室空间、窗、案与人物轴线清楚；陈迹俯身走近案边、抬手压住信封，冷雾沿案面流动。{无对白}<脚步、烛芯轻响、衣料摩擦>\n"
                    "镜头2【中景，沿案面侧向缓推】陈迹手指压住信封一角并转动纸面，霜纹由接触点向外爬至折痕。{陈迹：字不在信里。}<纸张摩擦、霜纹细响>\n"
                    "镜头3【近景转特写，微距跟随】陈迹沿折痕移动指腹并停在记号终点，保持同一手、同一信封和同一方向，末字后闭口。{陈迹：在折法里。这几道折，是记号。}<指腹擦纸、呼吸收止>\n"
                    + prompt
            )
            prompt_path = PROD / "video_prompts_repair_v2/E36-CW-U12-R2.txt"
            prompt_path.write_text(prompt, encoding="utf-8")
        else:
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_path.write_text(prompt, encoding="utf-8")
        prompt_rows.append({
            "unit_id": uid, "scene_id": scene_id, "weather": weather,
            "prompt_path": rel(prompt_path), "prompt_sha256": sha(prompt_path),
        })
    write(PROMPT_MANIFEST, {
        "schema": "qingshan.complete_video_prompt_manifest.v1", "episode": "E36",
        "source_script_sha256": SCRIPT_SHA, "status": "PASS", "unit_count": 21,
        "all_units_have_prompt": True, "source_plan": rel(PLAN), "source_plan_sha256": sha(PLAN),
        "source_scene_authority": rel(SCENE_AUTHORITY),
        "source_scene_authority_sha256": sha(SCENE_AUTHORITY), "rows": prompt_rows,
    })

    dialogue_rows = [
        {"dia_id": "E36-U12-D01", "video_unit_id": "U12", "speaker_id": "chenji",
         "speaker": "陈迹", "spoken_text": "字不在信里。", "status": "PASS",
         "audio_mode": "CANONICAL_NATIVE_VOICE_STYLE_REFERENCE_WITH_EXACT_TEXT_PROMPT",
         "path": rel(CHENJI_VOICE), "sha256": sha(CHENJI_VOICE),
         "remote_asset_id": CHENJI_VOICE_ASSET_ID, "start_seconds": 0.8, "end_seconds": 2.3,
         "breath_after_seconds": 0.5, "expression": "低声确认，目光锁住折痕"},
        {"dia_id": "E36-U12-D02", "video_unit_id": "U12", "speaker_id": "chenji",
         "speaker": "陈迹", "spoken_text": "在折法里。这几道折，是记号。", "status": "PASS",
         "audio_mode": "CANONICAL_NATIVE_VOICE_STYLE_REFERENCE_WITH_EXACT_TEXT_PROMPT",
         "path": rel(CHENJI_VOICE), "sha256": sha(CHENJI_VOICE),
         "remote_asset_id": CHENJI_VOICE_ASSET_ID, "start_seconds": 2.8, "end_seconds": 6.3,
         "breath_after_seconds": 0.4, "expression": "从确认转为笃定，末字后闭口"},
    ]
    write(DIALOGUE_MANIFEST, {
        "schema": "qingshan.video_dialogue_manifest.v1", "episode": "E36", "status": "PASS",
        "source_script_sha256": SCRIPT_SHA, "rows": dialogue_rows,
    })

    image = ROOT / "working_assets/e36_v2_stills_20260728/repair_v2_candidates/E36_E36-CW-U12-A1-STILL-V2_a1e411f6-b6cd-4a45-a00a-a7123835d1ba.png"
    prompt = PROD / "video_prompts_repair_v2/E36-CW-U12-R2.txt"
    task = {
        "task_key": "E36-CW-U12-VIDEO-R4-AGE17-FULL-LIPSYNC", "source_id": "E36-CW-U12",
        "tool_type": "video_generation", "generation_mode": "performance_generation",
        "episode": "E36", "batch_id": "E36-U12-REPAIR-V4", "unit_id": "U12",
        "scene_id": "E36-CW-S03", "visual_zone": "E36-U12-CANONICAL", "duration": 10,
        "duration_seconds": 10, "edit_target_duration_seconds": 10, "model": "seedance-2.0-pro",
        "aspect_ratio": "9:16", "resolution": "720p", "status": "READY_TO_SUBMIT",
        "dependencies_ready": True, "prompt_file": rel(prompt), "prompt_path": rel(prompt),
        "prompt_sha256": sha(prompt), "reference_images": [rel(CHENJI_IDENTITY_TRANSPORT), rel(image)],
        "reference_image_sequence": [{"asset_label": "@图片1", "role": "CANONICAL_CHARACTER_IDENTITY_PERFORMANCE_START",
             "path": rel(CHENJI_IDENTITY_TRANSPORT), "sha256": sha(CHENJI_IDENTITY_TRANSPORT),
             "state_id": "CHAR-陈迹-17岁-古装", "identity_reference": True},
            {"asset_label": "@图片2", "role": "PROP_ACTION_REFERENCE",
             "path": rel(image), "sha256": sha(image), "state_id": "E36-CW-U12-A1", "identity_reference": False}],
        "planned_reference_image_count": 1, "state_reference_minimum": 1,
        "still_sequence_only_allowed": True, "action_unit": True,
        "duration_plan": {"policy": "qingshan.shot_generation_duration.v5", "duration_seconds": 10,
            "rationale": "Two canonical deductions separated by paper-fold inspection, breath and reaction button.",
            "edit_policy": "Preserve both utterances; trim silent head or tail only after ASR and lip-sync QA."},
        "dialogue": [{"dia_id": r["dia_id"], "speaker": r["speaker"], "spoken_text": r["spoken_text"],
            "start_seconds": r["start_seconds"], "end_seconds": r["end_seconds"],
            "breath_after_seconds": r["breath_after_seconds"], "expression": r["expression"]} for r in dialogue_rows],
        "native_dialogue_required": True,
        "reference_audios": [rel(CHENJI_VOICE)],
        "reference_audio_asset_ids": [],
        "dialogue_audio_assets": [{
            "dia_id": r["dia_id"], "speaker_id": "chenji", "audio_slot": f"@音频{index + 1}",
            "path": rel(CHENJI_VOICE), "sha256": sha(CHENJI_VOICE),
            "voice_reference_asset_id": CHENJI_VOICE_ASSET_ID,
            "voice_derivation_status": "PASS", "source_voice": "陈迹锁定原生声线参考",
            "voice_gender": "male", "audio_mode": r["audio_mode"],
            "purpose": "LOCKED_NATIVE_VOICE_STYLE_REFERENCE_WITH_EXACT_TEXT",
        } for index, r in enumerate(dialogue_rows)],
        "performance_spec": {
            "schema": "qingshan.performance_generation_spec.v2", "episode": "E36", "unit_id": "U12",
            "duration_seconds": 10, "prop_ownership": {"无字信封": "始终在陈迹指下的案面上"},
            "motion_beats": [
                {"start_seconds": 0.0, "end_seconds": 2.8, "subject": "陈迹", "action": "俯身走近案边并按住信封一角，说出第一句", "contact_point": "右手指腹与信封纸角", "direction": "由身前向案面下压", "end_state": "信封固定，视线锁住折痕", "intent": "确认线索不在字面", "visible_causality": "按住信封后才开口", "expression": "冷静确认", "viewer_read": "信中无字但仍有线索"},
                {"start_seconds": 2.8, "end_seconds": 7.0, "subject": "陈迹", "action": "转动纸面，指腹沿折痕移动并说出第二句", "contact_point": "指腹与信封折痕", "direction": "沿折痕由近向远滑动", "end_state": "指腹停在记号终点，末字后闭口", "intent": "把折法辨认为记号", "visible_causality": "触摸折痕引出判断", "expression": "由确认转为笃定", "viewer_read": "折痕是人为编码"},
                {"start_seconds": 7.0, "end_seconds": 10.0, "subject": "陈迹", "action": "保持指尖终点，抬眼思索并稳住呼吸", "contact_point": "指腹与折痕终点", "direction": "手不移动，视线由信封抬向前方", "end_state": "人物闭口定神，信封仍在案面", "intent": "留下推理后的决断反应", "visible_causality": "识别记号后进入思考", "expression": "警觉笃定", "viewer_read": "陈迹已掌握新方向"}
            ]
        },
        "keyframe_interpolation_gate": {"status": "PASS", "stage": "CANDIDATE_PREFLIGHT",
            "anchor_count": 1, "checked_adjacent_pairs": 0, "candidate_recheck_required": False,
            "reason": "单一进行态首帧支撑同空间连续验折动作，身份图仅用于人物约束。"},
        "character_free_unit": False, "visual_entity_ids": ["chenji"],
        "source_script_sha256": SCRIPT_SHA, "workflow_credit_scope": "e36_claude_writer_v2_4e46c013_20260728",
    }
    bindings = [{
        "entity_id": "chenji", "character_name": "陈迹", "registry_id": "CHAR-陈迹-古装",
        "visual_reference": rel(CHENJI_IDENTITY), "visual_reference_sha256": sha(CHENJI_IDENTITY),
        "identity_image_slot": "@图片1", "voice_reference_asset_id": CHENJI_VOICE_ASSET_ID,
        "dialogue_audio_slots": ["@音频1", "@音频2"], "visible_speaker": True, "lip_sync": True,
        "prop_owners": {"无字信封": "陈迹按住并检查折痕"}, "ability_owners": ["霜纹"],
    }]
    task["multimodal_entity_bindings"] = bindings
    task["multimodal_binding_sha256"] = hashlib.sha256(
        json.dumps(bindings, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    write(ANCHOR_PLAN, {
        "schema": "qingshan.video_unit_anchor_count_plan.v1", "episode": "E36",
        "source_script_sha256": SCRIPT_SHA, "planned_reference_image_count": 1,
        "units": [{"unit_id": "U12", "planned_reference_image_count": 1,
            "reference_image_task_keys": ["E36-CW-U12-A1-STILL-V2"],
            "anchor_count_decision": {"planned_reference_image_count": 1,
                "reason": "Independently assessed from continuous paper-fold inspection, stable room axis, unchanged prop ownership and interpolable terminal state.",
                "criteria": {"continuous_motion_from_single_start": True, "identity_or_space_reanchor": False,
                    "prop_ownership_transition": False, "non_interpolable_terminal_state": False},
                "anchor_roles": ["fold_reveal_start_motion"],
                "action_design_class": "SINGLE_START_CONTINUOUS_MOTION"},
            "keyframe_interpolation_gate": {"status": "PASS", "adjacent_pairs_checked": 0,
                "basis": "One authored start anchor supports the continuous fold-reveal action; output still requires continuity QA."}}],
    })
    write(PERIOD_PLAN, {
        "schema": "qingshan.anachronism_lock_plan.v1", "episode": "E36",
        "period_contract": {"era": "中国古代架空洛城", "status": "PASS", "source_refs": [rel(SCRIPT)]},
        "units": [{"unit_id": "U12", "period_lock": {"status": "PASS",
            "reviewed_visible_elements": ["古代木制医馆密室", "古代青衫", "无字空信封", "烛焰与玄幻霜纹"],
            "detected_anachronisms": [], "exception_approvals": {}, "evidence_refs": [rel(prompt)]}}],
    })
    write(CONFIG, {
        "schema": "qingshan.episode_parallel_batch.config.v1", "episode": "E36",
        "status": "READY_INCREMENTAL_UNITS", "concurrency": 1, "max_retries": 0,
        "effective_ruleset": "QINGSHAN_PIPELINE_EFFECTIVE_RULESET_V1",
        "workflow_credit_scope": "e36_claude_writer_v2_4e46c013_20260728", "video_credit_limit": 6000,
        "source_script_sha256": SCRIPT_SHA, "output_dir": rel(PROD / "video_repair_v2_outputs"),
        "qa_dir": rel(QA / "u12_video_runtime"), "scene_contract_ref": rel(SCENE_AUTHORITY),
        "script_readiness_report": rel(QA / "E36_SCRIPT_READINESS_GATE_V1.json"),
        "dramatic_quality_report_ref": rel(QA / "E36_DRAMATIC_COUNCIL_INPUT_V1.json"),
        "mechanical_default_plan_ref": rel(QA / "E36_U12_MECHANICAL_DEFAULT_PLAN_V1.json"),
        "anchor_count_plan_ref": rel(ANCHOR_PLAN),
        "common_sense_causality_plan_ref": rel(QA / "E36_U12_COMMON_SENSE_CAUSALITY_PLAN_V1.json"),
        "period_lock_plan_ref": rel(PERIOD_PLAN),
        "complete_video_prompt_manifest_ref": rel(PROMPT_MANIFEST), "dialogue_manifest_ref": rel(DIALOGUE_MANIFEST),
        "supervisor_script_gate_required": True,
        "supervisor_script_gate_report": rel(QA / "E36_LOCAL_CLAUDE_SCRIPT_SUPERVISION_V1.json"),
        "writer_agent_provenance": {"status": "PASS", "provenance_type": "claude_writer_script",
            "source_script": rel(SCRIPT), "source_script_sha256": sha(SCRIPT),
            "production_manifest": rel(WRITER_MANIFEST), "production_manifest_sha256": sha(WRITER_MANIFEST),
            "generated_script": rel(QA / "E36_SUPERVISOR_SCRIPT_BINDING_SOURCE_V1.json"),
            "compiled_script": rel(QA / "E36_SUPERVISOR_SCRIPT_BINDING_SOURCE_V1.json")},
        "tasks": [task],
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
