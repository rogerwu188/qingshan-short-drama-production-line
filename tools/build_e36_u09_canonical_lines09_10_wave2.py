#!/usr/bin/env python3
"""Build a canonical-locked U09 lines 9/10 recovery after the prior text mismatch."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/autonomous_recovery_20260731/u09_lines09_10"
OUT = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/autonomous_recovery_20260731/u09_canonical_lines09_10_wave2"
QA = "qa/e36_agentcut_20260730/u09_canonical_lines09_10_wave2_runtime"
MEDIA = "working_assets/e36_autonomous_recovery_20260731/u09_canonical_lines09_10_wave2"
SCRIPT_SHA = "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6"
MAILBOX_SHA = "3c5a003b4ba3f00fe335847a7891a78cacf850f3443cd228bb5c5776eb59c445"

PROMPT_REL = str((OUT / "E36_U09_CANONICAL_LINES09_10_WAVE2_PROMPT.txt").relative_to(ROOT))
CONFIG_REL = str((OUT / "E36_U09_CANONICAL_LINES09_10_WAVE2_BATCH.json").relative_to(ROOT))
COMPLETE_REL = str((OUT / "E36_U09_CANONICAL_LINES09_10_WAVE2_COMPLETE_VIDEO_PROMPT_MANIFEST.json").relative_to(ROOT))
DIALOGUE_REL = str((OUT / "E36_U09_CANONICAL_LINES09_10_WAVE2_DIALOGUE_MANIFEST.json").relative_to(ROOT))

LINE_9 = "有人隔月塞给小的一只信封，叫送到茶棚、桥头，搁下就走。"
LINE_10 = "从不许拆——小的连字都不识几个，拆了也白拆！"

PROMPT = f"""VISUAL_PROMPT_NO_DIALOGUE_TEXT:
【剧本硬锁】E36 canonical SHA={SCRIPT_SHA}；本镜只覆盖 canonical 编译对白第9、10行，禁止使用上一失败稿中的“跑腿”“腰牌”“三脚的鸟”等非本镜词句。古代景朝太平医馆，人物身份、古装服饰、晴天连续性不得改变。
【天气硬合同】weather=INTERIOR_CLEAR_HARSH_SUN。
【人物与场景绑定】[[scene_e36_u09]]；[[char_messenger]]；[[prop_blank_envelope]]。递信人是画面内唯一说话者；陈迹与皎兔只在画外审问且不发声。唯一素白空信封始终无字、无复制、无人拆开。
【色彩与光影】旧木深褐、灰青布衣、低饱和暖烛与冷白窗光；光源仅来自直棂窗硬日光与古式烛焰。
【环境生命层】烛焰持续微颤，药帘与悬挂草药受穿堂风轻摆，药汽缓慢上升，门外古街人声与木轮声很轻；背景不得冻结。
镜头1【中近景，肩高机位，缓慢向左横移，0.00-5.25秒】首帧已在动作中：递信人双膝接触青砖，右掌正从砖面抬向胸前，左手捏住自己衣摆但不碰信封；他朝画面左前方陈迹自然开口。主体=递信人；动作=边解释边用右手从胸前指向画外茶棚方向；接触点=双膝与青砖、左手与衣摆；方向=右手由下向左前方；终态=说完第一句短吸气，右手落回膝上，嘴闭合。{{对白：递信人仅说第9行}}。
镜头2【同轴胸上近景，5.25-11.00秒】主体=递信人；动作=他右手压住自己膝头，身体因害怕微向后缩，只说第二句；接触点=右掌与膝头、双膝与青砖；方向=重心由前向后半寸，目光仍朝左前方；终态=“白拆”完整落下后闭口，双手并放膝前，空信封仍完整留在旧木案上无人触碰。{{对白：递信人仅说第10行}}。
【力量作用于环境介质】递信人抬手与后缩只带动自己袖褶、衣摆和近身药汽；穿堂风推动药帘与悬挂草药，烛焰随气流微颤。力量不得隔空推动、吸附或复制空信封。
【原生对白硬合同】视频模型原生生成自然中文普通话，递信人0.35-5.05秒逐字只说一次：“{LINE_9}”；5.45-10.45秒逐字只说一次：“{LINE_10}”。每句起止、口型、气息、眉眼与表情同步；不增删、不改写、不重复、不旁白、不后配。其他人全程闭口且不得画外代说。
【负面约束】无现代物件、无字幕、水印、Logo、可读文字或伪文字；无身份漂移、成年化、同脸复制、肢体融合、静止起手、无因果瞬移、重复动作、循环填时、口型错配、非本镜旧台词。
"""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (ROOT / QA).mkdir(parents=True, exist_ok=True)
    (ROOT / MEDIA).mkdir(parents=True, exist_ok=True)
    prompt_path = ROOT / PROMPT_REL
    prompt_path.write_text(PROMPT, encoding="utf-8")
    prompt_sha = sha256(prompt_path)

    dialogue_rows = [
        {
            "dia_id": "E36-U09-CANONICAL-L09-W2",
            "video_unit_id": "U09",
            "speaker_id": "messenger",
            "speaker": "递信人",
            "spoken_text": LINE_9,
            "status": "PASS",
            "start_seconds": 0.35,
            "end_seconds": 5.05,
            "breath_after_seconds": 0.4,
            "expression": "紧张解释信封投递路径，末字闭口",
            "audio_mode": "MODEL_NATIVE_TEXT_ONLY_HUMAN_LISTENING_EXCEPTION",
            "human_listening_exception": True,
            "external_voice_reference": False,
            "path": "",
            "remote_asset_id": "",
        },
        {
            "dia_id": "E36-U09-CANONICAL-L10-W2",
            "video_unit_id": "U09",
            "speaker_id": "messenger",
            "speaker": "递信人",
            "spoken_text": LINE_10,
            "status": "PASS",
            "start_seconds": 5.45,
            "end_seconds": 10.45,
            "breath_after_seconds": 0.3,
            "expression": "畏缩辩解自己不识字，白拆落下后闭口",
            "audio_mode": "MODEL_NATIVE_TEXT_ONLY_HUMAN_LISTENING_EXCEPTION",
            "human_listening_exception": True,
            "external_voice_reference": False,
            "path": "",
            "remote_asset_id": "",
        },
    ]

    dialogue_manifest = json.loads((BASE / "E36_U09_LINES09_10_DIALOGUE_MANIFEST.json").read_text(encoding="utf-8"))
    dialogue_manifest["rows"] = dialogue_rows
    write_json(ROOT / DIALOGUE_REL, dialogue_manifest)

    complete = json.loads((BASE / "E36_U09_LINES09_10_COMPLETE_VIDEO_PROMPT_MANIFEST.json").read_text(encoding="utf-8"))
    for row in complete["rows"]:
        if row["unit_id"] == "U09":
            row["prompt_path"] = PROMPT_REL
            row["prompt_sha256"] = prompt_sha
    write_json(ROOT / COMPLETE_REL, complete)

    source = json.loads((BASE / "E36_U09_LINES09_10_BATCH.json").read_text(encoding="utf-8"))
    batch = copy.deepcopy(source)
    batch.update({
        "status": "ready",
        "video_credit_limit": 176,
        "episode_paid_credits_before": 8512,
        "output_dir": MEDIA,
        "qa_dir": QA,
        "complete_video_prompt_manifest_ref": COMPLETE_REL,
        "dialogue_manifest_ref": DIALOGUE_REL,
        "source_cl2x": "CL2X-871",
        "source_cl2x_mailbox_sha256": MAILBOX_SHA,
        "changed_input_parent_task_id": "24f74f4d-ca05-46f2-afa9-15306b5ccae2",
    })
    task = batch["tasks"][0]
    task.update({
        "task_key": "E36-U09-CANONICAL-L09-L10-WAVE2",
        "source_id": "E36-U09-CANONICAL-L09-L10-WAVE2",
        "batch_id": "E36-U09-CANONICAL-L09-L10-WAVE2",
        "duration_seconds": 11,
        "duration": 11,
        "edit_target_duration_seconds": 11,
        "status": "ready",
        "prompt_path": PROMPT_REL,
        "prompt_file": PROMPT_REL,
        "prompt_sha256": prompt_sha,
        "dialogue": [
            {**row, "dia_id": row["dia_id"], "language": "zh-CN", "native_video_audio": True, "lip_sync": True, "breath_expression_sync": True}
            for row in dialogue_rows
        ],
        "dialogue_audio_assets": [],
        "reference_audios": [],
        "reference_audio_asset_ids": [],
        "model_native_text_only_dialogue_ids": [row["dia_id"] for row in dialogue_rows],
        "audio_reference_optional": True,
        "source_segment_id": "u09_canonical_lines09_10_wave2",
        "replaces_parent_task_id": "24f74f4d-ca05-46f2-afa9-15306b5ccae2",
        "changed_input_repair": True,
        "unchanged_retry": False,
    })
    task["duration_plan"].update({
        "duration_seconds": 11,
        "rationale": "Canonical lines 9 and 10 require two complete native Mandarin breath groups with visible closed-mouth terminals.",
    })
    task["performance_spec"]["motion_beats"] = [
        {
            "start_seconds": 0.0,
            "end_seconds": 5.25,
            "subject": "递信人",
            "action": "递信人从青砖抬右手指向画外茶棚方向并说第一句",
            "contact_point": "双膝与青砖、左手与衣摆",
            "direction": "右手由下向左前方",
            "end_state": "第一句末闭口，右手落回膝上",
            "intent": "交代空信封投递路径",
            "visible_causality": "被问到投递方式后抬手示意地点",
            "expression": "紧张解释",
            "viewer_read": "投递路线与放下即走清楚可见",
        },
        {
            "start_seconds": 5.25,
            "end_seconds": 11.0,
            "subject": "递信人",
            "action": "递信人右手压膝，身体后缩并说第二句",
            "contact_point": "右掌与膝头、双膝与青砖",
            "direction": "重心向后半寸，目光朝左前方",
            "end_state": "白拆完整落下后闭口，双手并放膝前，空信封无人触碰",
            "intent": "辩解自己从未拆信且不识字",
            "visible_causality": "害怕被怀疑而后缩辩解",
            "expression": "畏缩发紧",
            "viewer_read": "不拆信的辩解和闭口终态清楚",
        },
    ]
    for binding in task.get("multimodal_entity_bindings", []):
        binding.pop("voice_reference", None)
        binding.pop("voice_reference_sha256", None)
        binding.pop("voice_reference_asset_id", None)
        binding.pop("audio_slot", None)
        binding.pop("dialogue_audio_slots", None)
    write_json(ROOT / CONFIG_REL, batch)
    print(json.dumps({
        "config": CONFIG_REL,
        "config_sha256": sha256(ROOT / CONFIG_REL),
        "prompt": PROMPT_REL,
        "prompt_sha256": prompt_sha,
        "complete_manifest": COMPLETE_REL,
        "dialogue_manifest": DIALOGUE_REL,
        "projected_credits": 176,
        "projected_episode_total": 8688,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
