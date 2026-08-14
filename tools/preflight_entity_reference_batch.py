#!/usr/bin/env python3
"""Validate a no-network entity-reference batch and expose its exact media argv."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

try:
    from episode_parallel_batch_supervisor import abs_path, validate_entity_reference_task, validate_writer_agent_provenance
except ModuleNotFoundError:
    from tools.episode_parallel_batch_supervisor import abs_path, validate_entity_reference_task, validate_writer_agent_provenance


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command_preview(task: dict) -> list[str]:
    command = ["python3", "tools/giggle_api_client.py", "omni-video", "--prompt-file", str(abs_path(task["prompt_file"]))]
    for path in task.get("reference_images") or []:
        command.extend(["--reference-image", str(abs_path(path))])
    for path in task.get("reference_audios") or []:
        command.extend(["--audio", str(abs_path(path))])
    for asset_id in task.get("reference_audio_asset_ids") or []:
        command.extend(["--audio-asset-id", str(asset_id)])
    for path in task.get("reference_videos") or []:
        command.extend(["--video", str(abs_path(path))])
    command.extend([
        "--model", task.get("model", "seedance-2.0-pro"),
        "--duration", str(task.get("duration", 4)),
        "--aspect-ratio", task.get("aspect_ratio", "9:16"),
        "--resolution", task.get("resolution", "720p"),
        "--count", "1",
    ])
    return command


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    config_path = abs_path(args.config)
    out_path = abs_path(args.out)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    writer_ok, writer_failures = validate_writer_agent_provenance(config)
    results = []
    for task in config.get("tasks") or []:
        failures = validate_entity_reference_task(task)
        prompt_path = abs_path(task.get("prompt_file") or "")
        expected_prompt_sha = task.get("prompt_sha256")
        if not prompt_path.is_file():
            failures.append({"check": "prompt_exists", "path": str(prompt_path)})
        elif expected_prompt_sha and sha256(prompt_path) != expected_prompt_sha:
            failures.append({"check": "prompt_sha256", "expected": expected_prompt_sha, "actual": sha256(prompt_path)})
        results.append({
            "task_key": task.get("task_key"),
            "batch_id": task.get("batch_id"),
            "unit_id": task.get("unit_id"),
            "status": "PASS" if not failures else "FAIL",
            "failures": failures,
            "reference_image_count": len(task.get("reference_images") or []),
            "reference_audio_count": len(task.get("reference_audios") or []) + len(task.get("reference_audio_asset_ids") or []),
            "reference_video_count": len(task.get("reference_videos") or []),
            "required_slot_count": len(task.get("required_slot_ids") or []),
            "command_preview": command_preview(task),
        })

    report = {
        "schema": "qingshan.entity_reference_batch_preflight.v1",
        "config": str(config_path),
        "config_sha256": sha256(config_path),
        "status": "PASS" if writer_ok and all(row["status"] == "PASS" for row in results) else "FAIL",
        "writer_agent_provenance": "PASS" if writer_ok else "FAIL",
        "writer_agent_failures": writer_failures,
        "network_called": False,
        "remote_generation_called": False,
        "actual_charged_credits": 0,
        "results": results,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
