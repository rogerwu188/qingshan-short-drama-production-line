#!/usr/bin/env python3
"""Query and download the 26 already-bound E43 v6 tasks; never submit."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path.home() / ".local/share/backlotos/share/pipeline-tools"))
from giggle_api_shot_runner import query  # noqa: E402

SUBMISSION = ROOT / "qa/e43_v6_video_units/E43_V6_GIGGLE_VIDEO_SUBMISSION_V1.json"
ASSET_DIR = ROOT / "working_assets/e43_v6_video_units_a1"
RAW_DIR = ROOT / "qa/e43_v6_video_units/raw_status_a1"
OUT = ROOT / "qa/e43_v6_video_units/E43_V6_VIDEO_HARVEST_LATEST.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def download(url: str, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = out.with_suffix(out.suffix + ".part")
    with urllib.request.urlopen(url, timeout=300) as response, temporary.open("wb") as stream:
        while block := response.read(1024 * 1024):
            stream.write(block)
    os.replace(temporary, out)


def one(task: dict, api_key: str) -> dict:
    task_key, task_id = str(task["task_key"]), str(task["task_id"])
    unit_id = str(task.get("unit_id") or task_key.split("-VIDEO-A1")[0])
    response = query(api_key, task_id)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw = RAW_DIR / f"{task_key}_{task_id}.json"
    raw.write_text(json.dumps(response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    data = response.get("data") or {}
    status = str(data.get("status") or "unknown").lower()
    row = {
        "task_key": task_key,
        "unit_id": unit_id,
        "task_id": task_id,
        "status": status,
        "raw_response": str(raw.relative_to(ROOT)),
    }
    urls = data.get("urls") or []
    if status == "completed" and urls:
        path = ASSET_DIR / f"{unit_id}.mp4"
        if not path.is_file():
            download(str(urls[0]), path)
        row.update({
            "video_path": str(path.relative_to(ROOT)),
            "video_sha256": sha(path),
            "bytes": path.stat().st_size,
        })
    elif status in {"failed", "error", "canceled", "cancelled"}:
        row["terminal_error"] = data.get("fail_reason") or data.get("message") or response
    return row


def main() -> int:
    api_key = os.environ.get("GIGGLE_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("Missing GIGGLE_API_KEY")
    submission = json.loads(SUBMISSION.read_text(encoding="utf-8"))
    # Submission receipts persist bound remote handles under ``tasks``.  Older
    # receipt versions used ``results``; retain the fallback for compatibility
    # while preferring the authoritative field used by the current submitter.
    tasks = submission.get("tasks") or submission.get("results") or []
    if submission.get("status") != "PASS" or submission.get("submitted") != 26 or submission.get("failed") != 0:
        raise ValueError("E43 v6 submission is not the expected 26/26 bound batch")
    if len(tasks) != 26 or len({row.get("task_id") for row in tasks}) != 26:
        raise ValueError("E43 v6 harvest does not bind exactly 26 unique task IDs")
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(one, task, api_key) for task in tasks]
        rows = [future.result() for future in as_completed(futures)]
    rows.sort(key=lambda row: row["task_key"])
    terminal = {"completed", "failed", "error", "canceled", "cancelled"}
    counts = {value: sum(row["status"] == value for row in rows) for value in sorted({row["status"] for row in rows})}
    payload = {
        "schema": "qingshan.e43.video_harvest.v1",
        "episode": "E43",
        "production_version": 6,
        "observed_at": now(),
        "submission_ref": str(SUBMISSION.relative_to(ROOT)),
        "submission_sha256": sha(SUBMISSION),
        "status_counts": counts,
        "all_terminal": all(row["status"] in terminal for row in rows),
        "all_completed": all(row["status"] == "completed" for row in rows),
        "results": rows,
        "duplicate_post_forbidden": True,
        "post_generation_qa_scope": "TECHNICAL_AND_BASIC_PLOT_ONLY",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status_counts": counts,
        "all_terminal": payload["all_terminal"],
        "all_completed": payload["all_completed"],
        "out": str(OUT.relative_to(ROOT)),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
