#!/usr/bin/env python3
"""Build changed-input E31 U18-A R3 after an encoded opening-clause omission."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from episode_video_generation_guard import generation_fingerprint


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e31_claude_writer_v1_20260722/video_performance_v1"
SOURCE = BASE / "E31_VIDEO_BATCH_U18_SPLIT_DIALOGUE_R2.json"
PROMPT = BASE / "prompts/E31-CW-U18-A-PERFORMANCE-R3.txt"
CONFIG = BASE / "E31_VIDEO_BATCH_U18_A_DIALOGUE_R3.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    task = next(row for row in source["tasks"] if row["unit_id"] == "E31-CW-U18-A")
    row = task["dialogue"][0]
    line = row["spoken_text"]
    speaker = row["speaker"]
    prompt = "\n".join([
        "《青山》E31《王府风暴》U18-A R3，Seedance 2.0 Pro 四模态表演生成，8秒，9:16，720p，原速连续表演。",
        "【实体绑定】陈迹[[char_chenji]]、云羊[[char_yunyang]]、火后庭院[[scene_e31_s05]]、越级骨牌[[prop_e31_token]]。",
        "【生成范式】@图片1只锁人物身份、火后庭院、骨牌造型与空间方向；@音频1只驱动云羊。第一帧云羊已经接稳骨牌，取消接牌前置动作，确保音频从开头完整生成。",
        "【色彩与动机光】残火暖橙映面，雪夜环境冷蓝；人物动作的力量作用到环境介质，火苗、薄烟、衣摆只响应一次并自然衰减。",
        "【唯一对白】0.00秒云羊立即开口，严格从@音频1第一个字开始逐字说完；不得先沉默、不得从第二句开始、不得裁掉“这印是发调令的印”。台词只在后续分镜大括号声明一次，陈迹全程闭口。",
        f"镜头1【0.0-8.0秒，云羊持牌近景缓慢推近】第一帧云羊左掌已经稳稳托住骨牌，印纹朝向自己；他立刻开口，指腹沿凹刻短距离摩擦，眼神从疑惑变为震骇，最后抬眼看陈迹。{{{speaker}：{line}}}<骨牌轻摩指腹、衣料轻响、残火噼啪、风雪底噪>",
        "【连续物理链】0-0.2秒：云羊已持牌并立即说出第一字；0.2-5.3秒：保持骨牌归属不变，边确认刻痕边完整说完@音频1；5.3-7.2秒：抬眼看陈迹，呼吸发紧；7.2-8秒：握牌手轻收，反应落定。",
        "【表演目的】观众必须从完整判断、骤然变色和确认刻痕看懂：此印来自云羊无权接近的更高层级。",
        "【声音】必须保留@音频1从第一个字到最后一个字的原生中文普通话口型对白，以及残火、衣料、风雪现场声；禁止BGM、旁白、额外对白和重复台词。",
        "【负面约束】禁止字幕、水印、Logo、可读文字；禁止开头静默、吞掉首句、从中间起说、串台、改词、换脸、分身、瞬移、道具换手、慢放、停帧、循环、周期重复和静帧微动。",
    ]) + "\n"
    PROMPT.write_text(prompt, encoding="utf-8")
    task = {
        **task,
        "task_key": "E31-CW-U18-A-PERFORMANCE-R3",
        "batch_id": "E31-U18-A-DIALOGUE-R3",
        "duration": 8,
        "duration_seconds": 8,
        "duration_plan": {
            "policy": "qingshan.shot_generation_duration.v5",
            "duration_seconds": 8,
            "rationale": "Allow the exact five-second reference line to start at frame one and retain its closing reaction without compression.",
            "edit_policy": "End after the line and reaction land; never pad, slow or loop.",
        },
        "prompt_file": str(PROMPT.relative_to(ROOT)),
        "prompt_sha256": sha256(PROMPT),
        "retry_reason": "R2 final-source ASR proved the first independent clause was omitted after a 1.8-second handoff delay; R3 removes the handoff, starts speech at frame one, and adds two seconds.",
        "status": "READY_CHANGED_INPUT_FAILED_ONLY_RETRY",
    }
    task["performance_spec"] = {**task["performance_spec"], "duration_seconds": 8}
    task["performance_spec"]["motion_beats"] = [{
        **task["performance_spec"]["motion_beats"][0],
        "start_seconds": 0.0,
        "end_seconds": 8.0,
        "action": "Cloud Sheep already holds the token and begins the exact audio at frame one before inspecting the engraving.",
        "end_state": "The entire line is complete; token ownership remains with Cloud Sheep.",
    }]
    task["generation_fingerprint"] = generation_fingerprint(task)
    config = {
        **source,
        "status": "READY_FAILED_ONLY_U18_A_CHANGED_INPUT_R3",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "targeted_unit_replacement": True,
        "replaces_task_key": "E31-CW-U18-A-PERFORMANCE-R2",
        "concurrency": 1,
        "tasks": [task],
        "prior_candidate_retained_as_rollback": True,
    }
    CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"config": str(CONFIG.relative_to(ROOT)), "prompt": str(PROMPT.relative_to(ROOT)), "fingerprint": task["generation_fingerprint"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
