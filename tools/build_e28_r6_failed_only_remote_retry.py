#!/usr/bin/env python3
"""Build E28 R6 from only the R5 terminal failures."""

from __future__ import annotations

import copy
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/E28_standard_storyboard_v1_sheetbound_failed_only_r5_promptrepair_20260720.json"
RECEIPT = ROOT / "workflow/tasks/E28_STANDARD_STORYBOARD_V1_SHEETBOUND_FAILED_ONLY_R5_PROMPTREPAIR_RECEIPT_20260720.json"
OUT = ROOT / "configs/E28_standard_storyboard_v1_sheetbound_failed_only_r6_remote_retry_20260720.json"
PROMPT_DIR = ROOT / "workflow/prompts/e28_standard_storyboard_v1_sheetbound_failed_only_r6_remote_retry_20260720"


def main() -> None:
    base = json.loads(BASE.read_text(encoding="utf-8"))
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    base_rows = {task["task_key"]: task for task in base["tasks"]}
    failed = [task for task in receipt["tasks"] if task.get("state") != "qa_pass"]
    retained = sorted(
        set(base.get("retained_pass_task_keys", []))
        | {task["task_key"] for task in receipt["tasks"] if task.get("state") == "qa_pass"}
    )
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    tasks = []
    for row in failed:
        task = copy.deepcopy(base_rows[row["task_key"]])
        prompt = (ROOT / task["prompt_file"]).read_text(encoding="utf-8").rstrip()
        new_prompt = PROMPT_DIR / f"{task['task_key']}.txt"
        new_prompt.write_text(
            prompt
            + "\n\n【R6 远端失败项重试】保持三张以内参考图和原剧情合约；连续自然运动，无停帧、伪文字、字幕、水印或书封标签；不要增加人物、地点、昼夜或剧情动作。\n",
            encoding="utf-8",
        )
        task["prompt_file"] = str(new_prompt.relative_to(ROOT))
        task["status"] = "READY_FOR_PARALLEL_SUBMIT"
        task["retry_of"] = {
            "batch": str(RECEIPT.relative_to(ROOT)),
            "task_id": row.get("task_id"),
            "state": row.get("state"),
        }
        for key in (
            "qa_dir", "output_dir", "state", "task_id", "submit_response", "credit_attempts",
            "submitted_at", "last_polled_at", "remote_status", "output_path", "sha256", "qa",
            "failure_evidence", "retry_count", "error", "settled_at",
        ):
            task.pop(key, None)
        tasks.append(task)
    out = copy.deepcopy(base)
    out.update({
        "status": "READY_FOR_FAILED_ONLY_PARALLEL_SUBMIT",
        "tasks": tasks,
        "video_tasks": tasks,
        "image_tasks": [],
        "output_dir": "working_assets/e28_standard_storyboard_v1_sheetbound_failed_only_r6_remote_retry_20260720",
        "qa_dir": "qa/e28_standard_storyboard_v1_sheetbound_failed_only_r6_remote_retry_20260720",
        "max_retries": 1,
        "base_batch_note": "R6 retries only the nine R5 terminal failures; preserve 27 passed siblings.",
        "retry_of": str(RECEIPT.relative_to(ROOT)),
        "retained_pass_task_keys": retained,
    })
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"failed_only_count": len(tasks), "retained_pass_count": len(retained)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
