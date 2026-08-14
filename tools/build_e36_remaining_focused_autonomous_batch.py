#!/usr/bin/env python3
"""Build the seven remaining E36 focused video jobs for concurrent dispatch."""

from __future__ import annotations

import copy
import hashlib
import json
import wave
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
OUT = BASE / "autonomous_recovery_20260731"
QA = ROOT / "qa/e36_agentcut_20260730"
SCRIPT_SHA = "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6"
MANIFEST_SHA = "e0809a1517bff7755832bdccd143487ac7eb2791aa42efb502f541cb792109d5"


def read(path: str | Path) -> dict:
    p = Path(path)
    return json.loads((p if p.is_absolute() else ROOT / p).read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path: str | Path) -> str:
    p = Path(path)
    return hashlib.sha256((p if p.is_absolute() else ROOT / p).read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def duration(path: str) -> float:
    with wave.open(str(ROOT / path), "rb") as wav:
        return round(wav.getnframes() / wav.getframerate(), 6)


BASES = {
    "u02": BASE / "recovery_10000_20260730/u02_r1a1_video/E36_U02_R1A1_CHANGED_INPUT_EPISODE_PARALLEL_BATCH_V1.json",
    "u09": BASE / "recovery_10000_20260730/u09_r1a_video/E36_U09_R1A_CHANGED_INPUT_EPISODE_PARALLEL_BATCH_V1.json",
    "u10_jiaotu": BASE / "E36_U10_EPISODE_PARALLEL_BATCH_V1.json",
    "u10_messenger": BASE / "recovery_10000_20260730/u10_line15_video/E36_U10_LINE15_FAST6S_EPISODE_PARALLEL_BATCH_V1.json",
    "u14": BASE / "recovery_10000_20260730/u14_r3_d02_video/E36_U14_R3_D02_EPISODE_PARALLEL_BATCH_V1.json",
}


SPECS = [
    {
        "slug": "u02_lines02_03", "base": "u02", "unit": "U02", "scene": "E36-CW-S01", "weather": "HEAT_NOON_DRY_DUST", "seconds": 8,
        "speakers": ["陈迹", "云羊"], "entities": ["chenji", "yunyang"],
        "lines": [
            ("E36-U02-FOCUS-L02", "陈迹", "chenji", "临刑才换囚，不是怕劫，是怕人看见他。", .35, 3.65, "working_assets/e36_dialogue_audio_refs_20260730/u02_r1/E36-U02-R1-D02.wav"),
            ("E36-U02-FOCUS-L03", "陈迹", "chenji", "劫的是人头，保的却是活口。", 4.0, 6.85, "working_assets/e36_dialogue_audio_refs_20260730/u02_r1/E36-U02-R1-D03.wav"),
        ],
        "visual": "十七岁陈迹借人群遮挡向刑台侧探，右手扶木柱、左脚压尘前移；十七岁云羊在他身后错半步警戒。刑台热浪翻动旗幡，尘土被脚步卷起，远处役卒与百姓持续移动。",
        "terminal": "陈迹说完后闭口，身体仍向刑台侧探；云羊闭口守住后侧，二人没有碰触刑具或囚犯。",
    },
    {
        "slug": "u09_lines09_10", "base": "u09", "unit": "U09", "scene": "E36-CW-S02", "weather": "INTERIOR_CLEAR_HARSH_SUN", "seconds": 10,
        "speakers": ["递信人"], "entities": ["messenger"],
        "lines": [
            ("E36-U09-FOCUS-L09", "递信人", "messenger", "小的就是个跑腿的，有人给钱，小的就送。", .35, 4.3, "working_assets/e36_dialogue_audio_refs_20260730/u09_r2/E36-U09-R2-D01.wav"),
            ("E36-U09-FOCUS-L10", "递信人", "messenger", "脸没见着，只认得腰牌上有一只三脚的鸟，小的不识几个字。", 4.65, 9.35, "working_assets/e36_dialogue_audio_refs_20260731/u09_line10_changed_take_r3/E36-U09-L10-D02-CHANGED-R3.wav"),
        ],
        "visual": "递信人跪在医馆地面，双膝接触青砖，手掌撑地后抬起一寸解释；门缝烈日切入，药帘、蒸汽与悬挂草药轻动，陈迹和皎兔只在画外审问。",
        "terminal": "递信人说完闭口，双手重新落到膝前，目光朝左前方陈迹，腰牌留在腰间未取下。",
    },
    {
        "slug": "u10_lines11_12_jiaotu", "base": "u10_jiaotu", "unit": "U10", "scene": "E36-CW-S02", "weather": "INTERIOR_CLEAR_HARSH_SUN", "seconds": 5,
        "speakers": ["皎兔"], "entities": ["jiaotu", "courier"], "rights": True,
        "lines": [
            ("E36-U10-FOCUS-L11", "皎兔", "jiaotu", "这一句，是真的。", .3, 1.5, None),
            ("E36-U10-FOCUS-L12", "皎兔", "jiaotu", "他自己都不知道自己是什么。", 1.8, 4.4, None),
        ],
        "visual": "皎兔正处于阖眼辨谎动作中，眉心血痕由暗转亮，右手两指悬在递信人耳侧一寸且不接触；药炉蒸汽横过侧光，药帘和草叶持续微动。",
        "terminal": "皎兔说完闭口并睁眼，悬指收回胸前；递信人仍跪地不动，双方始终没有皮肤接触。",
    },
    {
        "slug": "u10_lines13_14", "base": "u10_messenger", "unit": "U10", "scene": "E36-CW-S02", "weather": "INTERIOR_CLEAR_HARSH_SUN", "seconds": 10,
        "speakers": ["递信人"], "entities": ["messenger"],
        "lines": [
            ("E36-U10-FOCUS-L13", "递信人", "messenger", "小的自己也纳闷！那信封里头一个字都没有，空的！", .4, 4.6, "working_assets/e36_dialogue_audio_refs_20260730/u10_line13_prosody_r2/E36-U10-L13-D01-PROSODY-R2.wav"),
            ("E36-U10-FOCUS-L14", "递信人", "messenger", "可小的每送一回，密谍司就跟疯了似的往那儿扑。", 4.9, 9.4, "working_assets/e36_dialogue_audio_refs_20260730/u10_line14_prosody_r2/E36-U10-L14-D01-PROSODY-R2.wav"),
        ],
        "visual": "递信人跪地时先抓紧自己的衣摆，手指接触粗布并向胸前收紧，肩膀正处于发颤中段；门口药帘被风掀起，药炉蒸汽和悬草持续摆动。",
        "terminal": "递信人说完闭口，抓衣的右手松到半握，左掌停在膝上，目光转向右后方门口表示密谍司扑去的方向。",
    },
    {
        "slug": "u14_line23", "base": "u14", "unit": "U14", "scene": "E36-CW-S03", "weather": "INTERIOR_CLEAR_DAY", "seconds": 6,
        "speakers": ["陈迹"], "entities": ["chenji", "jiaotu"],
        "lines": [("E36-U14-FOCUS-L23", "陈迹", "chenji", "真正的信，是\"他这个人\"送到了哪儿、密谍司为他动了多少兵。", .3, 5.5, "working_assets/e36_dialogue_audio_refs_20260731/u14_r4_line23_prosody_r2/E36-U14-R4-D01-PROSODY-R2.wav")],
        "visual": "十七岁陈迹右食指正沿空信封折痕滑向交点，指腹接触纸面并向桌深推进；皎兔随指尖下移视线。药炉蒸汽、窗纸光斑与门帘持续轻动。",
        "terminal": "陈迹末字后闭口，指尖离开信封停在桌边并指向门外；信封完整留在桌面，皎兔看向门外。",
    },
    {
        "slug": "u14_lines24_26", "base": "u14", "unit": "U14", "scene": "E36-CW-S03", "weather": "INTERIOR_CLEAR_DAY", "seconds": 11,
        "speakers": ["陈迹"], "entities": ["chenji", "jiaotu"],
        "lines": [
            ("E36-U14-FOCUS-L24", "陈迹", "chenji", "景朝每叫他递一回空信封，就是丢颗石子进水。", .4, 4.2, "working_assets/e36_dialogue_audio_refs_20260730/u14_r5/E36-U14-R5-D01.wav"),
            ("E36-U14-FOCUS-L25", "陈迹", "chenji", "看各方溅起多大的浪。", 4.55, 6.35, "working_assets/e36_dialogue_audio_refs_20260730/u14_r5_d02_pronunciation_r2/E36-U14-R5-D02-PROSODY-R2.wav"),
            ("E36-U14-FOCUS-L26", "陈迹", "chenji", "他不是废子，是景朝拿来试各方反应的活棋子。", 6.7, 10.5, "working_assets/e36_dialogue_audio_refs_20260730/u14_r6_pronunciation_r2/E36-U14-R6-D01-PROSODY-R2.wav"),
        ],
        "visual": "十七岁陈迹用右指从空信封向外划出三道短路线，指腹先接触折痕再离纸，方向由桌面中心向门口散开；皎兔的视线逐条跟随。蒸汽掠过光束，门帘和草药轻动。",
        "terminal": "陈迹说完闭口，三道路线只由手势表示而不出现文字，右手停在胸前半握；空信封仍完整留桌。",
    },
    {
        "slug": "u14_lines27_28", "base": "u14", "unit": "U14", "scene": "E36-CW-S03", "weather": "INTERIOR_CLEAR_DAY", "seconds": 9,
        "speakers": ["皎兔", "陈迹"], "entities": ["jiaotu", "chenji"], "rights": True,
        "lines": [
            ("E36-U14-FOCUS-L27", "皎兔", "jiaotu", "拿一条活人命，当量兵的尺。", .4, 2.6, None),
            ("E36-U14-FOCUS-L28", "陈迹", "chenji", "这尺上还叠着两家的记。批次，是景朝的；折法，是王府账房的。", 2.95, 7.75, "working_assets/e36_dialogue_audio_refs_20260730/u14_r8_pronunciation_r2/E36-U14-R8-D01-PROSODY-R2.wav"),
        ],
        "visual": "皎兔右手正把空信封一角向陈迹推半寸，指腹接触纸角并向左前移动；陈迹左手悬在信封上方接住推理而不碰纸。药炉蒸汽、窗纸光斑和门帘持续变化。",
        "terminal": "皎兔说完闭口并收手；陈迹说完闭口，左手停在信封上方一寸，信封仍由桌面承托且没有被拿起。",
    },
]


def build_prompt(spec: dict) -> str:
    dialogue = "；".join(f"{speaker}{start:.2f}-{end:.2f}秒：‘{text}’" for _, speaker, _, text, start, end, _ in spec["lines"])
    rights = ""
    if spec.get("rights"):
        rights = "皎兔采用视频模型内置、权利清晰的年轻女性自然中文普通话音色；不读取、不引用、不模仿任何外部声纹或clone。"
    return f"""VISUAL_PROMPT_NO_DIALOGUE_TEXT:
【剧本硬锁】E36 canonical SHA={SCRIPT_SHA}；古代景朝医馆空间；人物年龄、身份、服饰、晴天连续性不得改变。
【天气硬合同】weather={spec['weather']}
【人物与场景绑定】[[scene_e36_{spec['unit'].lower()}]]；[[{' ]] [['.join('char_'+x for x in spec['entities'])}]]；[[prop_blank_envelope]]。
【色彩与光影】灰白药铺、木色桌案、冷青阴影和窗缝硬光，动机光来自窗与门；不使用现代灯具。
【环境生命层】环境介质持续可见：{spec['visual'].split('。')[-2] if '。' in spec['visual'] else '药帘、蒸汽与尘埃持续移动'}
镜头1【中近景，肩高机位，缓慢横移跟拍】首帧已在动作中：{spec['visual']} 主体动作、接触点与方向均清楚；再完成：说话者按时自然开口、旁人闭口反应、道具物权不变；动作结果：{spec['terminal']} {{对白：仅由AUDIO段生成}} <衣料摩擦、呼吸、药帘轻响、室内脚步与远处街声>
【负面约束】无现代物件、无现代文字、无水印、无字幕、无乱码、无新增人物、无身份漂移、无年龄漂移、无静止起手、无无因果瞬移、无重复动作、无口型错配、无画外代说。

AUDIO_PROMPT_DIALOGUE_ONLY:
视频模型原生生成自然中文普通话；每位可见说话者口型、气息、表情、发声起止严格同步；未说话者闭口。{rights}
精确对白与时序：{dialogue}
现场声保持低于对白；对白只说一遍，不增删、不改写、不旁白、不后配。
"""


def audio_rows(spec: dict) -> tuple[list[dict], list[dict], list[str]]:
    dialogue, assets, refs = [], [], []
    for index, (dia, speaker, speaker_id, text, start, end, path) in enumerate(spec["lines"], 1):
        dialogue.append({
            "dia_id": dia, "speaker": speaker, "spoken_text": text,
            "start_seconds": start, "end_seconds": end, "breath_after_seconds": 0.15,
            "expression": "自然口语随推理递进，末字闭口", "language": "zh-CN",
            "native_video_audio": True, "lip_sync": True, "breath_expression_sync": True,
        })
        if path and not spec.get("model_native_text_only"):
            voice_id = {"chenji": "cypqud0bu7t", "messenger": "3llwjcbwf3w", "yunyang": "v0udrgrojud"}[speaker_id]
            refs.append(path)
            assets.append({
                "dia_id": dia, "speaker_id": speaker_id, "character_name": speaker,
                "spoken_text": text, "audio_slot": f"@音频{index}", "path": path,
                "sha256": sha(path), "duration_seconds": duration(path),
                "voice_reference_asset_id": voice_id, "voice_derivation_status": "PASS",
                "source_voice": f"CANONICAL_LOCKED_REFERENCE:{voice_id}", "voice_gender": "male",
                "audio_mode": "EXACT_DIALOGUE_AUDIO_REFERENCE", "mode": "exact_dialogue_audio_reference",
                "purpose": "EXACT_TARGET_DIALOGUE_REFERENCE",
            })
    return dialogue, assets, refs


def build_one(spec: dict) -> dict:
    cfg = copy.deepcopy(read(BASES[spec["base"]]))
    task = cfg["tasks"][0]
    job_dir = OUT / spec["slug"]
    qa_dir = QA / f"{spec['slug']}_runtime"
    prompt_path = job_dir / f"E36_{spec['slug'].upper()}_PROMPT.txt"
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(build_prompt(spec), encoding="utf-8")

    cfg.update({
        "status": "READY_FOR_SUPERVISOR_PRECHECK", "source_cl2x": "CL2X-870",
        "source_cl2x_mailbox_sha256": "f98cc5c2b522253568c63a5b24009ab8a78bf370fe8eac16efdffa03a55406ca",
        "video_credit_limit": 10000, "episode_paid_credits_before": 8064,
        "output_dir": f"working_assets/e36_autonomous_recovery_20260731/{spec['slug']}",
        "qa_dir": rel(qa_dir), "concurrency": 1, "max_retries": 0,
        "targeted_unit_replacement": True, "unchanged_retry": False,
        "streaming_submission_policy": "SUBMIT_EACH_READY_UNIT_IMMEDIATELY",
    })
    for key in ("anchor_count_plan_ref", "common_sense_causality_plan_ref", "period_lock_plan_ref"):
        if not cfg.get(key):
            raise RuntimeError(f"{spec['slug']} missing {key}")

    prompt_sha = sha(prompt_path)
    complete = read(BASE / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V25.json")
    for row in complete["rows"]:
        if row["unit_id"] == spec["unit"]:
            row.update({"scene_id": spec["scene"], "weather": spec["weather"], "prompt_path": rel(prompt_path), "prompt_sha256": prompt_sha})
    complete_path = job_dir / f"E36_{spec['slug'].upper()}_COMPLETE_VIDEO_PROMPT_MANIFEST.json"
    write(complete_path, complete)

    manifest_rows = []
    for dia, speaker, speaker_id, text, start, end, path in spec["lines"]:
        row = {
            "dia_id": dia, "video_unit_id": spec["unit"], "speaker_id": speaker_id,
            "speaker": speaker, "spoken_text": text, "status": "PASS",
            "start_seconds": start, "end_seconds": end, "breath_after_seconds": .15,
            "expression": "自然普通话、可见口型、气息与表情同步",
        }
        if path and not spec.get("model_native_text_only"):
            row.update({"audio_mode": "EXACT_DIALOGUE_AUDIO_REFERENCE", "path": path, "sha256": sha(path), "duration_seconds": duration(path)})
        else:
            if speaker_id == "jiaotu":
                row.update({
                    "audio_mode": "RIGHTS_CLEARED_MODEL_NATIVE_TEXT_ONLY",
                    "rights_cleared_model_native": True, "external_voice_reference": False,
                    "unverified_clone_prohibited": True, "path": "", "remote_asset_id": "",
                })
            else:
                row.update({
                    "audio_mode": "MODEL_NATIVE_TEXT_ONLY_HUMAN_LISTENING_EXCEPTION",
                    "human_listening_exception": True, "external_voice_reference": False,
                    "path": "", "remote_asset_id": "",
                })
        manifest_rows.append(row)
    dialogue_manifest_path = job_dir / f"E36_{spec['slug'].upper()}_DIALOGUE_MANIFEST.json"
    write(dialogue_manifest_path, {"schema": "qingshan.video_dialogue_manifest.v1", "episode": "E36", "status": "PASS", "source_script_sha256": SCRIPT_SHA, "rows": manifest_rows})
    cfg["complete_video_prompt_manifest_ref"] = rel(complete_path)
    cfg["dialogue_manifest_ref"] = rel(dialogue_manifest_path)

    dialogue, assets, refs = audio_rows(spec)
    task.update({
        "task_key": f"E36-{spec['slug'].upper()}-AUTONOMOUS", "source_id": f"E36-{spec['slug'].upper()}-AUTONOMOUS",
        "batch_id": f"E36-{spec['slug'].upper()}-AUTONOMOUS", "unit_id": spec["unit"], "scene_id": spec["scene"],
        "source_segment_id": spec["slug"], "duration_seconds": spec["seconds"], "duration": spec["seconds"],
        "edit_target_duration_seconds": spec["seconds"], "model": "seedance-2.0-fast", "status": "READY_TO_SUBMIT",
        "dependencies_ready": True, "prompt_path": rel(prompt_path), "prompt_file": rel(prompt_path), "prompt_sha256": prompt_sha,
        "dialogue": dialogue, "dialogue_audio_assets": assets, "reference_audios": refs,
        "audio_reference_optional": True,
        "model_native_text_only_dialogue_ids": [row[0] for row in spec["lines"]] if spec.get("model_native_text_only") else [row[0] for row in spec["lines"] if row[6] is None],
        "reference_audio_asset_ids": [], "native_dialogue_required": True, "visible_speaker_required": True,
        "temporal_visual_qa_required": True, "visual_entity_ids": spec["entities"], "source_script_sha256": SCRIPT_SHA,
        "reference_image_asset_ids": [], "max_retries": 0, "unchanged_retry": False,
        "inherits_establishing_coverage": True,
    })
    task["duration_plan"] = {
        "policy": "qingshan.shot_generation_duration.v5", "duration_seconds": spec["seconds"],
        "rationale": "Focused canonical dialogue windows fit with visible breathing and a closed-mouth terminal state.",
        "edit_policy": "Preserve native Mandarin and lip sync; no post-dub, time stretch, filler or duplicate frames.",
    }
    task["performance_spec"] = {
        "schema": "qingshan.performance_generation_spec.v2", "episode": "E36", "unit_id": spec["unit"],
        "prop_ownership": {"唯一素白空信封": "保持单一、无字、物权连续，不复制"},
        "motion_beats": [{
            "start_seconds": 0.0, "end_seconds": spec["seconds"],
            "subject": "、".join(spec["speakers"]) + "、场内道具",
            "action": spec["visual"], "contact_point": "手指、衣料、青砖、桌面或纸面接触点按提示保持清楚",
            "direction": "动作沿镜头内既定前后左右方向连续推进", "end_state": spec["terminal"],
            "intent": "完成聚焦台词对应的推理或供述", "visible_causality": "接触动作先发生，视线与开口随后响应，末字后进入明确终态",
            "expression": "随台词由紧张或专注转为确认", "viewer_read": "主体、动作、接触点、方向和终态均可直接读出",
        }],
    }
    for binding in task.get("multimodal_entity_bindings") or []:
        for key in ("voice_reference", "voice_reference_sha256", "voice_reference_asset_id", "audio_slot", "dialogue_audio_slots"):
            binding.pop(key, None)
        entity = binding.get("entity_id")
        matching = [row for row in assets if row["speaker_id"] == entity]
        if matching:
            binding.update({
                "visible_speaker": True, "lip_sync": True,
                "voice_reference": matching[0]["path"], "voice_reference_sha256": matching[0]["sha256"],
                "voice_reference_asset_id": matching[0]["voice_reference_asset_id"],
                "audio_slot": matching[0]["audio_slot"], "dialogue_audio_slots": [row["audio_slot"] for row in matching],
            })
        elif entity in {row[2] for row in spec["lines"]}:
            policy = "RIGHTS_CLEARED_MODEL_NATIVE_NO_EXTERNAL_REFERENCE" if entity == "jiaotu" else "MODEL_NATIVE_TEXT_ONLY_HUMAN_LISTENING_EXCEPTION_NO_EXTERNAL_REFERENCE"
            binding.update({"visible_speaker": True, "lip_sync": True, "voice_policy": policy})
    task["multimodal_binding_sha256"] = hashlib.sha256(json.dumps(task.get("multimodal_entity_bindings") or [], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    cfg_path = job_dir / f"E36_{spec['slug'].upper()}_BATCH.json"
    receipt_path = qa_dir / f"E36_{spec['slug'].upper()}_RECEIPT.json"
    precheck_path = qa_dir / f"E36_{spec['slug'].upper()}_PRECHECK.json"
    write(cfg_path, cfg)
    return {"slug": spec["slug"], "config": rel(cfg_path), "receipt": rel(receipt_path), "precheck": rel(precheck_path), "prompt_sha256": prompt_sha}


def main() -> int:
    script = ROOT / "workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md"
    manifest = ROOT / "workflow/claude_writer_agent/scripts/E36_manifest_v2.json"
    if sha(script) != SCRIPT_SHA or sha(manifest) != MANIFEST_SHA:
        raise SystemExit("canonical script or manifest SHA mismatch")
    if read(manifest).get("sha256") != SCRIPT_SHA:
        raise SystemExit("manifest declared script SHA mismatch")
    # The standing human-listening exception permits exact canonical text to be
    # generated natively without attaching brittle or overlong audio references.
    for spec in SPECS:
        spec["model_native_text_only"] = True
    rows = [build_one(spec) for spec in SPECS]
    index = OUT / "E36_REMAINING_FOCUSED_AUTONOMOUS_BATCH_INDEX.json"
    write(index, {
        "schema": "qingshan.e36.remaining_focused_autonomous_batch.v1", "status": "READY_FOR_CONCURRENT_PRECHECK",
        "source_cl2x": "CL2X-870", "source_script_sha256": SCRIPT_SHA, "source_manifest_sha256": MANIFEST_SHA,
        "episode_paid_credits_before": 8064, "projected_video_credits": 944, "projected_total": 9008,
        "rights_policy": "JiaoTu uses model-native text-only female Mandarin with no external voice reference or clone.",
        "jobs": rows,
    })
    print(json.dumps({"status": "READY", "index": rel(index), "jobs": rows}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
