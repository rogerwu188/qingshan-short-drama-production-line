#!/usr/bin/env python3
"""Query/download bound E40 full-performance videos without provider replay."""

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

MANIFEST = ROOT / "workflow/claude_writer_agent/production/e40_remake_v1_20260817/full_performance_native_dialogue_v1/E40_FULL_PERFORMANCE_VIDEO_PREPRODUCTION_V1.json"
TX_DIR = ROOT / "workflow/tasks/giggle_video_submit_transactions/E40"
ASSET_DIR = ROOT / "working_assets/e40_remake_20260822/full_performance_native_dialogue_v1/videos_v1"
OUT = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/videos/E40_FULL_PERFORMANCE_VIDEO_HARVEST_LATEST.json"


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
    matches = sorted(TX_DIR.glob(f"{task['task_key']}__*.json"))
    if len(matches) != 1:
        return {"task_key": task["task_key"], "status": "TRANSACTION_CARDINALITY_ERROR", "count": len(matches)}
    tx = json.loads(matches[0].read_text(encoding="utf-8"))
    if tx.get("state") != "SUBMITTED_TASK_ID_BOUND" or not tx.get("task_id"):
        return {"task_key": task["task_key"], "status": tx.get("state"), "task_id": tx.get("task_id"), "transaction": str(matches[0].relative_to(ROOT))}
    response = query(api_key, str(tx["task_id"]))
    data = response.get("data") or {}
    status = str(data.get("status") or "unknown").lower()
    row = {"task_key": task["task_key"], "task_id": str(tx["task_id"]), "status": status, "transaction": str(matches[0].relative_to(ROOT))}
    if status == "completed" and data.get("urls"):
        path = ASSET_DIR / f"{task['task_key']}.mp4"
        if not path.is_file():
            download(str(data["urls"][0]), path)
        row.update({"video_path": str(path.relative_to(ROOT)), "video_sha256": sha(path), "bytes": path.stat().st_size})
    elif status in {"failed", "error", "canceled", "cancelled"}:
        row["terminal_error"] = data.get("fail_reason") or data.get("message") or response
    return row


def main() -> int:
    api_key = os.environ.get("GIGGLE_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("Missing GIGGLE_API_KEY")
    tasks = json.loads(MANIFEST.read_text(encoding="utf-8"))["tasks"]
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(one, task, api_key): task for task in tasks}
        rows = [future.result() for future in as_completed(futures)]
    rows.sort(key=lambda row: row["task_key"])
    payload = {
        "schema": "qingshan.e40.full_performance_video_harvest.v1",
        "episode": "E40",
        "observed_at": now(),
        "status_counts": {value: sum(row["status"] == value for row in rows) for value in sorted({row["status"] for row in rows})},
        "results": rows,
        "duplicate_post_forbidden": True,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status_counts": payload["status_counts"], "out": str(OUT.relative_to(ROOT)), "sha256": sha(OUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
