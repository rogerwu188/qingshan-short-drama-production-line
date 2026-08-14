#!/usr/bin/env python3
"""Submit E18/E19 omni multimodal candidate groups without blocking for completion."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


BASE = Path("/Users/rogerwu/qingshan_short_drama")
CLIENT = BASE / "tools/giggle_api_client.py"
PACKAGE = BASE / "configs/e18_e19_final_omni_multimodal_candidate_package_v1_20260715.json"
RUN_PLAN = BASE / "configs/e18_e19_final_omni_multimodal_submit_run_plan_v1_20260715.json"
RECEIPT = BASE / "workflow/generation/e18_e19/E18_E19_FINAL_OMNI_MULTIMODAL_SUBMIT_RECEIPT_20260715.json"
VIDEO_ASSET_MAP = BASE / "workflow/generation/e18_e19/video_asset_register_20260715/E18_E19_FINAL_OMNI_VIDEO_ASSET_MAP_20260715.json"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def duration_for(group: dict[str, Any]) -> int:
    # Giggle omni-video uses integer durations; preserve existing source length without going below 4s.
    return max(4, min(15, int(round(float(group.get("duration_window_sec") or 6)))))


def out_dir_for(group: dict[str, Any]) -> Path:
    episode = group["episode"].lower()
    source_id = group["source_id"]
    return BASE / f"working_assets/{episode}_final_omni_multimodal_candidates_v1_20260715/{source_id}"


def build_run_plan(package: dict[str, Any]) -> list[dict[str, Any]]:
    asset_map = {}
    if VIDEO_ASSET_MAP.exists():
        asset_map = (read_json(VIDEO_ASSET_MAP).get("assets") or {})
    plan: list[dict[str, Any]] = []
    for idx, group in enumerate(package["candidate_groups"], 1):
        source_video = Path(group["source_visual_baseline"])
        if not source_video.exists():
            raise SystemExit(f"Missing source visual baseline: {source_video}")
        prompt_file = Path(group["prompt_file"])
        if not prompt_file.exists():
            raise SystemExit(f"Missing prompt file: {prompt_file}")
        plan.append(
            {
                "shot_id": f"{idx:02d}",
                "episode": group["episode"],
                "source_id": group["source_id"],
                "prompt_file": str(prompt_file),
                "video_reference": str(source_video),
                "video_asset_id": (asset_map.get(group["source_id"]) or {}).get("asset_id"),
                "out_dir": str(out_dir_for(group)),
                "duration": duration_for(group),
                "model": "seedance-2.0-pro",
                "aspect_ratio": "9:16",
                "resolution": "720p",
                "dialogue_ids": group["dialogue_ids"],
                "submit_status": "READY_TO_SUBMIT_NONBLOCKING",
                "policy": "one multimodal video request with visual and audio/dialogue sections together; no standalone final dialogue audio",
            }
        )
    return plan


def submit_one(task: dict[str, Any], force: bool = False) -> dict[str, Any]:
    out_dir = Path(task["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = out_dir / "submit_response.json"
    if receipt_path.exists() and not force:
        prior = read_json(receipt_path)
        task_id = (prior.get("data") or {}).get("task_id") or prior.get("task_id")
        if task_id:
            return {
                "shot_id": task["shot_id"],
                "episode": task["episode"],
                "source_id": task["source_id"],
                "status": "ALREADY_SUBMITTED",
                "task_id": task_id,
                "receipt": str(receipt_path),
            }

    args = [
        "python3",
        str(CLIENT),
        "omni-video",
        "--prompt-file",
        task["prompt_file"],
        "--video",
        task["video_reference"],
        "--model",
        task["model"],
        "--duration",
        str(task["duration"]),
        "--aspect-ratio",
        task["aspect_ratio"],
        "--resolution",
        task["resolution"],
        "--count",
        "1",
    ]
    if task.get("video_asset_id"):
        video_index = args.index("--video")
        args[video_index:video_index + 2] = ["--video-asset-id", task["video_asset_id"]]
    proc = subprocess.run(args, cwd=BASE, env=os.environ.copy(), text=True, capture_output=True)
    if proc.returncode != 0:
        failure = {
            "shot_id": task["shot_id"],
            "episode": task["episode"],
            "source_id": task["source_id"],
            "status": "SUBMIT_FAILED",
            "stderr": proc.stderr[-2000:],
            "stdout": proc.stdout[-2000:],
        }
        (out_dir / "submit_failure.json").write_text(json.dumps(failure, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return failure
    receipt_path.write_text(proc.stdout, encoding="utf-8")
    response = json.loads(proc.stdout)
    task_id = (response.get("data") or {}).get("task_id") or response.get("task_id")
    return {
        "shot_id": task["shot_id"],
        "episode": task["episode"],
        "source_id": task["source_id"],
        "status": "SUBMITTED" if task_id else "SUBMIT_NO_TASK_ID",
        "task_id": task_id,
        "receipt": str(receipt_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Submit E18/E19 omni multimodal package concurrently.")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not os.environ.get("GIGGLE_API_KEY") and not args.dry_run:
        raise SystemExit("Missing GIGGLE_API_KEY")

    package = read_json(PACKAGE)
    plan = build_run_plan(package)
    RUN_PLAN.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RUN_PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.dry_run:
        print(json.dumps({"status": "DRY_RUN", "run_plan": str(RUN_PLAN), "task_count": len(plan)}, ensure_ascii=False))
        return 0

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        futures = [pool.submit(submit_one, task, args.force) for task in plan]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(json.dumps(result, ensure_ascii=False))

    status_counts: dict[str, int] = {}
    for result in results:
        status_counts[result["status"]] = status_counts.get(result["status"], 0) + 1
    payload = {
        "schema": "qingshan.e18_e19_omni_multimodal_submit_receipt.v1",
        "package": str(PACKAGE),
        "run_plan": str(RUN_PLAN),
        "status": "SUBMITTED_WITH_FAILURES" if any(r["status"].endswith("FAILED") for r in results) else "SUBMITTED_OR_ALREADY_SUBMITTED",
        "task_count": len(plan),
        "status_counts": status_counts,
        "results": sorted(results, key=lambda item: item["shot_id"]),
    }
    RECEIPT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 1 if payload["status"] == "SUBMITTED_WITH_FAILURES" else 0


if __name__ == "__main__":
    raise SystemExit(main())
