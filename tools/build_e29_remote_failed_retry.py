#!/usr/bin/env python3
"""Build changed-input retries for E29 video tasks that failed remotely at zero charge."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from episode_video_generation_guard import generation_fingerprint


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "workflow/claude_writer_agent/production/e29_claude_writer_v1_20260722"
SOURCE_CONFIG = PRODUCTION / "E29_15_VIDEO_UNIT_BATCH_V1.json"
SOURCE_RECEIPT = ROOT / "workflow/tasks/E29_15_VIDEO_UNIT_PARALLEL_BATCH_V1_20260722.json"
OUT_DIR = ROOT / "working_assets/e29_video_remote_failed_refs_v3_20260722"
PROMPT_DIR = PRODUCTION / "video_prompts_multistate_v3_remote_failed"
CONFIG_OUT = PRODUCTION / "E29_2_VIDEO_UNIT_REMOTE_FAILED_RETRY_V3.json"
RECEIPT_OUT = ROOT / "workflow/tasks/E29_2_VIDEO_UNIT_REMOTE_FAILED_RETRY_BUILD_V3_20260722.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def main() -> int:
    config = load(SOURCE_CONFIG)
    receipt = load(SOURCE_RECEIPT)
    failed = {
        row["task_key"]: row
        for row in receipt.get("tasks", [])
        if row.get("state") == "remote_failed_terminal"
        and any(
            attempt.get("success") is False
            and attempt.get("actual_charged_credits") == 0
            and attempt.get("task_id")
            for attempt in row.get("credit_attempts") or []
        )
    }
    if not failed:
        raise RuntimeError("no zero-credit remote failures")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    retry_tasks = []
    derivative_rows = []
    for source in config["tasks"]:
        failure = failed.get(source["task_key"])
        if not failure:
            continue
        task = json.loads(json.dumps(source))
        task["task_key"] = source["task_key"].replace("VIDEO-V1", "VIDEO-V3-REMOTE-FAILED")
        task["status"] = "READY_TO_SUBMIT"
        replacements = {}
        new_images = []
        for index, path_value in enumerate(source["reference_images"], 1):
            original = ROOT / path_value
            destination = OUT_DIR / f"{source['unit_id']}_REF{index:02d}_720x1280_q60.jpg"
            subprocess.run(
                [
                    "/usr/bin/sips",
                    "-s",
                    "format",
                    "jpeg",
                    "-s",
                    "formatOptions",
                    "60",
                    "-z",
                    "1280",
                    "720",
                    str(original),
                    "--out",
                    str(destination),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
            )
            old_sha = sha256(original)
            new_sha = sha256(destination)
            replacements[old_sha] = new_sha
            new_images.append(rel(destination))
            derivative_rows.append(
                {
                    "unit_id": source["unit_id"],
                    "source_path": path_value,
                    "source_sha256": old_sha,
                    "transport_path": rel(destination),
                    "transport_sha256": new_sha,
                    "transform": "SIPS_720X1280_JPEG_QUALITY60",
                }
            )
        task["reference_images"] = new_images
        for row, new_path in zip(task["reference_image_sequence"], new_images):
            old_sha = row["sha256"]
            row["source_candidate_sha256"] = old_sha
            row["source_candidate_path"] = row["path"]
            row["path"] = new_path
            row["sha256"] = replacements[old_sha]
            row["transport_derivative"] = True

        prompt = (ROOT / source["prompt_file"]).read_text(encoding="utf-8")
        for old_sha, new_sha in replacements.items():
            prompt = prompt.replace(old_sha, new_sha)
        prompt += (
            "\n【远端失败定向修复V3】本次仅规范化参考图传输并收紧生成约束；保持原剧本事实、人物身份、地点、时段和动作顺序。"
            "画面只保留剧本要求的人物数量，不增加远景人形、镜像人影或重复肢体；灯笼、车辆、墙面、衣物及器物不得出现任何可读或伪文字。"
            "不得恢复旧参考文件或旧提示词。\n"
        )
        prompt_path = PROMPT_DIR / f"{source['unit_id']}.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        task["prompt_file"] = rel(prompt_path)
        task["prompt_sha256"] = sha256(prompt_path)
        task["retry_reason"] = "REMOTE_FAILED_ZERO_CREDIT_CHANGED_TRANSPORT_AND_CONSTRAINTS"
        task["changed_generation_input"] = {
            "prompt_changed": True,
            "reference_asset_shas_changed": True,
            "source_attempt_task_id": failure.get("task_id"),
            "source_attempt_generation_fingerprint": source["generation_fingerprint"],
            "source_attempt_actual_charged_credits": 0,
        }
        task["generation_fingerprint"] = generation_fingerprint(task)
        if task["generation_fingerprint"] == source["generation_fingerprint"]:
            raise RuntimeError(f"generation fingerprint did not change: {source['unit_id']}")
        retry_tasks.append(task)

    retry_config = {
        **{key: value for key, value in config.items() if key != "tasks"},
        "status": "READY_FOR_FAILED_ONLY_PARALLEL_SUBMIT",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "concurrency": len(retry_tasks),
        "max_retries": 0,
        "retry_policy": "FAILED_ITEMS_ONLY_CHANGED_INPUT_REQUIRED",
        "source_batch": rel(SOURCE_CONFIG),
        "source_receipt": rel(SOURCE_RECEIPT),
        "tasks": retry_tasks,
    }
    CONFIG_OUT.write_text(json.dumps(retry_config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    build_receipt = {
        "schema": "qingshan.failed_only_remote_retry_build.v1",
        "episode": "E29",
        "status": "PASS_READY_FOR_FAILED_ONLY_PARALLEL_SUBMIT",
        "recorded_at": retry_config["recorded_at"],
        "source_failed_task_count": len(failed),
        "retry_task_count": len(retry_tasks),
        "source_attempt_credit": 0,
        "changed_generation_inputs": True,
        "units": sorted(task["unit_id"] for task in retry_tasks),
        "derivatives": derivative_rows,
        "config": rel(CONFIG_OUT),
        "config_sha256": sha256(CONFIG_OUT),
    }
    RECEIPT_OUT.write_text(json.dumps(build_receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": build_receipt["status"], "units": build_receipt["units"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
