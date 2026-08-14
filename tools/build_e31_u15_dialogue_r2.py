#!/usr/bin/env python3
"""Build changed-input failed-only repair for E31 U15."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from episode_video_generation_guard import generation_fingerprint


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e31_claude_writer_v1_20260722/video_performance_v1"
SOURCE_CONFIG = BASE / "E31_VIDEO_BATCH_DIALOGUE_READY_V1.json"
PROMPT = BASE / "prompts/E31-CW-U15-PERFORMANCE-R2.txt"
CONFIG = BASE / "E31_VIDEO_BATCH_U15_FAILED_ONLY_R2.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    source = json.loads(SOURCE_CONFIG.read_text(encoding="utf-8"))
    task = next(row for row in source["tasks"] if row["unit_id"] == "E31-CW-U15")
    first, second = task["dialogue"]
    prompt = "\n".join([
        "《青山》E31《王府风暴》U15，Seedance 2.0 Pro 四模态表演生成，14秒，9:16，720p，原速连续对话。",
        "【实体绑定】陈迹[[char_chenji]]、灰衣门客[[char_grey_guest]]、侧阁孤灯[[scene_e31_s04]]、书案与空椅[[prop_e31_furniture]]。",
        "【生成范式】@图片1只锁两人身份、侧阁、书案和初始距离；@音频1只驱动灰衣门客，@音频2只驱动陈迹。每句只说一次，不在镜头间重复。",
        "【色彩与动机光】palette=孤灯暖琥珀、室内暗木、门外雪夜冷蓝；动机光来自案上孤灯。力量作用到环境介质：起身带动衣摆和灯焰轻摆一次，陈迹急停使门槛薄尘向前移动后落定。",
        f"【对白时轴】0.25-7.15秒：@音频1，灰衣门客逐字说“{first['spoken_text']}”，口型、气息和温和表情同步；7.31-13.05秒：@音频2，陈迹逐字说“{second['spoken_text']}”，口型、气息和冷硬表情同步。其他人物在对应音频槽闭口。",
        f"镜头1【0.0-7.2秒，远景定场转双人中景缓慢侧移】灰衣门客从案后起身，双手拢袖作揖，再以右掌示意空椅；他保持一案距离按@音频1完整说话。陈迹站在门内不坐、不前进，只冷眼看他。{{灰衣门客：{first['spoken_text']}}}<衣摆、木椅轻响、孤灯火苗、对白尾息>",
        f"镜头2【7.2-14.0秒，陈迹近景反打再回双人近景】陈迹后脚稳在门槛内，拒绝落座，抬眼越过空椅按@音频2完整质问；灰衣门客收回示座手势、保持距离、全程闭口。两人最后隔案僵持。{{陈迹：{second['spoken_text']}}}<靴底停步、衣料轻响、灯芯噼啪、压低呼吸>",
        "【连续物理动作脚本】0-2秒：门客脚底发力起身，衣摆滞后落下；2-7.2秒：门客作揖、示座并说完@音频1，双手不取出任何道具；7.2-13.1秒：陈迹拒绝前进并说完@音频2，双手垂下不碰案桌；13.1-14秒：门客收手，双方隔案对视。",
        "【表演目的】门客用礼貌和座位争夺谈话节奏；陈迹以拒坐和旧疮质问夺回主动。门客始终温和无懈可击，陈迹始终冷硬带压迫，观众必须看懂双方都在试探。",
        "【声音】必须保留@音频1、@音频2原生口型对白和现场声；禁止BGM、旁白、额外对白。",
        "【负面约束】禁止字幕、水印、Logo、可读文字；禁止重复台词、串台、换脸、分身、瞬移、无因接近、慢放、停帧、循环、周期重复和静帧微动。",
    ]) + "\n"
    PROMPT.write_text(prompt, encoding="utf-8")
    for asset in task["dialogue_audio_assets"]:
        asset["sha256"] = sha256(ROOT / asset["path"])
    task = {
        **task,
        "task_key": "E31-CW-U15-PERFORMANCE-R2",
        "batch_id": "E31-U15-FAILED-ONLY-R2",
        "prompt_file": str(PROMPT.relative_to(ROOT)),
        "prompt_sha256": sha256(PROMPT),
        "retry_reason": "Changed actual prompt structure: each exact dialogue is now bound to one non-overlapping camera segment and is not repeated in both storyboard rows.",
        "status": "READY_CHANGED_INPUT_FAILED_ONLY_RETRY",
    }
    task["generation_fingerprint"] = generation_fingerprint(task)
    config = {
        **source,
        "status": "READY_FAILED_ONLY_U15_CHANGED_INPUT_R2",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "targeted_unit_replacement": True,
        "concurrency": 1,
        "tasks": [task],
        "prior_remote_failure_credit": 0,
    }
    CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"config": str(CONFIG.relative_to(ROOT)), "prompt": str(PROMPT.relative_to(ROOT)), "fingerprint": task["generation_fingerprint"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
