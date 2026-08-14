#!/usr/bin/env python3
"""Retry only E28 DIA-013 after R7 cadence/text QA failures."""

from __future__ import annotations

import copy
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/E28_standard_storyboard_v1_sheetbound_failed_only_r7_single_reference_20260720.json"
RECEIPT = ROOT / "workflow/tasks/E28_STANDARD_STORYBOARD_V1_SHEETBOUND_FAILED_ONLY_R7_SINGLE_REFERENCE_RECEIPT_20260720.json"
OUT = ROOT / "configs/E28_standard_storyboard_v1_sheetbound_failed_only_r8_dia013_motion_repair_20260720.json"
PROMPT_DIR = ROOT / "workflow/prompts/e28_standard_storyboard_v1_sheetbound_failed_only_r8_dia013_motion_repair_20260720"


def main() -> None:
    base = json.loads(BASE.read_text(encoding="utf-8"))
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    base_rows = {task["task_key"]: task for task in base["tasks"]}
    failed = [task for task in receipt["tasks"] if task.get("state") != "qa_pass"]
    if [task.get("task_key") for task in failed] != ["E28-DIA-013-VIDEO"]:
        raise SystemExit(f"expected only E28-DIA-013-VIDEO, got {[task.get('task_key') for task in failed]}")
    retained = sorted(
        set(base.get("retained_pass_task_keys", []))
        | {task["task_key"] for task in receipt["tasks"] if task.get("state") == "qa_pass"}
    )
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    row = failed[0]
    task = copy.deepcopy(base_rows[row["task_key"]])
    prompt = (ROOT / task["prompt_file"]).read_text(encoding="utf-8").rstrip()
    new_prompt = PROMPT_DIR / f"{task['task_key']}.txt"
    new_prompt.write_text(
        prompt
        + "\n\n【R8 DIA-013 动态修复】全程必须有连续、自然且可见的动作变化：人物呼吸、视线移动、手部检查屋梁、衣摆和烛火微动，镜头缓慢推进；最后两秒人物完成检查后自然转头回应，禁止停格、循环帧、周期性重复、静止结尾。画面内所有纸张、梁柱、器物和墙面必须完全无文字、无符号、无数字、无标签、无字幕和水印。\n",
        encoding="utf-8",
    )
    task["prompt_file"] = str(new_prompt.relative_to(ROOT))
    task["status"] = "READY_FOR_PARALLEL_SUBMIT"
    task["retry_of"] = {
        "batch": str(RECEIPT.relative_to(ROOT)),
        "task_id": row.get("task_id"),
        "state": row.get("state"),
        "failure_modes": ["unlisted_chinese_ocr", "periodic_duplicate_cadence"],
    }
    for key in (
        "qa_dir", "output_dir", "state", "task_id", "submit_response", "credit_attempts",
        "submitted_at", "last_polled_at", "remote_status", "output_path", "sha256", "qa",
        "failure_evidence", "retry_count", "error", "settled_at", "failure_reason",
    ):
        task.pop(key, None)
    out = copy.deepcopy(base)
    out.update({
        "status": "READY_FOR_FAILED_ONLY_PARALLEL_SUBMIT",
        "tasks": [task],
        "video_tasks": [task],
        "image_tasks": [],
        "output_dir": "working_assets/e28_standard_storyboard_v1_sheetbound_failed_only_r8_dia013_motion_repair_20260720",
        "qa_dir": "qa/e28_standard_storyboard_v1_sheetbound_failed_only_r8_dia013_motion_repair_20260720",
        "max_retries": 1,
        "base_batch_note": "R8 retries only DIA-013; preserve 35 passed siblings.",
        "retry_of": str(RECEIPT.relative_to(ROOT)),
        "retained_pass_task_keys": retained,
    })
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"failed_only_count": 1, "retained_pass_count": len(retained)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
