#!/usr/bin/env python3
"""Compile the 13 E28 Seedance units from the final 38-state reference map."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "workflow/claude_writer_agent/production/e28_cl2x517_20260721"
UNIT_PLAN = PRODUCTION / "E28_MULTI_REFERENCE_STILL_PLAN_V3.json"
FINAL_STILLS = PRODUCTION / "E28_MULTI_REFERENCE_STILL_PLAN_V6_FINAL.json"
MANIFEST = PRODUCTION / "E28_PRODUCTION_MANIFEST.json"
PROMPT_DIR = PRODUCTION / "video_prompts_multireference_v3"
CONFIG_OUT = PRODUCTION / "E28_13_VIDEO_UNIT_PROMPT_BATCH_V3.json"
MD_OUT = PRODUCTION / "E28_13_VIDEO_UNIT_PROMPTS_FULL_V3.md"
RECEIPT_OUT = ROOT / "workflow/tasks/E28_13_VIDEO_UNIT_PROMPT_BUILD_V3_RECEIPT_20260721.json"


SCENE_LOCKS = {
    "E28-CW-S01-SEALED-CHAMBER": "靖王府偏院密室，夜，室内；烛火摇红与冰霜幽蓝对峙，冬夜只从格窗和门缝进入，禁止月光改景。",
    "E28-CW-S02-CHAMBER-ASSAULT": "靖王府偏院密室，夜，室内；冷蓝主调，火星和血花为克制暖点，檐槽与梁柱空间必须连续。",
    "E28-CW-S03-AUTOPSY-SIDE-ROOM": "偏院停尸侧间，夜，室内；烛火暖底、冰霜冷点，证据台、布囊和尸身位置保持连续。",
    "E28-CW-S04-SCREEN-CORRIDOR-FIGHT": "偏院屏风回廊，夜，室内通向雪夜外檐；青蓝风雪、破窗暖光、木格与墙头形成明确纵深。",
    "E28-CW-S05-SNOW-ALLEY": "王府外雪巷，无月雪夜，室外；青蓝雪夜、火把暖橙、冰流幽蓝，层楼飞檐与深巷尺度清楚。",
}


VOICE_ASSETS = {
    "chenji": ROOT / "libraries/audio/voice_refs/e09_voice_locked_20260709/shot_01_VOICE-陈迹-古装.wav",
    "jiaotu": ROOT / "working_assets/e28_video_audio_refs_v3_20260721/jiaotu_voice_ref_2p1s.wav",
    "yunyang": ROOT / "working_assets/e20_voice_separation_20260717/reference_trimmed/yunyang_shot13_vocals_reference_trim.wav",
    "wuyun": ROOT / "working_assets/e28_video_audio_refs_v3_20260721/wuyun_voice_ref_2p1s.wav",
}


CHARACTER_SLOTS = {
    "chenji": "[[char_chenji]]",
    "jiaotu": "[[char_jiaotu]]",
    "yunyang": "[[char_yunyang]]",
    "wuyun": "[[char_wuyun]]",
    "protected_clerk": "[[char_protected_clerk]]",
    "instructor": "[[char_instructor]]",
}


DIALOGUES = {
    "E28-CW-U01-C2": [("chenji", "陈迹", "这一笔，落了就该死。今晚，我偏留他一条命。", "背对众人，声音压得极平")],
    "E28-CW-U02-C1": [
        ("protected_clerk", "活口", "我……替教习誊抄过训令。", "牙关打颤、气若游丝；无固定声线资产，只按中年男性惊惧短句生成"),
        ("chenji", "陈迹", "碰过那份训令的人，一个个都被写上了册。", "垂眸，不回头"),
    ],
    "E28-CW-U02-C2": [("jiaotu", "皎兔", "门窗封死，梁上有线。他要动这个人，先得碰断我的线。", "刀背轻叩掌心，低声")],
    "E28-CW-U03-C1": [("yunyang", "云羊", "线断在梁上——", "檐外压嗓急呼")],
    "E28-CW-U05-C2": [("jiaotu", "皎兔", "门窗一寸没坏。人，倒了。", "脸色骤沉，短促确认")],
    "E28-CW-U05-C3": [("chenji", "陈迹", "他不从门，不从窗。走的是檐上的槽。", "盯住霜痕，一字一顿")],
    "E28-CW-U06-C1": [("jiaotu", "皎兔", "这一刀……是照着我的路数下的。", "俯身盯伤口，切齿")],
    "E28-CW-U07-C1": [("chenji", "陈迹", "刀形一模一样。力，是反的。", "贴近证据台，逐字落音")],
    "E28-CW-U07-C2": [
        ("chenji", "陈迹", "霜裂朝内，才是真发力。模仿的人，学了刀形，没学到发力。", "指向霜裂，冷静断句"),
        ("yunyang", "云羊", "这假招的底子……是教习那一脉的旧法。", "凑近，极低声"),
        ("jiaotu", "皎兔", "我知道是谁教出来的。", "缓缓直身，眼神一凛"),
    ],
    "E28-CW-U10-C2": [
        ("chenji", "陈迹", "密谍司的教习……头上还压着一个人。", "拾起私记，声冷如铁"),
        ("yunyang", "云羊", "他翻墙了——踏檐无痕！", "已掠上檐脊，自高处落声"),
    ],
    "E28-CW-U12-C2": [("yunyang", "云羊", "这脚印……两个步子。", "火光照处，语气陡变")],
    "E28-CW-U13-C2": [("wuyun", "乌云", "丑时了。忍住。", "黑猫低哑，只此一句")],
    "E28-CW-U13-C4": [("chenji", "陈迹", "翻墙逃走的……未必只有一个人。", "压到最低，几近自语；末字后切黑")],
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def norm(value: str) -> str:
    match = re.fullmatch(r"(.+-U\d+)-C0*(\d+)", value)
    if not match:
        raise ValueError(value)
    return f"{match.group(1)}-C{int(match.group(2))}"


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


def audio_assets_for(unit: dict) -> list[dict]:
    speakers = []
    for internal in unit["internal_shots"]:
        for character_id, _name, _text, _performance in DIALOGUES.get(norm(internal["state_id"]), []):
            if character_id in VOICE_ASSETS and character_id not in speakers:
                speakers.append(character_id)
    rows = []
    for character_id in speakers:
        path = VOICE_ASSETS[character_id]
        if not path.is_file():
            raise FileNotFoundError(path)
        rows.append({"character_id": character_id, "path": relative(path), "sha256": sha256(path)})
    return rows


def render_prompt(unit: dict, slots: dict, shots: dict, audio_rows: list[dict]) -> tuple[str, list[dict]]:
    references = []
    cursor = 0
    scene_ids = []
    for index, internal in enumerate(unit["internal_shots"], 1):
        state = norm(internal["state_id"])
        slot = slots[state]
        if slot["source_shot_id"] != internal["source_shot_id"]:
            raise ValueError(f"source shot mismatch: {state}")
        references.append({
            "asset_label": f"@图片{index}",
            "state_id": state,
            "source_shot_id": slot["source_shot_id"],
            "path": slot["image_path"],
            "sha256": slot["image_sha256"],
            "start_seconds": cursor,
            "end_seconds": cursor + internal["duration_seconds"],
            "qa_decision": slot["qa_decision"],
            "decisive_moment": slot["decisive_moment"],
        })
        scene_ids.append(shots[slot["source_shot_id"]]["scene_id"])
        cursor += internal["duration_seconds"]
    if cursor != unit["duration_seconds"]:
        raise ValueError(f"duration mismatch: {unit['unit_id']}")

    unique_scenes = list(dict.fromkeys(scene_ids))
    scene_text = "；".join(SCENE_LOCKS[item] for item in unique_scenes)
    lines = [
        f"这是《青山》E28《纸上杀人》{unit['unit_id']} 的 Seedance 2.0 Pro 多参考图连续分镜视频，生成{unit['duration_seconds']}秒，9:16，720p。",
        f"场景硬锁[[scene_1]]：{scene_text}",
        "多参考图不是候选图集合，而是同一连续单元的时间轴状态锚。必须按下列时段依次消费，禁止只采用第一张、禁止把多图拼成画中画、拼贴或分屏：",
    ]
    for ref in references:
        lines.append(
            f"- {ref['start_seconds']:.1f}-{ref['end_seconds']:.1f}秒：{ref['asset_label']}锁定{ref['state_id']}的构图、人物身份、服装、地点、道具与决定性状态；SHA-256={ref['sha256']}。"
        )
    lines.extend([
        "人物身份锁：陈迹[[char_chenji]]、皎兔[[char_jiaotu]]、云羊[[char_yunyang]]、乌云[[char_wuyun]]、活口[[char_protected_clerk]]、教习[[char_instructor]]分别独立绑定；教习始终是面部完全隐于黑色兜帽与蒙面的成年男性黑衣刺客，绝不能露出或借用陈迹的脸、发髻与服装。所有人物只允许继承对应时段参考图中的同一张脸、年龄、性别、发型和服装，禁止角色槽互换。同一角色始终只有一个实体身体。半透明运动残像只能依附本体，不能生成第二个人。",
        "道具锁[[prop_1]]：门闩、沉柜、冰线、刀、暗器、布囊、私记、拓纸、火把、透明珠只在剧本指定时段出现，持有人和受力方向不得改变。",
        "镜头语言：每次切换参考图都必须由前一动作的结果自然触发，保持左右轴线、入口出口、视线和力量方向；不得用统一缓慢推镜代替分镜。",
        "palette与动机光：烛火暖色、冰霜幽蓝、雪夜青蓝、火把暖橙按场景硬锁切换；黑位保留木纹、衣褶和面部层次，高光受控，禁止把室内夜景改成月光空镜。",
        "大远景/远景定场只在本单元确有空间建立时出现；中景、近景和特写服从动作与证据，不得为恢弘感擅改地点、时段、天气或剧情。",
        "",
    ])

    audio_index = {row["character_id"]: index for index, row in enumerate(audio_rows, 1)}
    cursor = 0
    for shot_index, internal in enumerate(unit["internal_shots"], 1):
        state = norm(internal["state_id"])
        source = shots[internal["source_shot_id"]]
        slot = slots[state]
        start = cursor
        end = cursor + internal["duration_seconds"]
        cursor = end
        dialogues = DIALOGUES.get(state, [])
        if dialogues:
            dialogue_text = []
            for character_id, name, text, performance in dialogues:
                voice = f"，台词音色严格参考@音频{audio_index[character_id]}" if character_id in audio_index else "，本角色无固定音色资产，不得借用其他角色声线"
                dialogue_text.append(f"{name}{CHARACTER_SLOTS[character_id]}{voice}：‘{text}’（{performance}）")
            dialogue_block = "；".join(dialogue_text)
        else:
            dialogue_block = "无对白，禁止人物说话或生成旁白"
        lines.append(
            f"镜头{shot_index}【{start:.1f}-{end:.1f}秒；景别={source['scale']}；机位与运动={source['camera']}】："
            f"从@图片{shot_index}锁定的单一状态进入真实连续动作，主体先稳定站位，再完成：{slot['decisive_moment']}；"
            f"动作结果必须落到下一状态锚或本镜结尾，不停帧、不循环。"
            f"{{对白：{dialogue_block}}}<现场声：{source['sound']}；衣料、脚步、器物和环境介质只随真实接触发声>"
        )

    if audio_rows:
        lines.extend(["", "【对白与声音资产】"])
        for index, row in enumerate(audio_rows, 1):
            lines.append(
                f"- @音频{index}={row['character_id']}固定声线，文件SHA-256={row['sha256']}；只学习音色、年龄感、语气和口音，禁止照抄参考音频原文字。"
            )
    else:
        lines.extend(["", "【对白与声音资产】本单元无对白，不绑定台词音频；禁止自动生成对白、旁白或人声吟唱。"])
    lines.extend([
        "【现场声】现场声必须连续：起势先于接触，接触声与画面同帧，力量传导后才出现木屑、火星、冰屑、纸影、雪粉或衣摆反应；远近声场随景别变化。不要生成背景音乐。",
        "【动作物理】按 wind-up→contact→force_transfer→result 顺序完成；人物和道具轨迹可追踪，重心、惯性、碰撞、落点与碎片方向一致。不得瞬移、穿模、悬空停顿或用慢动作填满时长。",
        "【负面约束】禁止字幕、水印、Logo、可读或伪可读文字；禁止换脸、变年龄、变性别、同款分身、双胞胎效果、额外人物、融合肢体；禁止拼贴、分屏、故事板网格；禁止重复第一帧、静图微动、全程缓慢推进；禁止擅改昼夜、地点、天气、人物、道具、对白与剧情结果。",
    ])
    return "\n".join(lines) + "\n", references


def main() -> int:
    unit_plan = load(UNIT_PLAN)
    final = load(FINAL_STILLS)
    production = load(MANIFEST)
    if final.get("status") != "READY_FOR_VIDEO_REFERENCE_CONSUMPTION":
        raise RuntimeError("final still map is not ready")
    blocked_identity_slots = [
        item["internal_shot_id"]
        for item in final["slots"]
        if item.get("qa_decision") == "CONDITIONAL_MACHINE_ADMISSION"
    ]
    if blocked_identity_slots:
        raise RuntimeError(
            "conditional identity admissions cannot enter video prompts: "
            + ", ".join(blocked_identity_slots)
        )
    slots = {norm(item["internal_shot_id"]): item for item in final["slots"]}
    shots = {item["shot_id"]: item for item in production["shots"]}
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    tasks = []
    md = [
        "# 《青山》E28 13 个视频单元完整提示词",
        "",
        f"- 源剧本 SHA-256：`{production['source']['script_sha256']}`",
        f"- 最终参考图映射：`{FINAL_STILLS}`",
        f"- 视频单元：13；内部状态图：38；总时长：{unit_plan['runtime_seconds']} 秒",
        "- 状态：提示词已编译并待人工检查，尚未提交视频生成。",
        "",
    ]
    for unit in unit_plan["video_units"]:
        audio_rows = audio_assets_for(unit)
        prompt, refs = render_prompt(unit, slots, shots, audio_rows)
        prompt_path = PROMPT_DIR / f"{unit['unit_id']}.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        task = {
            "task_key": f"{unit['unit_id']}-VIDEO-V3",
            "tool_type": "video_generation",
            "generation_mode": "entity_reference_sequence",
            "episode": "E28",
            "unit_id": unit["unit_id"],
            "scene_id": shots[unit["internal_shots"][0]["source_shot_id"]]["scene_id"],
            "duration_seconds": unit["duration_seconds"],
            "model": "seedance-2.0-pro",
            "aspect_ratio": "9:16",
            "resolution": "720p",
            "prompt_file": relative(prompt_path),
            "prompt_sha256": sha256(prompt_path),
            "reference_images": [relative(Path(item["path"])) for item in refs],
            "reference_image_sequence": refs,
            "reference_audios": [row["path"] for row in audio_rows],
            "reference_audio_assets": audio_rows,
            "source_script_sha256": production["source"]["script_sha256"],
            "status": "READY_FOR_USER_PROMPT_REVIEW",
        }
        tasks.append(task)
        md.extend([
            f"## {unit['unit_id']} · {unit['duration_seconds']}秒 · {len(refs)}张参考图",
            "",
            "```text",
            prompt.rstrip(),
            "```",
            "",
        ])
    if len(tasks) != 13 or sum(len(task["reference_images"]) for task in tasks) != 38:
        raise RuntimeError("expected 13 units and 38 ordered reference images")
    config = {
        "schema": "qingshan.episode_parallel_batch.config.v1",
        "episode": "E28",
        "status": "READY_FOR_USER_PROMPT_REVIEW_NOT_SUBMITTED",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "concurrency": 13,
        "max_retries": 0,
        "retry_policy": "FAILED_ITEMS_ONLY_CHANGED_INPUT_REQUIRED",
        "source_script_sha256": production["source"]["script_sha256"],
        "final_still_plan": relative(FINAL_STILLS),
        "final_still_plan_sha256": sha256(FINAL_STILLS),
        "tasks": tasks,
    }
    CONFIG_OUT.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MD_OUT.write_text("\n".join(md), encoding="utf-8")
    receipt = {
        "schema": "qingshan.e28.video_prompt_build_receipt.v1",
        "episode": "E28",
        "status": "PASS_NOT_SUBMITTED",
        "unit_count": 13,
        "reference_state_count": 38,
        "runtime_seconds": unit_plan["runtime_seconds"],
        "config": str(CONFIG_OUT),
        "config_sha256": sha256(CONFIG_OUT),
        "markdown": str(MD_OUT),
        "markdown_sha256": sha256(MD_OUT),
        "remote_calls": 0,
        "credit_spent": 0,
    }
    RECEIPT_OUT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS_NOT_SUBMITTED", "units": 13, "states": 38, "markdown": str(MD_OUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
