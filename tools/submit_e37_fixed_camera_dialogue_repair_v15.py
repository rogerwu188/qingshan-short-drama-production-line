#!/usr/bin/env python3
"""Submit independent E37 V15 fixed-camera dialogue units concurrently."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_SCRIPT = Path.home() / ".codex/skills/giggle-seedance2-gen/scripts/generation_api.py"
SOURCE = ROOT / "workflow/tasks/E37_V15_FIXED_CAMERA_DIALOGUE_PROMPT_BUILD_20260804.json"
OUT = ROOT / "workflow/tasks/E37_V15_FIXED_CAMERA_DIALOGUE_SUBMIT_20260804.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_api():
    spec = importlib.util.spec_from_file_location("giggle_seedance_api", API_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {API_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def submit(item: dict) -> dict:
    api = load_api()
    key = api.check_api_key()
    if not key:
        raise RuntimeError("GIGGLE_API_KEY missing")
    prompt_path = ROOT / item["prompt"]
    images = []
    for relative in item["reference_images"]:
        images.append({"base64": base64.b64encode((ROOT / relative).read_bytes()).decode("ascii")})
    result = api.SeedanceClient(key).omni_video(
        prompt=prompt_path.read_text(encoding="utf-8"),
        images=images,
        audios=None,
        videos=None,
        model="seedance-2.0-pro",
        duration=item["duration_seconds"],
        aspect_ratio="9:16",
        resolution="1080p",
        generating_count=1,
    )
    task_id = result.get("data", {}).get("task_id")
    if not task_id:
        raise RuntimeError(f"{item['task_key']}: response missing task_id: {result}")
    return {
        **item,
        "task_id": task_id,
        "submitted_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "state": "remote_running",
    }


def main() -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    rows, errors = [], []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(submit, item): item for item in source["tasks"]}
        for future in as_completed(futures):
            item = futures[future]
            try:
                rows.append(future.result())
            except Exception as exc:
                errors.append({"task_key": item["task_key"], "error": str(exc)})
    rows.sort(key=lambda row: row["segment_id"])
    payload = {
        "schema": "qingshan.e37.v15_fixed_camera_dialogue_submit.v1",
        "episode": "E37",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "SUBMITTED_ALL" if len(rows) == len(source["tasks"]) and not errors else "PARTIAL_OR_FAILED",
        "concurrency": {"max_workers": 4, "submitted": len(rows), "failed": len(errors)},
        "tasks": rows,
        "errors": errors,
        "credits": {"pay": 0, "refund": 0, "net": 0, "state": "PENDING_EXACT_TASK_BOUND_RECONCILIATION", "repair_round_cap": 10000},
        "next_action": "Poll in parallel, harvest completed media, reconcile Pay/Refund/Net per task, run normal-speed no-camera-drift gate, then bind only passing sources into V15.",
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"receipt": str(OUT), "sha256": sha256(OUT), "submitted": len(rows), "errors": errors}, ensure_ascii=False))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
