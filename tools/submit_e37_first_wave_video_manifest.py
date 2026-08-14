#!/usr/bin/env python3
"""Submit E37's prechecked first-wave video segments with production guards."""

from __future__ import annotations

import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from episode_video_generation_guard import (
    evaluate_episode_credit_gate,
    evaluate_episode_submission_authority,
    find_existing_paid_candidate,
    generation_fingerprint,
)
from giggle_api_client import generate_omni_video
from submit_giggle_task_manifest import ensure_giggle_api_key


ROOT = Path(__file__).resolve().parents[1]


def resolve(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def precheck(manifest: dict) -> list[dict]:
    failures: list[dict] = []
    for task in manifest.get("tasks", []):
        prompt = resolve(task["prompt_file"])
        refs = [resolve(value) for value in task.get("reference_images", [])]
        reasons = []
        if not prompt.is_file():
            reasons.append("PROMPT_MISSING")
        if not refs or any(not path.is_file() for path in refs):
            reasons.append("REFERENCE_IMAGE_MISSING")
        if not 4 <= int(task.get("duration_seconds", 0)) <= 15:
            reasons.append("DURATION_OUT_OF_RANGE")
        if reasons:
            failures.append({"task_key": task.get("task_key"), "reasons": reasons})
    return failures


def submit_one(task: dict, manifest: dict, raw_dir: Path) -> dict:
    enriched = {
        **task,
        "tool_type": "video_generation",
        "workflow_credit_scope": manifest["workflow_credit_scope"],
        "model": manifest["model"],
        "aspect_ratio": manifest["aspect_ratio"],
        "resolution": manifest["resolution"],
    }
    enriched["prompt_sha256"] = sha256(resolve(task["prompt_file"]))
    enriched["reference_assets"] = [
        {"path": value, "sha256": sha256(resolve(value))}
        for value in task["reference_images"]
    ]
    enriched["generation_fingerprint"] = generation_fingerprint(enriched)
    existing = find_existing_paid_candidate("E37", enriched)
    if existing:
        return {
            **enriched,
            "state": "tool_blocked",
            "block_code": "BLOCK_UNCHANGED_VIDEO_REGENERATION",
            "existing_candidate": existing,
        }

    args = SimpleNamespace(
        prompt="",
        prompt_file=str(resolve(task["prompt_file"])),
        model=manifest["model"],
        duration=int(task["duration_seconds"]),
        aspect_ratio=manifest["aspect_ratio"],
        resolution=manifest["resolution"],
        count=1,
        reference_image=[str(resolve(value)) for value in task["reference_images"]],
        image_url=None,
        image_asset_id=None,
        audio=None,
        audio_asset_id=None,
        video=None,
        video_asset_id=None,
    )
    response = generate_omni_video(args)
    raw_path = raw_dir / f"{task['task_key']}_submit_response.json"
    raw_path.write_text(json.dumps(response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    task_id = (response.get("data") or {}).get("task_id") or response.get("task_id")
    if not task_id:
        return {
            **enriched,
            "state": "submit_failed_terminal",
            "submit_response": str(raw_path.relative_to(ROOT)),
            "failure": response,
        }
    return {
        **enriched,
        "task_id": str(task_id),
        "state": "remote_running",
        "remote_status": "submitted",
        "submitted_at": utc_now(),
        "submit_response": str(raw_path.relative_to(ROOT)),
        "credit_attempts": [{
            "attempt": 1,
            "task_id": str(task_id),
            "success": None,
            "charge_status": "PENDING_REMOTE_RESULT",
            "actual_charged_credits": None,
            "generation_fingerprint": enriched["generation_fingerprint"],
        }],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--limit", type=int, default=10000)
    args = parser.parse_args()

    ensure_giggle_api_key()
    manifest_path = resolve(args.manifest)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    failures = precheck(manifest)
    credit_gate = evaluate_episode_credit_gate("E37", limit=args.limit)
    authority_gate = evaluate_episode_submission_authority("E37")
    if failures or credit_gate.get("status") != "PASS" or authority_gate.get("status") != "PASS":
        raise SystemExit(json.dumps({
            "status": "BLOCKED_PRECHECK",
            "failures": failures,
            "credit_gate": credit_gate,
            "authority_gate": authority_gate,
        }, ensure_ascii=False))

    out = resolve(args.out)
    raw_dir = out.parent / f"{out.stem}_responses"
    raw_dir.mkdir(parents=True, exist_ok=True)
    results = []
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        futures = {
            pool.submit(submit_one, task, manifest, raw_dir): task["task_key"]
            for task in manifest["tasks"]
        }
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:  # Preserve independent segment failures.
                results.append({
                    "task_key": futures[future],
                    "state": "submit_failed_terminal",
                    "error": f"{type(exc).__name__}: {exc}",
                })
    results.sort(key=lambda row: row["task_key"])
    submitted = sum(row.get("state") == "remote_running" for row in results)
    receipt = {
        "schema": "qingshan.e37.first_wave_video_submit.v1",
        "episode": "E37",
        "recorded_at": utc_now(),
        "status": "PASS_SUBMITTED" if submitted == len(results) else "PARTIAL_SUBMIT",
        "manifest": str(manifest_path.relative_to(ROOT)),
        "manifest_sha256": sha256(manifest_path),
        "concurrency": args.concurrency,
        "credit_gate": credit_gate,
        "authority_gate": authority_gate,
        "submitted": submitted,
        "total": len(results),
        "tasks": results,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": receipt["status"],
        "submitted": submitted,
        "total": len(results),
        "task_ids": [row.get("task_id") for row in results if row.get("task_id")],
    }, ensure_ascii=False))
    return 0 if submitted == len(results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
