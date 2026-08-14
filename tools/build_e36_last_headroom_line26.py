#!/usr/bin/env python3
"""Build the final affordable E36 Fast6 line26 continuation task."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
OUT = PROD / "autonomous_recovery_20260731/last_headroom_line26"
SOURCE = PROD / "autonomous_recovery_20260731/cap_close_changed_wave3/u14_line25/E36_U14_CANONICAL_L25_CHANGED_W3_BATCH.json"
IDENTITY = ROOT / "assets/reference/e36_20260729/characters/CHAR-chenji-age17-canonical-v1-20260729.png"
ANCHOR = ROOT / "working_assets/e36_autonomous_recovery_20260731/last_headroom_line26_anchors/E36_U14_L26_FROM_ACCEPTED_L25_TERMINAL_A1.png"
LATER = ROOT / "working_assets/e36_recovery_10000_20260730/u14_a2_repair/E36-CW-U14-A2-STILL-V4-CHANGED-INPUT-TERMINAL-REPAIR_0bf2a864-81c1-4379-9745-d1e10a257a0b.png"
SCRIPT_SHA = "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6"
MANIFEST_SHA = "e0809a1517bff7755832bdccd143487ac7eb2791aa42efb502f541cb792109d5"
MAILBOX_SHA = "5e3774eff59f161205194f9ae2f327b4ee8c76b9281a3432a2197e91d952934b"
IDENTITY_SHA = "e513b4e9b3a1caba1326e9511136550f94e2add111b3ad897f6f24642d07c4c0"
ANCHOR_SHA = "4eef3713088907b80188fd3b493476473a8f91eb8d88684927fdae5e284f7cc2"
LATER_SHA = "958f0320bc7e5315cebbda604b5a56ca0b09d8b62507b337c80d272df260e0dc"
TEXT = "他不是废子，是景朝拿来试各方反应的活棋子。"
PARENT_TASK_ID = "0d5746fa-d77d-4bad-be57-3efdfc610d5c"


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    batch = json.loads(SOURCE.read_text(encoding="utf-8"))
    task = batch["tasks"][0]
    stem = "E36_U14_CANONICAL_L26_LAST_HEADROOM"
    task_key = stem.replace("_", "-")
    prompt_path = OUT / f"{stem}_PROMPT.txt"
    dialogue_path = OUT / f"{stem}_DIALOGUE_MANIFEST.json"
    complete_path = OUT / f"{stem}_COMPLETE_VIDEO_PROMPT_MANIFEST.json"
    config_path = OUT / f"{stem}_BATCH.json"
    index_path = OUT / "E36_LAST_HEADROOM_LINE26_INDEX.json"
    media_rel = "working_assets/e36_autonomous_recovery_20260731/last_headroom_line26"
    qa_rel = "qa/e36_agentcut_20260730/last_headroom_line26_runtime"
    (ROOT / media_rel).mkdir(parents=True, exist_ok=True)
    (ROOT / qa_rel).mkdir(parents=True, exist_ok=True)

    prompt = (
        "VISUAL_PROMPT_NO_DIALOGUE_TEXT:\n"
        "【E36 final-headroom accepted-terminal continuation】9:16，720p，Seedance Fast 6秒，写实古装电影质感。"
        "@图片1只锁定十七岁陈迹身份；@图片2是已验收 line25 的5.70秒终态并作为本镜头第一帧权威；"
        "@图片3只锁同场后续光线、药柜与桌面轴线。严格连续承接@图片2，禁止复制人物、禁止回到更早动作。\n"
        "【天气硬合同】weather=INTERIOR_CLEAR_DAY。[[char_chenji]] [[scene_u14_canonical]] [[prop_contact_contract]]\n"
        "【光影与色彩】低饱和灰黑棕；窗光为动机光，烛光暖色辅光，肤色、灰麻衣和木桌纹理真实。\n"
        "【环境介质与力量反馈】烛焰、窗纸微光、药帘与衣袖持续微动，背景不得冻结。\n"
        "镜头1【中近景固定机位极慢微推】0.00-6.00秒：十七岁陈迹从@图片2的动作中直接开始，"
        "右食指正从空信封折痕上方后撤一指宽，左掌持续压住近侧桌沿；他把右手拇指和食指在信封上方捏成一枚棋子的形状，"
        "手势朝画面右前方移动但始终不触碰信封，然后抬眼清楚说出唯一结论。"
        f"{{对白：{TEXT}}}<音效>衣料摩擦、木桌轻响、烛焰轻爆与呼吸</音效>\n"
        "【主体与动作】陈迹独自以右手捏棋手势说明递信人的作用，正脸与嘴全程可见。\n"
        "【接触点】左掌持续接触近侧桌沿；右手始终悬在空信封一指以上，不接触纸面。\n"
        "【方向】右手由信封上方后撤并移向画面右前方，信封始终平铺、完整、静止。\n"
        "【环境生命层】烛焰、窗纸微光、药帘、衣袖和纸角持续轻动；皎兔与其他人物彻底不入镜。\n"
        f"【原生对白】唯一可见说话人陈迹在0.20-5.20秒只说一次：“{TEXT}”必须模型原生自然中文普通话、逐字完整，"
        "同步口型、气息、表情和起止时间，不得后配音、删字、换词、加字或倒序。\n"
        "【终态】棋子完整落下后闭口呼吸至少0.80秒，右手捏棋手势停在桌面右前方，左掌仍压桌沿，唯一空信封完整静止。\n"
        "【专项硬锁】只有一个十七岁陈迹；禁止成年替身、黑衣替身、画外第二人说话；"
        "景朝、各方反应、活棋子逐词清楚，活读huó，棋读qí，子读zǐ。\n"
        "禁止：字幕、画面文字、乱码、logo、水印、现代物、年龄漂移、身份交换、第二张嘴、静止首帧、重复帧、无因位移、动物。\n"
    )
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt, encoding="utf-8")

    dialogue = copy.deepcopy(task["dialogue"][0])
    dialogue.update({
        "dia_id": task_key,
        "video_unit_id": "U14",
        "speaker_id": "chenji",
        "speaker": "陈迹",
        "spoken_text": TEXT,
        "status": "PASS",
        "start_seconds": 0.2,
        "end_seconds": 5.2,
        "breath_after_seconds": 0.8,
        "expression": "十七岁陈迹冷静确认递信人是景朝测试各方反应的活棋",
        "audio_mode": "MODEL_NATIVE_TEXT_ONLY_HUMAN_LISTENING_EXCEPTION",
        "human_listening_exception": True,
        "external_voice_reference": False,
        "rights_cleared_model_native": False,
        "unverified_clone_prohibited": False,
        "path": "",
        "remote_asset_id": "",
        "language": "zh-CN",
        "native_video_audio": True,
        "lip_sync": True,
        "breath_expression_sync": True,
    })
    write_json(dialogue_path, {
        "schema": "qingshan.video_dialogue_manifest.v1",
        "episode": "E36",
        "status": "PASS",
        "source_script_sha256": SCRIPT_SHA,
        "rows": [{k: v for k, v in dialogue.items() if k not in {"language", "native_video_audio", "lip_sync", "breath_expression_sync"}}],
    })

    complete = json.loads((ROOT / batch["complete_video_prompt_manifest_ref"]).read_text(encoding="utf-8"))
    for row in complete.get("rows", []):
        if row.get("unit_id") == "U14":
            row["prompt_path"] = rel(prompt_path)
            row["prompt_sha256"] = sha(prompt_path)
    write_json(complete_path, complete)

    batch.update({
        "status": "ready",
        "source_cl2x": "CL2X-879",
        "source_cl2x_mailbox_sha256": MAILBOX_SHA,
        "source_mailbox_sha256": MAILBOX_SHA,
        "source_manifest_sha256": MANIFEST_SHA,
        "episode_paid_credits_before": 9880,
        "video_credit_limit": 96,
        "output_dir": media_rel,
        "qa_dir": qa_rel,
        "complete_video_prompt_manifest_ref": rel(complete_path),
        "dialogue_manifest_ref": rel(dialogue_path),
        "changed_input_parent_task_id": PARENT_TASK_ID,
        "changed_input_repair": True,
        "unchanged_retry": False,
        "max_retries": 0,
    })
    refs = [rel(IDENTITY), rel(ANCHOR), rel(LATER)]
    sequence = [
        {"asset_label": "@图片1", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "chenji", "path": rel(IDENTITY), "sha256": IDENTITY_SHA, "identity_reference": True},
        {"asset_label": "@图片2", "role": "ACCEPTED_LINE25_TERMINAL_AS_LINE26_FIRST_FRAME_AUTHORITY", "state_id": f"{task_key}-START", "path": rel(ANCHOR), "sha256": ANCHOR_SHA, "identity_reference": False},
        {"asset_label": "@图片3", "role": "ACCEPTED_LATER_STATE_SCENE_AND_LIGHT_BOUNDARY", "state_id": "U14-A2", "path": rel(LATER), "sha256": LATER_SHA, "identity_reference": False},
    ]
    task.update({
        "task_key": task_key,
        "source_id": task_key,
        "batch_id": task_key,
        "status": "ready",
        "model": "seedance-2.0-fast",
        "duration_seconds": 6,
        "duration": 6,
        "edit_target_duration_seconds": 6,
        "prompt_path": rel(prompt_path),
        "prompt_file": rel(prompt_path),
        "prompt_sha256": sha(prompt_path),
        "reference_images": refs,
        "reference_image_sequence": sequence,
        "planned_reference_image_count": 2,
        "state_reference_minimum": 2,
        "dialogue": [dialogue],
        "dialogue_audio_assets": [],
        "reference_audios": [],
        "reference_audio_asset_ids": [],
        "audio_reference_optional": True,
        "native_dialogue_required": True,
        "visible_speaker_required": True,
        "visual_entity_ids": ["chenji"],
        "model_native_text_only_dialogue_ids": [task_key],
        "changed_input_parent_task_id": PARENT_TASK_ID,
        "replaces_parent_task_id": PARENT_TASK_ID,
        "changed_input_repair": True,
        "unchanged_retry": False,
        "max_retries": 0,
        "source_segment_id": "u14_line26_last_headroom",
        "anchor_image_qa_ref": "qa/e36_agentcut_20260730/E36_LAST_HEADROOM_LINE26_TERMINAL_ANCHOR_IMAGE_QA_V1.json",
        "keyframe_interpolation_gate": {
            "status": "PASS",
            "stage": "CANDIDATE_PREFLIGHT",
            "anchor_count": 2,
            "adjacent_pairs_checked": 1,
            "checked_adjacent_pairs": 1,
            "candidate_recheck_required": True,
            "physical_interpolation_or_declared_cut": "PASS_ACCEPTED_LINE25_TERMINAL_TO_LINE26_CONTINUATION",
            "reason": "The accepted line25 terminal supplies exact pose, prop, axis and light continuity; accepted U14-A2 constrains later scene continuity.",
        },
        "multimodal_entity_bindings": [{
            "entity_id": "chenji",
            "character_name": "陈迹",
            "registry_id": "CHAR-陈迹-古装",
            "visual_reference": rel(IDENTITY),
            "visual_reference_sha256": IDENTITY_SHA,
            "identity_image_slot": "@图片1",
            "visible_speaker": True,
            "lip_sync": True,
            "prop_owners": {"唯一素白空信封": "始终完整平铺静止，右手不接触"},
            "ability_owners": [],
            "voice_policy": "MODEL_NATIVE_TEXT_ONLY_HUMAN_LISTENING_EXCEPTION_NO_EXTERNAL_REFERENCE",
        }],
        "performance_spec": {
            "schema": "qingshan.performance_generation_spec.v2",
            "episode": "E36",
            "unit_id": "U14",
            "prop_ownership": {"唯一素白空信封": "完整平铺静止；左掌接触桌沿；右手悬空不触纸面"},
            "motion_beats": [{
                "start_seconds": 0.0,
                "end_seconds": 6.0,
                "subject": "陈迹",
                "action": "十七岁陈迹右食指从信封折痕上方后撤，拇指与食指捏成棋子手势并说出结论",
                "contact_point": "左掌持续接触近侧桌沿；右手始终悬在信封一指以上",
                "direction": "右手由信封上方向画面右前方移动，信封不位移",
                "end_state": "棋子完整落下后闭口，捏棋手势停在桌面右前方，左掌仍压桌沿，信封完整静止",
                "intent": "冷静确认递信人的活棋作用",
                "visible_causality": "承接 line25 对各方反应的推演，得出递信人是活棋的结论",
                "expression": "十七岁陈迹冷静确认递信人是景朝测试各方反应的活棋",
                "viewer_read": "主体、动作、接触点、方向、终态及唯一对白均清楚",
            }],
        },
        "duration_plan": {
            "policy": "qingshan.shot_generation_duration.v5",
            "duration_seconds": 6,
            "rationale": "One canonical line26 continuation from an accepted terminal anchor; projected96 keeps total9976 within cap10000.",
            "edit_policy": "Preserve model-native Mandarin and lip sync; no post-dub, speed change, filler or duplicate frames.",
        },
    })
    task["multimodal_binding_sha256"] = hashlib.sha256(json.dumps(
        task["multimodal_entity_bindings"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    write_json(config_path, batch)
    write_json(index_path, {
        "schema": "qingshan.e36.last_headroom_line26.v1",
        "status": "READY_FOR_PREFLIGHT",
        "source_cl2x": "CL2X-879",
        "source_mailbox_sha256": MAILBOX_SHA,
        "source_script_sha256": SCRIPT_SHA,
        "source_manifest_sha256": MANIFEST_SHA,
        "episode_paid_credits_before": 9880,
        "projected_credits": 96,
        "projected_episode_total": 9976,
        "projected_headroom": 24,
        "task": {
            "unit": "U14",
            "line": 26,
            "config": rel(config_path),
            "config_sha256": sha(config_path),
            "prompt": rel(prompt_path),
            "prompt_sha256": sha(prompt_path),
            "anchor": rel(ANCHOR),
            "anchor_sha256": ANCHOR_SHA,
            "qa_dir": qa_rel,
            "media_dir": media_rel,
            "parent_task_id": PARENT_TASK_ID,
        },
    })
    print(json.dumps({"config": rel(config_path), "config_sha256": sha(config_path), "index": rel(index_path), "index_sha256": sha(index_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
