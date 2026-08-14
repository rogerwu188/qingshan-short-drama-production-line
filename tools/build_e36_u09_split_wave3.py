#!/usr/bin/env python3
"""Split E36 U09 canonical lines 9/10 into independent six-second video tasks."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/autonomous_recovery_20260731/u09_canonical_lines09_10_wave2"
OUT_ROOT = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/autonomous_recovery_20260731/u09_split_wave3"
SCRIPT_SHA = "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6"
MAILBOX_SHA = "3c5a003b4ba3f00fe335847a7891a78cacf850f3443cd228bb5c5776eb59c445"
PARENT_TASK = "81648f55-be39-42d4-8834-07c165bdfa11"

SPECS = [
    {
        "slug": "line09",
        "line": 9,
        "text": "有人隔月塞给小的一只信封，叫送到茶棚、桥头，搁下就走。",
        "dia_id": "E36-U09-CANONICAL-L09-W3",
        "start": 0.35,
        "end": 5.35,
        "action": "递信人右手从胸前向画面左前方划出茶棚到桥头的投递路线",
        "contact": "双膝与青砖、左手与衣摆",
        "direction": "右手由胸前向左前方再落回膝上",
        "end_state": "走字落下后闭口，右手落回右膝，空信封仍在案上无人触碰",
        "intent": "交代隔月收到信封及投递路线",
        "expression": "紧张回忆投递过程",
    },
    {
        "slug": "line10",
        "line": 10,
        "text": "从不许拆——小的连字都不识几个，拆了也白拆！",
        "dia_id": "E36-U09-CANONICAL-L10-W3",
        "start": 0.35,
        "end": 5.25,
        "action": "递信人右掌压住自己膝头，左手摊开示意从未拆信",
        "contact": "右掌与右膝、双膝与青砖",
        "direction": "左手由胸前向外摊开后收回膝前",
        "end_state": "白拆完整落下后闭口，双手并放膝前，空信封完整无字",
        "intent": "辩解从未获准拆信且自己不识字",
        "expression": "畏缩急切地自证清白",
    },
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    source_config = json.loads((SOURCE_DIR / "E36_U09_CANONICAL_LINES09_10_WAVE2_BATCH.json").read_text(encoding="utf-8"))
    source_complete = json.loads((SOURCE_DIR / "E36_U09_CANONICAL_LINES09_10_WAVE2_COMPLETE_VIDEO_PROMPT_MANIFEST.json").read_text(encoding="utf-8"))
    outputs = []
    for spec in SPECS:
        out = OUT_ROOT / spec["slug"]
        out.mkdir(parents=True, exist_ok=True)
        qa_rel = f"qa/e36_agentcut_20260730/u09_split_wave3_{spec['slug']}_runtime"
        media_rel = f"working_assets/e36_autonomous_recovery_20260731/u09_split_wave3_{spec['slug']}"
        (ROOT / qa_rel).mkdir(parents=True, exist_ok=True)
        (ROOT / media_rel).mkdir(parents=True, exist_ok=True)
        stem = f"E36_U09_CANONICAL_L{spec['line']:02d}_WAVE3"
        prompt_rel = str((out / f"{stem}_PROMPT.txt").relative_to(ROOT))
        config_rel = str((out / f"{stem}_BATCH.json").relative_to(ROOT))
        complete_rel = str((out / f"{stem}_COMPLETE_VIDEO_PROMPT_MANIFEST.json").relative_to(ROOT))
        dialogue_rel = str((out / f"{stem}_DIALOGUE_MANIFEST.json").relative_to(ROOT))
        prompt = f"""VISUAL_PROMPT_NO_DIALOGUE_TEXT:
