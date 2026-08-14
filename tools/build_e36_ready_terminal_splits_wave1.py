#!/usr/bin/env python3
"""Build independent changed-input splits for the seven ready E36 terminal lines."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/autonomous_recovery_20260731"
OUT_ROOT = PROD / "ready_terminal_splits_wave1"
SCRIPT_SHA = "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6"
MAILBOX_SHA = "2f2a1470cf865b528df1df042d9c3eb8efcfc8dd0eaf217b6377231f3e700dc5"
EPISODE_BEFORE = 8880

SPECS = [
    {"unit": "U10", "line": 11, "speaker": "皎兔", "speaker_id": "jiaotu", "text": "这一句，是真的。", "parent": "c0af5853-4e95-46bf-b85c-dbdd5fd2a086", "source": "u10_lines11_12_jiaotu", "prefix": "E36_U10_LINES11_12_JIAOTU", "weather": "INTERIOR_CLEAR_HARSH_SUN", "action": "皎兔眉心血痕正由暗转亮，右手两指悬在画面右侧一寸处辨谎", "contact": "双膝与青砖、左掌与衣摆，悬指不接触任何人", "direction": "右手两指由眉心向右前方伸出后收回胸前", "end_state": "真的完整落下后闭口睁眼，右手收回胸前，始终无皮肤接触", "expression": "专注辨谎后确认", "rights": True},
    {"unit": "U10", "line": 12, "speaker": "皎兔", "speaker_id": "jiaotu", "text": "他自己都不知道自己是什么。", "parent": "c0af5853-4e95-46bf-b85c-dbdd5fd2a086", "source": "u10_lines11_12_jiaotu", "prefix": "E36_U10_LINES11_12_JIAOTU", "weather": "INTERIOR_CLEAR_HARSH_SUN", "action": "皎兔睁眼看向画面右侧的递信人，右手由胸前缓慢向下压止", "contact": "双膝与青砖、左掌与衣摆，右手只压空气", "direction": "视线由下向右抬起，右手由胸前向下落回膝前", "end_state": "什么完整落下后闭口，右手停在膝前，递信人画外不动", "expression": "冷静确认对方全不知情", "rights": True},
    {"unit": "U14", "line": 24, "speaker": "陈迹", "speaker_id": "chenji", "text": "景朝每叫他递一回空信封，就是丢颗石子进水。", "parent": "af37ccf3-43cd-432c-bb7b-e3736f161293", "source": "u14_lines24_26", "prefix": "E36_U14_LINES24_26", "weather": "INTERIOR_CLEAR_DAY", "action": "十七岁陈迹右指正从桌面空信封折痕向外划出一道入水路线", "contact": "右指腹与信封折痕、左掌与桌沿", "direction": "右指由桌面中心向画面右前方划出后离纸", "end_state": "水字落下后闭口，右指停在桌边，唯一空信封完整留桌", "expression": "沉着拆解景朝试探逻辑", "rights": False},
    {"unit": "U14", "line": 25, "speaker": "陈迹", "speaker_id": "chenji", "text": "看各方溅起多大的浪。", "parent": "af37ccf3-43cd-432c-bb7b-e3736f161293", "source": "u14_lines24_26", "prefix": "E36_U14_LINES24_26", "weather": "INTERIOR_CLEAR_DAY", "action": "十七岁陈迹右手正由桌面向外展开三指，示意波纹向各方扩散", "contact": "左掌与桌沿、双脚与青砖，右手不碰信封", "direction": "右手由桌面中心向画面左右两侧展开", "end_state": "浪字落下后闭口，三指半收停在胸前，空信封静止留桌", "expression": "目光锐利地指出各方反应", "rights": False},
    {"unit": "U14", "line": 26, "speaker": "陈迹", "speaker_id": "chenji", "text": "他不是废子，是景朝拿来试各方反应的活棋子。", "parent": "af37ccf3-43cd-432c-bb7b-e3736f161293", "source": "u14_lines24_26", "prefix": "E36_U14_LINES24_26", "weather": "INTERIOR_CLEAR_DAY", "action": "十七岁陈迹右手从空信封上方移向画面右侧，掌心半握如落下一枚棋子", "contact": "左掌与桌沿、右指尖与木桌空处，信封不被拿起", "direction": "右手由信封上方向右前方木桌空处落下", "end_state": "棋子完整落下后闭口，右指停在木桌空处，空信封完整静止", "expression": "确认递信人是景朝活棋", "rights": False},
    {"unit": "U14", "line": 27, "speaker": "皎兔", "speaker_id": "jiaotu", "text": "拿一条活人命，当量兵的尺。", "parent": "0cdff50e-4567-4ada-a77e-ea4a74b07491", "source": "u14_lines27_28", "prefix": "E36_U14_LINES27_28", "weather": "INTERIOR_CLEAR_DAY", "action": "皎兔右手正把空信封一角向画面左侧推半寸，眉心血痕微亮", "contact": "右指腹与信封右角、左掌与桌沿", "direction": "右手由右向左推半寸后收回胸前", "end_state": "尺字落下后闭口收手，唯一空信封仍由桌面承托且没有被拿起", "expression": "愤怒而克制地看清活人代价", "rights": True},
    {"unit": "U14", "line": 28, "speaker": "陈迹", "speaker_id": "chenji", "text": "这尺上还叠着两家的记。批次，是景朝的；折法，是王府账房的。", "parent": "0cdff50e-4567-4ada-a77e-ea4a74b07491", "source": "u14_lines27_28", "prefix": "E36_U14_LINES27_28", "weather": "INTERIOR_CLEAR_DAY", "action": "十七岁陈迹左手悬在空信封上方一寸，右指沿两道折痕依次点向交点", "contact": "右指腹依次接触两道折痕、左掌悬空不接触纸面", "direction": "右指由第一道折痕移向第二道折痕再停在交点", "end_state": "账房的完整落下后闭口，右指离纸停在桌边，信封完整无字留桌", "expression": "冷静区分景朝批次与王府折法", "rights": False},
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    jobs = []
    for spec in SPECS:
        source_dir = PROD / spec["source"]
        batch_src = json.loads((source_dir / f'{spec["prefix"]}_BATCH.json').read_text(encoding="utf-8"))
        complete_src = json.loads((source_dir / f'{spec["prefix"]}_COMPLETE_VIDEO_PROMPT_MANIFEST.json').read_text(encoding="utf-8"))
        slug = f'{spec["unit"].lower()}_line{spec["line"]:02d}'
        out = OUT_ROOT / slug
        out.mkdir(parents=True, exist_ok=True)
        qa_rel = f"qa/e36_agentcut_20260730/ready_terminal_splits_wave1_{slug}_runtime"
        media_rel = f"working_assets/e36_autonomous_recovery_20260731/ready_terminal_splits_wave1_{slug}"
        (ROOT / qa_rel).mkdir(parents=True, exist_ok=True)
        (ROOT / media_rel).mkdir(parents=True, exist_ok=True)
        stem = f'E36_{spec["unit"]}_CANONICAL_L{spec["line"]:02d}_SPLIT_W1'
        prompt_rel = str((out / f"{stem}_PROMPT.txt").relative_to(ROOT))
        config_rel = str((out / f"{stem}_BATCH.json").relative_to(ROOT))
        complete_rel = str((out / f"{stem}_COMPLETE_VIDEO_PROMPT_MANIFEST.json").relative_to(ROOT))
        dialogue_rel = str((out / f"{stem}_DIALOGUE_MANIFEST.json").relative_to(ROOT))
        rights_text = "仅使用视频模型自带、rights-cleared 的自然年轻女声，禁止外部音频、克隆或模仿真人声纹。" if spec["rights"] else "采用视频模型原生自然普通话，禁止外部后配。"
        prompt = f'''VISUAL_PROMPT_NO_DIALOGUE_TEXT:
【剧本硬锁】E36 canonical SHA={SCRIPT_SHA}；本镜只覆盖 canonical 编译对白第{spec["line"]}行，禁止增删、改写、重复或混入相邻台词。古代景朝太平医馆，人物身份、十七岁陈迹、古装服饰与空间连续性不变。
【绑定】[[scene_e36_{spec["unit"].lower()}]]；[[char_{spec["speaker_id"]}]]；[[prop_blank_envelope]]。{spec["speaker"]}是唯一可见且唯一发声人物；其余人物只在画外闭口观察。
【天气硬合同】weather={spec["weather"]}
【天气与光影】weather={spec["weather"]}；旧木深褐、灰青布衣，直棂窗日光与古式烛焰为唯一动机光。
【环境生命层】烛焰持续微颤，药帘和悬挂草药受穿堂风轻摆，药汽缓慢上升；背景不得冻结。
镜头1【单一连续中近景，肩高机位，极缓横移，0.00-6.00秒】首帧已在动作中：{spec["speaker"]}肩膀和手臂正在推进动作，嘴正要开。主体={spec["speaker"]}；动作={spec["action"]}；接触点={spec["contact"]}；方向={spec["direction"]}；终态={spec["end_state"]}。{{对白：{spec["speaker"]}仅说 canonical 第{spec["line"]}行}}。
【力量作用于环境介质】手臂只带动自己的袖褶、衣摆和近身药汽；穿堂风推动药帘、草药与烛焰。力量不得隔空推动、吸附、拆开或复制空信封。
【原生对白硬合同】视频模型原生生成自然中文普通话。{spec["speaker"]}0.35-5.45秒逐字只说一次：“{spec["text"]}”口型、气息、眉眼、表情与起止时间同步；末字后闭口。{rights_text}不得旁白、画外代说或现代播音腔。
【负面约束】无现代物件、字幕、水印、Logo、可读文字或伪文字；无身份漂移、成年化、同脸复制、肢体融合、静止起手、瞬移、循环填时、口型错配、非本镜相邻台词。
'''
        prompt_path = ROOT / prompt_rel
        prompt_path.write_text(prompt, encoding="utf-8")
        prompt_sha = sha(prompt_path)
        dia = {
            "dia_id": f'E36-{spec["unit"]}-CANONICAL-L{spec["line"]:02d}-SPLIT-W1',
            "video_unit_id": spec["unit"], "speaker_id": spec["speaker_id"], "speaker": spec["speaker"],
            "spoken_text": spec["text"], "status": "PASS", "start_seconds": 0.35, "end_seconds": 5.45,
            "breath_after_seconds": 0.25, "expression": spec["expression"],
            "audio_mode": "RIGHTS_CLEARED_MODEL_NATIVE_TEXT_ONLY" if spec["rights"] else "MODEL_NATIVE_TEXT_ONLY_HUMAN_LISTENING_EXCEPTION",
            "human_listening_exception": True, "external_voice_reference": False,
            "rights_cleared_model_native": spec["rights"], "unverified_clone_prohibited": spec["rights"],
            "path": "", "remote_asset_id": "",
        }
        dump(ROOT / dialogue_rel, {"schema": "qingshan.video_dialogue_manifest.v1", "episode": "E36", "status": "PASS", "source_script_sha256": SCRIPT_SHA, "rows": [dia]})
        complete = copy.deepcopy(complete_src)
        for row in complete["rows"]:
            if row["unit_id"] == spec["unit"]:
                row["prompt_path"] = prompt_rel
                row["prompt_sha256"] = prompt_sha
        dump(ROOT / complete_rel, complete)
        batch = copy.deepcopy(batch_src)
        batch.update({"status": "ready", "video_credit_limit": 96, "episode_paid_credits_before": EPISODE_BEFORE,
                      "output_dir": media_rel, "qa_dir": qa_rel, "complete_video_prompt_manifest_ref": complete_rel,
                      "dialogue_manifest_ref": dialogue_rel, "source_cl2x": "CL2X-872", "source_cl2x_mailbox_sha256": MAILBOX_SHA,
                      "changed_input_parent_task_id": spec["parent"], "changed_input_repair": True, "unchanged_retry": False})
        task = batch["tasks"][0]
        task.update({"task_key": stem.replace("_", "-"), "source_id": stem.replace("_", "-"), "batch_id": stem.replace("_", "-"),
                     "duration_seconds": 6, "duration": 6, "edit_target_duration_seconds": 6, "status": "ready",
                     "prompt_path": prompt_rel, "prompt_file": prompt_rel, "prompt_sha256": prompt_sha,
                     "dialogue": [{**dia, "language": "zh-CN", "native_video_audio": True, "lip_sync": True, "breath_expression_sync": True}],
                     "model_native_text_only_dialogue_ids": [dia["dia_id"]], "source_segment_id": slug,
                     "replaces_parent_task_id": spec["parent"], "changed_input_repair": True, "unchanged_retry": False,
                     "native_dialogue_required": True, "visible_speaker_required": True, "audio_reference_optional": True,
                     "reference_audios": [], "reference_audio_asset_ids": [], "dialogue_audio_assets": []})
        task["duration_plan"] = {"policy": "qingshan.shot_generation_duration.v5", "duration_seconds": 6,
                                 "rationale": f'Canonical line {spec["line"]} isolated after combined provider failure.',
                                 "edit_policy": "Preserve native Mandarin and lip sync; no post-dub, time stretch, filler or duplicate frames."}
        task["performance_spec"]["motion_beats"] = [{"start_seconds": 0.0, "end_seconds": 6.0, "subject": spec["speaker"],
            "action": spec["action"], "contact_point": spec["contact"], "direction": spec["direction"], "end_state": spec["end_state"],
            "intent": "以单一自然呼吸组完成 canonical 推理台词", "visible_causality": "前镜推理触发本镜发言",
            "expression": spec["expression"], "viewer_read": "主体、动作、接触点、方向、终态和唯一对白均清楚"}]
        dump(ROOT / config_rel, batch)
        jobs.append({"unit": spec["unit"], "line": spec["line"], "config": config_rel, "config_sha256": sha(ROOT / config_rel),
                     "prompt": prompt_rel, "prompt_sha256": prompt_sha, "qa_dir": qa_rel, "media_dir": media_rel, "projected_credits": 96})
    index = {"schema": "qingshan.e36.ready_terminal_splits_wave1.v1", "status": "READY_FOR_CONCURRENT_PRECHECK",
             "source_cl2x": "CL2X-872", "source_mailbox_sha256": MAILBOX_SHA, "source_script_sha256": SCRIPT_SHA,
             "episode_paid_credits_before": EPISODE_BEFORE, "projected_credits": 96 * len(jobs),
             "projected_episode_total": EPISODE_BEFORE + 96 * len(jobs), "jobs": jobs}
    index_path = OUT_ROOT / "E36_READY_TERMINAL_SPLITS_WAVE1_INDEX.json"
    dump(index_path, index)
    print(json.dumps({"index": str(index_path.relative_to(ROOT)), "index_sha256": sha(index_path), "jobs": jobs}, ensure_ascii=False))


if __name__ == "__main__":
    main()
