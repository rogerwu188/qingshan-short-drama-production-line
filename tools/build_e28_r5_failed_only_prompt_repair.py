#!/usr/bin/env python3
"""Build E28 R5 from only the R4 remote or QA failures."""

from __future__ import annotations

import copy
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE_CONFIG = ROOT / "configs/E28_standard_storyboard_v1_sheetbound_failed_only_r4_refcap3_20260720.json"
R4_RECEIPT = ROOT / "workflow/tasks/E28_STANDARD_STORYBOARD_V1_SHEETBOUND_FAILED_ONLY_R4_REFCAP3_RECEIPT_20260720.json"
OUT_CONFIG = ROOT / "configs/E28_standard_storyboard_v1_sheetbound_failed_only_r5_promptrepair_20260720.json"
PROMPT_DIR = ROOT / "workflow/prompts/e28_standard_storyboard_v1_sheetbound_failed_only_r5_promptrepair_20260720"


RUNTIME_KEYS = {
    "qa_dir", "output_dir", "state", "task_id", "submit_response", "credit_attempts",
    "submitted_at", "last_polled_at", "remote_status", "output_path", "sha256", "qa",
    "failure_evidence", "retry_count", "error", "settled_at",
}


def main() -> None:
    base = json.loads(BASE_CONFIG.read_text(encoding="utf-8"))
    receipt = json.loads(R4_RECEIPT.read_text(encoding="utf-8"))
    base_by_key = {task["task_key"]: task for task in base["tasks"]}
    failed_rows = [task for task in receipt["tasks"] if task.get("state") != "qa_pass"]
    retained = sorted(
        set(base.get("retained_pass_task_keys", []))
        | {task["task_key"] for task in receipt["tasks"] if task.get("state") == "qa_pass"}
    )
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    tasks = []
    for failed in failed_rows:
        key = failed["task_key"]
        task = copy.deepcopy(base_by_key[key])
        for runtime_key in RUNTIME_KEYS:
            task.pop(runtime_key, None)
        old_prompt = ROOT / task["prompt_file"]
        prompt = old_prompt.read_text(encoding="utf-8").rstrip()
        failures = failed.get("qa", {}).get("failures", [])
        failure_checks = {item.get("check") for item in failures if isinstance(item, dict)}
        repair_lines = [
            "",
            "【本轮失败项定向修复】",
            "全程保持人物、场景、服装、道具和剧情动作与原任务一致，不新增剧情，不改变昼夜、地点或角色身份。",
        ]
        if "frame_cadence" in failure_checks:
            repair_lines.append("人物呼吸、眼神、衣袖、手部和背景烛火必须持续自然运动；禁止定格、卡顿、循环帧、停顿后跳帧或伪慢动作。")
        if "full_motion_ocr" in failure_checks:
            repair_lines.append("画面内所有纸张、书封、匾额、标签、卷宗和器物表面必须完全空白；禁止任何可读或伪可读文字、数字、字母、印章、水印和字幕。")
        if failed.get("state") == "remote_failed_terminal":
            repair_lines.append("保持三张以内参考图绑定；本轮为远端瞬时失败重试，不增加参考图，不改变内容合约。")
        repair_lines.append("镜头需在目标时长内完成连续表演并保留可剪辑的起势、核心动作和收势，不用空镜填时长。")
        new_prompt = PROMPT_DIR / f"{key}.txt"
        new_prompt.write_text(prompt + "\n" + "\n".join(repair_lines) + "\n", encoding="utf-8")
        task["prompt_file"] = str(new_prompt.relative_to(ROOT))
        task["status"] = "READY_FOR_PARALLEL_SUBMIT"
        task["retry_of"] = {
            "batch": str(R4_RECEIPT.relative_to(ROOT)),
            "task_id": failed.get("task_id"),
            "state": failed.get("state"),
            "failure_checks": sorted(check for check in failure_checks if check),
        }
        tasks.append(task)

    out = copy.deepcopy(base)
    out.update({
        "status": "READY_FOR_FAILED_ONLY_PARALLEL_SUBMIT",
        "tasks": tasks,
        "video_tasks": tasks,
        "image_tasks": [],
        "output_dir": "working_assets/e28_standard_storyboard_v1_sheetbound_failed_only_r5_promptrepair_20260720",
        "qa_dir": "qa/e28_standard_storyboard_v1_sheetbound_failed_only_r5_promptrepair_20260720",
        "max_retries": 1,
        "base_batch_note": "R5 contains only R4 failures; preserve all R4 and earlier passes. Repair cadence/text prompts and retry remote failures under the three-reference provider cap.",
        "retry_of": str(R4_RECEIPT.relative_to(ROOT)),
        "retained_pass_task_keys": retained,
    })
    OUT_CONFIG.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "config": str(OUT_CONFIG),
        "failed_only_count": len(tasks),
        "retained_pass_count": len(retained),
        "failed_task_keys": [task["task_key"] for task in tasks],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
