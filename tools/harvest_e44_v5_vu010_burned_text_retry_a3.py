#!/usr/bin/env python3
"""Harvest the one bound E44 VU010 A3 task; never submit."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path.home() / ".local/share/backlotos/share/pipeline-tools"))
from giggle_api_shot_runner import query  # noqa: E402

SUBMISSION = ROOT / "qa/e44_v5_a3_vu010_burned_text/E44_V5_VU010_A3_SUBMISSION_V1.json"
OUT = ROOT / "qa/e44_v5_a3_vu010_burned_text/E44_V5_VU010_A3_HARVEST_LATEST.json"
ASSET = ROOT / "working_assets/e44_v5_video_units_a3_burned_text/E44-VU-010.mp4"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    api_key = os.environ.get("GIGGLE_API_KEY", "").strip()
    submission = json.loads(SUBMISSION.read_text(encoding="utf-8"))
    tasks = submission.get("tasks") or []
    if not api_key or submission.get("status") != "PASS" or len(tasks) != 1:
        raise RuntimeError("missing API key or exact bound A3 submission")
    task = tasks[0]
    response = query(api_key, task["task_id"])
    raw = OUT.parent / f"{task['task_key']}_{task['task_id']}.json"
    raw.write_text(json.dumps(response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    data = response.get("data") or {}
    status = str(data.get("status") or "unknown").lower()
    row = {"task_key": task["task_key"], "unit_id": "E44-VU-010", "task_id": task["task_id"], "status": status, "raw_response": str(raw.relative_to(ROOT))}
    urls = data.get("urls") or []
    if status == "completed" and urls:
        ASSET.parent.mkdir(parents=True, exist_ok=True)
        temporary = ASSET.with_suffix(".mp4.part")
        if not ASSET.is_file():
            with urllib.request.urlopen(str(urls[0]), timeout=300) as response_stream, temporary.open("wb") as stream:
                while block := response_stream.read(1024 * 1024):
                    stream.write(block)
            os.replace(temporary, ASSET)
        row.update({"video_path": str(ASSET.relative_to(ROOT)), "video_sha256": sha(ASSET), "bytes": ASSET.stat().st_size})
    elif status in {"failed", "error", "canceled", "cancelled"}:
        row["terminal_error"] = data.get("fail_reason") or data.get("message") or response
    payload = {
        "schema": "qingshan.e44.v5.vu010_a3_harvest.v1",
        "episode": "E44",
        "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status_counts": {status: 1},
        "all_terminal": status in {"completed", "failed", "error", "canceled", "cancelled"},
        "all_completed": status == "completed",
        "results": [row],
        "duplicate_post_forbidden": True,
        "no_further_automatic_retry": True,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status_counts": payload["status_counts"], "all_terminal": payload["all_terminal"], "all_completed": payload["all_completed"], "out": str(OUT.relative_to(ROOT))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
