#!/usr/bin/env python3
"""Correct U10 A2 so the patrol token belongs to black-clad Chenji."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e32_claude_writer_v1_20260722"
SOURCE = PROD / "E32_IMAGE_U10_TERMINAL_ANCHOR_R4.json"
HARVEST = PROD / "E32_IMAGE_U10_TERMINAL_ANCHOR_R4_HARVEST.json"
OUT = PROD / "E32_IMAGE_U10_TERMINAL_ANCHOR_R5_PROP_OWNER.json"
PROMPT = PROD / "image_prompts_performance_r5/E32-CW-U10-A2-R5-CHENJI-TOKEN.txt"
R4_QA = "workflow/claude_writer_agent/production/e32_claude_writer_v1_20260722/E32_U10_A2_R4_PROP_OWNERSHIP_QA.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def main() -> int:
    source = json.loads(SOURCE.read_text())
    harvest = json.loads(HARVEST.read_text())
    prior = Path(harvest["results"][0]["output_path"])
    task = copy.deepcopy(source["tasks"][0])
    task.update({
        "task_key": "E32-CW-U10-A2-STILL-R5-CHENJI-TOKEN",
        "shot_id": "E32-CW-U10-A2-R5",
        "beat_id": "E32-CW-U10-R5",
        "status": "READY_FOR_PARALLEL_SUBMIT",
    })
    bindings = copy.deepcopy(task["reference_bindings"])
    scene = next(row for row in bindings if row["role"] == "scene")
    scene.update({"path": rel(prior), "sha256": sha(prior), "qa_status": "PASS_COMPOSITION_ONLY", "qa_report": R4_QA})
    task["reference_bindings"] = bindings
    task["reference_images"] = [row["path"] for row in bindings]
    action = (
        "定向纠错且只改道具归属：保持参考图中的雨夜暗巷、死亡齐三、远处撤离杀手和四人身份不变；"
        "把半枚巡检铜牌从灰衣云羊右手彻底移除，灰衣云羊双手必须空着，只用右手食指指向旁边黑衣陈迹；"
        "半枚铜牌必须唯一地位于黑衣年轻陈迹的右手拇指与食指之间，黑衣陈迹把铜牌举到眼前查看，"
        "铜牌有半圆断边和不可读抽象印纹；不得复制铜牌，不得让云羊、齐三或杀手持有任何铜牌。"
        "严格只有黑衣陈迹、灰衣云羊、倒地齐三、远处巡检司杀手四个人类；人物身份、服装与脸不互换。"
    )
    contract = task["prompt_contract"]
    contract.update({
        "shot_id": task["shot_id"],
        "source_action": action,
        "source_action_sha256": hashlib.sha256(action.encode()).hexdigest(),
        "reference_bindings": copy.deepcopy(bindings),
        "state_role": "post_mortem_token_transfer_terminal_prop_owner_corrected",
        "status": "PASS",
        "failures": [],
    })
    PROMPT.parent.mkdir(parents=True, exist_ok=True)
    PROMPT.write_text(
        "《青山》E32 U10 A2终态锚 R5，9:16电影写实古装雨夜，单一时刻。\n"
        "参考图只用于锁定人物身份、服装、场景、齐三死亡和杀手撤离构图；R4道具持有人是已登记错误，必须按下面唯一变更纠正。\n"
        f"源动作 R5（必须逐字绑定）：{action}\n"
        "画面阅读顺序：倒地齐三无生命反应；黑衣陈迹举起唯一半枚铜牌审视；灰衣云羊空手指向陈迹；杀手背对镜头远离。\n"
        "表情：陈迹震怒被压成冷静取证；云羊震怒确认；杀手急迫撤离；齐三无生命反应。\n"
        "禁止文字、字幕、水印、Logo；禁止多余人物、重复人物、换脸、融肢、额外刀具、完整圆牌、两枚铜牌或灰衣云羊持牌。\n"
    )
    task["prompt_file"] = rel(PROMPT)
    task["prompt_sha256"] = sha(PROMPT)
    payload = {key: copy.deepcopy(value) for key, value in source.items() if key != "tasks"}
    payload.update({
        "status": "READY_CHANGED_INPUT_PROP_OWNER_REPAIR",
        "output_dir": "working_assets/e32_performance_stills_20260722/u10_a2_r5",
        "qa_dir": "qa/e32_performance_stills_20260722/u10_a2_r5",
        "tasks": [task],
    })
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"manifest": rel(OUT), "tasks": 1}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
