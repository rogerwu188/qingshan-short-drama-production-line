#!/usr/bin/env python3
"""Build E32 U10's required terminal anchor from its admitted start state."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e32_claude_writer_v1_20260722"
SOURCE = PROD / "E32_IMAGE_BATCH_REMAINING_IDENTITY_REPAIR_R3.json"
HARVEST = PROD / "E32_IMAGE_BATCH_REMAINING_IDENTITY_REPAIR_R3_HARVEST.json"
OUT = PROD / "E32_IMAGE_U10_TERMINAL_ANCHOR_R4.json"
PROMPT = PROD / "image_prompts_performance_r4/E32-CW-U10-A2-R4-TOKEN-TRANSFER.txt"
START_QA = "workflow/claude_writer_agent/production/e32_claude_writer_v1_20260722/E32_REMAINING_IDENTITY_REPAIR_R3_IMAGE_QA.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def main() -> int:
    source = json.loads(SOURCE.read_text())
    harvest = json.loads(HARVEST.read_text())
    original = next(row for row in source["tasks"] if "-U10-" in row["task_key"])
    start = Path(next(row["output_path"] for row in harvest["results"] if "-U10-" in row["task_key"]))
    task = copy.deepcopy(original)
    task.update({
        "task_key": "E32-CW-U10-A2-STILL-R4-TOKEN-TRANSFER",
        "shot_id": "E32-CW-U10-A2-R4",
        "beat_id": "E32-CW-U10-R4",
        "state_index": 2,
        "state_count": 2,
        "status": "READY_FOR_PARALLEL_SUBMIT",
    })
    bindings = copy.deepcopy(task["reference_bindings"])
    scene = next(row for row in bindings if row["role"] == "scene")
    scene.update({
        "path": rel(start),
        "sha256": sha(start),
        "qa_status": "PASS",
        "qa_report": START_QA,
    })
    task["reference_bindings"] = bindings
    task["reference_images"] = [row["path"] for row in bindings]
    action = (
        "动作目的：生成与A1可物理连续插值的动作终态，明确完成灭口与巡检半牌换手；"
        "齐三仰躺雨地且已无生命反应，双手离开咽喉；巡检司杀手仍是A1同一人，已经退到暗巷出口远处，"
        "右手仍握短刃但破开的袖口不再持有铜牌；陈迹仍是A1同一人，右手两指夹住从地面拾起的半枚巡检铜牌，"
        "铜牌有清楚的半圆断边和不可读抽象印纹，印面朝向镜头；云羊仍是A1同一人，蹲在陈迹侧后方指向铜牌但不触碰。"
        "人物位置必须能从A1通过杀手横切、齐三后倒、杀手跃退、铜牌落地、陈迹拾牌连续到达；"
        "严格只有陈迹、云羊、齐三、巡检司杀手四个人类，不得新增人物、复制角色、文字、字幕或标志。"
    )
    contract = task["prompt_contract"]
    contract.update({
        "shot_id": task["shot_id"],
        "source_action": action,
        "source_action_sha256": hashlib.sha256(action.encode()).hexdigest(),
        "reference_bindings": copy.deepcopy(bindings),
        "state_index": 2,
        "state_count": 2,
        "state_role": "post_mortem_token_transfer_terminal",
        "status": "PASS",
        "failures": [],
    })
    PROMPT.parent.mkdir(parents=True, exist_ok=True)
    PROMPT.write_text(
        "《青山》E32 U10 A2终态锚，9:16电影写实古装雨夜。\n"
        "所有人物身份、服装、雨夜暗巷、机位和空间关系继承参考图；参考身份图只锁同名角色，不新增主体。\n"
        "这是同一连续动作结束后的单一时刻，不表现中间动作，不做拼贴、分镜格或多重曝光。\n"
        f"源动作 R4（必须逐字绑定）：{action}\n"
        "画面重点是陈迹两指夹住半枚铜牌、齐三死亡终态以及远处杀手已失去铜牌，三者归属不可矛盾。\n"
        "表情：陈迹震怒被压成冷静取证；云羊震怒确认；杀手急迫撤离；齐三无生命反应。\n"
        "禁止可读文字、字幕、水印、Logo；禁止多余人物、重复人物、换脸、融肢、额外刀具、完整圆牌或铜牌仍在杀手袖口。\n"
    )
    task["prompt_file"] = rel(PROMPT)
    task["prompt_sha256"] = sha(PROMPT)
    payload = {key: copy.deepcopy(value) for key, value in source.items() if key != "tasks"}
    payload.update({
        "status": "READY_REQUIRED_TERMINAL_ANCHOR",
        "output_dir": "working_assets/e32_performance_stills_20260722/u10_a2_r4",
        "qa_dir": "qa/e32_performance_stills_20260722/u10_a2_r4",
        "tasks": [task],
    })
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"manifest": rel(OUT), "tasks": 1}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