【剧本硬锁】E36 canonical SHA={SCRIPT_SHA}；本镜只覆盖 canonical 编译对白第{spec['line']}行，禁止增删、改写、重复或混入相邻台词。古代景朝太平医馆，人物身份、古装服饰与晴天连续性不变。
【绑定】[[scene_e36_u09]]；[[char_messenger]]；[[prop_blank_envelope]]。递信人是唯一可见且唯一发声人物；陈迹、皎兔只在画外闭口观察。
【天气硬合同】weather=INTERIOR_CLEAR_HARSH_SUN
【天气与光影】weather=INTERIOR_CLEAR_HARSH_SUN；旧木深褐、灰青布衣，冷白直棂窗硬光与古式烛焰为唯一动机光。
【环境生命层】烛焰持续微颤，药帘和悬挂草药受穿堂风轻摆，药汽缓慢上升，门外古街木轮声很轻；背景不得冻结。
镜头1【单一连续中近景，肩高机位，极缓向左横移，0.00-6.00秒】首帧已在动作中：递信人双膝压住青砖，右肩正在抬起，嘴正要开。主体=递信人；动作={spec['action']}；接触点={spec['contact']}；方向={spec['direction']}；终态={spec['end_state']}。{{对白：递信人仅说 canonical 第{spec['line']}行}}。
【力量作用于环境介质】手臂动作只带动自己的袖褶、衣摆和近身药汽；穿堂风推动药帘、草药与烛焰。力量不得隔空推动、吸附、拆开或复制空信封。
【原生对白硬合同】视频模型原生生成自然中文普通话。递信人{spec['start']:.2f}-{spec['end']:.2f}秒逐字只说一次：“{spec['text']}”口型、气息、眉眼、表情与起止时间同步；末字后闭口。不得旁白、后配、画外代说或现代播音腔。
【负面约束】无现代物件、字幕、水印、Logo、可读文字或伪文字；无身份漂移、成年化、同脸复制、肢体融合、静止起手、瞬移、循环填时、口型错配、非本镜相邻台词。
"""
        prompt_path = ROOT / prompt_rel
        prompt_path.write_text(prompt, encoding="utf-8")
        prompt_sha = sha256(prompt_path)

        row = {
            "dia_id": spec["dia_id"],
            "video_unit_id": "U09",
            "speaker_id": "messenger",
            "speaker": "递信人",
            "spoken_text": spec["text"],
            "status": "PASS",
            "start_seconds": spec["start"],
            "end_seconds": spec["end"],
            "breath_after_seconds": 0.3,
            "expression": spec["expression"],
            "audio_mode": "MODEL_NATIVE_TEXT_ONLY_HUMAN_LISTENING_EXCEPTION",
            "human_listening_exception": True,
            "external_voice_reference": False,
            "path": "",
            "remote_asset_id": "",
        }
        dialogue = {
            "schema": "qingshan.video_dialogue_manifest.v1",
            "episode": "E36",
            "status": "PASS",
            "source_script_sha256": SCRIPT_SHA,
            "rows": [row],
        }
        write_json(ROOT / dialogue_rel, dialogue)

        complete = copy.deepcopy(source_complete)
        for complete_row in complete["rows"]:
            if complete_row["unit_id"] == "U09":
                complete_row["prompt_path"] = prompt_rel
                complete_row["prompt_sha256"] = prompt_sha
        write_json(ROOT / complete_rel, complete)

        batch = copy.deepcopy(source_config)
        batch.update({
            "status": "ready",
            "video_credit_limit": 96,
            "episode_paid_credits_before": 8688,
            "output_dir": media_rel,
            "qa_dir": qa_rel,
            "complete_video_prompt_manifest_ref": complete_rel,
            "dialogue_manifest_ref": dialogue_rel,
            "source_cl2x": "CL2X-871",
            "source_cl2x_mailbox_sha256": MAILBOX_SHA,
            "changed_input_parent_task_id": PARENT_TASK,
        })
        task = batch["tasks"][0]
        task.update({
            "task_key": f"E36-U09-CANONICAL-L{spec['line']:02d}-WAVE3",
            "source_id": f"E36-U09-CANONICAL-L{spec['line']:02d}-WAVE3",
            "batch_id": f"E36-U09-CANONICAL-L{spec['line']:02d}-WAVE3",
            "duration_seconds": 6,
            "duration": 6,
            "edit_target_duration_seconds": 6,
            "status": "ready",
            "prompt_path": prompt_rel,
            "prompt_file": prompt_rel,
            "prompt_sha256": prompt_sha,
            "dialogue": [{**row, "language": "zh-CN", "native_video_audio": True, "lip_sync": True, "breath_expression_sync": True}],
            "model_native_text_only_dialogue_ids": [spec["dia_id"]],
            "source_segment_id": f"u09_canonical_line{spec['line']:02d}_wave3",
            "replaces_parent_task_id": PARENT_TASK,
            "changed_input_repair": True,
            "unchanged_retry": False,
        })
        task["duration_plan"].update({
            "duration_seconds": 6,
            "rationale": f"Canonical line {spec['line']} is isolated into one native Mandarin breath group to prevent omission.",
        })
        task["performance_spec"]["motion_beats"] = [{
            "start_seconds": 0.0,
            "end_seconds": 6.0,
            "subject": "递信人",
            "action": spec["action"],
            "contact_point": spec["contact"],
            "direction": spec["direction"],
            "end_state": spec["end_state"],
            "intent": spec["intent"],
            "visible_causality": "画外审问触发递信人现场解释",
            "expression": spec["expression"],
            "viewer_read": "主体、动作、接触点、方向、终态和唯一对白均清楚",
        }]
        write_json(ROOT / config_rel, batch)
        outputs.append({
            "line": spec["line"],
            "config": config_rel,
            "config_sha256": sha256(ROOT / config_rel),
            "prompt": prompt_rel,
            "prompt_sha256": prompt_sha,
            "qa_dir": qa_rel,
            "media_dir": media_rel,
            "projected_credits": 96,
        })
    index = {
        "schema": "qingshan.e36.u09_split_wave3.v1",
        "status": "READY_FOR_CONCURRENT_PRECHECK",
        "source_cl2x": "CL2X-871",
        "source_script_sha256": SCRIPT_SHA,
        "parent_failed_task_id": PARENT_TASK,
        "episode_paid_credits_before": 8688,
        "projected_credits": 192,
        "projected_episode_total": 8880,
        "jobs": outputs,
    }
    index_path = OUT_ROOT / "E36_U09_SPLIT_WAVE3_INDEX.json"
    write_json(index_path, index)
    print(json.dumps({"index": str(index_path.relative_to(ROOT)), "index_sha256": sha256(index_path), "jobs": outputs}, ensure_ascii=False))


if __name__ == "__main__":
    main()
