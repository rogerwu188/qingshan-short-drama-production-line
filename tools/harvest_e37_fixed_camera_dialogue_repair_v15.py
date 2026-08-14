#!/usr/bin/env python3
"""Poll and harvest E37 V15 fixed-camera dialogue tasks concurrently."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
API_SCRIPT = Path.home() / ".codex/skills/giggle-seedance2-gen/scripts/generation_api.py"
SUBMIT = ROOT / "workflow/tasks/E37_V15_FIXED_CAMERA_DIALOGUE_SUBMIT_20260804.json"
OUT_DIR = ROOT / "working_assets/e37_v15_fixed_camera_repair_20260804/video"
QA_DIR = ROOT / "qa/e37_v15_fixed_camera_repair_20260804/harvest"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_api():
    spec = importlib.util.spec_from_file_location("giggle_seedance_api", API_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {API_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def poll(task: dict) -> dict:
    api = load_api()
    key = api.check_api_key()
    if not key:
        raise RuntimeError("GIGGLE_API_KEY missing")
    client = api.SeedanceClient(key)
    task_id = task["task_id"]
    result = client.query_task(task_id)
    data = result.get("data", {})
    status = data.get("status", "")
    urls = client.extract_urls(result)
    row = {
        "segment_id": task["segment_id"],
        "task_key": task["task_key"],
        "task_id": task_id,
        "queried_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": status,
        "err_msg": data.get("err_msg", ""),
        "urls": urls,
        "prompt": task["prompt"],
        "prompt_sha256": task["prompt_sha256"],
        "model": task["model"],
        "resolution": task["resolution"],
    }
    if status == "completed" and urls:
        target = OUT_DIR / f"E37_{task['segment_id'].replace('-', '_')}_FIXED_TWO_COMPOSITIONS_V15_{task_id}.mp4"
        if not target.exists():
            response = requests.get(urls[0], timeout=180)
            response.raise_for_status()
            target.write_bytes(response.content)
        row.update({
            "output": str(target.relative_to(ROOT)),
            "output_sha256": sha256(target),
            "output_size_bytes": target.stat().st_size,
        })
    return row


def main() -> None:
    submit = json.loads(SUBMIT.read_text(encoding="utf-8"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    QA_DIR.mkdir(parents=True, exist_ok=True)
    rows, errors = [], []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(poll, task): task for task in submit["tasks"]}
        for future in as_completed(futures):
            task = futures[future]
            try:
                rows.append(future.result())
            except Exception as exc:
                errors.append({"task_key": task["task_key"], "task_id": task["task_id"], "error": str(exc)})
    rows.sort(key=lambda row: row["segment_id"])
    for row in rows:
        path = QA_DIR / f"E37_{row['segment_id'].replace('-', '_')}_V15_HARVEST.json"
        path.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    counts = {
        "completed": sum(row["status"] == "completed" for row in rows),
        "running": sum(row["status"] in {"running", "processing", "pending", "queued"} for row in rows),
        "failed": sum(row["status"] in {"failed", "error"} for row in rows),
        "query_errors": len(errors),
    }
    aggregate = {
        "schema": "qingshan.e37.v15_fixed_camera_dialogue_harvest.v1",
        "episode": "E37",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "submit_receipt": str(SUBMIT.relative_to(ROOT)),
        "submit_receipt_sha256": sha256(SUBMIT),
        "counts": counts,
        "tasks": rows,
        "errors": errors,
        "unchanged_retry": "PROHIBITED",
        "next_action": "Run rolling normal-speed no-sway QA on each completed source while remaining tasks continue."
    }
    path = QA_DIR / "E37_V15_FIXED_CAMERA_DIALOGUE_HARVEST.json"
    path.write_text(json.dumps(aggregate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"aggregate": str(path), "sha256": sha256(path), "counts": counts, "errors": errors}, ensure_ascii=False))


if __name__ == "__main__":
    main()
