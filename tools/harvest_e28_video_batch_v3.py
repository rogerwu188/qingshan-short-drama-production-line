#!/usr/bin/env python3
"""Harvest completed E28 V3 Seedance units and update the authoritative receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from giggle_api_client import query_task
from submit_giggle_task_manifest import ensure_giggle_api_key


ROOT = Path(__file__).resolve().parents[1]
FFPROBE = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffprobe"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def media_duration(path: Path) -> float:
    result = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return round(float(result.stdout.strip()), 3)


def download(url: str, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(output.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "qingshan-e28-harvester/1.0"})
    with urllib.request.urlopen(request, timeout=600) as response, partial.open("wb") as handle:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
    if partial.stat().st_size <= 0:
        raise RuntimeError(f"empty download: {url}")
    partial.replace(output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    if ensure_giggle_api_key() in {"MISSING", "UNSAFE_FILE_PERMISSIONS"}:
        raise RuntimeError("Giggle API key unavailable")
    receipt_path = Path(args.receipt).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    completed = 0
    running = 0
    failed = 0
    for task in receipt["tasks"]:
        response = query_task(SimpleNamespace(task_id=task["task_id"]))
        data = response.get("data") or {}
        status = str(data.get("status") or "unknown").lower()
        task["remote_status"] = status
        task["last_polled_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        if status == "completed":
            assets = data.get("asset_info") or []
            if not assets:
                raise RuntimeError(f"completed task has no asset: {task['task_id']}")
            asset = assets[0]
            output = output_dir / f"{task['unit_id']}_{task['task_id']}.mp4"
            if not output.is_file() or output.stat().st_size <= 0:
                download(asset.get("download_url") or asset.get("signed_url"), output)
            task.update({
                "state": "local_downloaded_pending_qa",
                "output_path": str(output),
                "output_sha256": sha256(output),
                "output_size_bytes": output.stat().st_size,
                "output_duration_seconds": media_duration(output),
                "remote_short_url": (data.get("urls") or [asset.get("download_url_shorter")])[0],
                "remote_asset_id": asset.get("asset_id"),
            })
            completed += 1
        elif status in {"failed", "error", "cancelled", "canceled"}:
            task.update({"state": "remote_failed", "failure_reason": data.get("err_msg") or status})
            failed += 1
        else:
            task["state"] = "remote_running"
            running += 1
    receipt["active_task_ids"] = [task["task_id"] for task in receipt["tasks"] if task["state"] == "remote_running"]
    receipt["active_task_count"] = len(receipt["active_task_ids"])
    receipt["downloaded_count"] = completed
    receipt["remote_failed_count"] = failed
    receipt["status"] = "ALL_DOWNLOADED_PENDING_QA" if completed == len(receipt["tasks"]) else "PARTIAL_DOWNLOADED_REMOTE_RUNNING"
    receipt["last_harvested_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    temporary = receipt_path.with_suffix(receipt_path.suffix + ".tmp")
    temporary.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(receipt_path)
    print(json.dumps({
        "status": receipt["status"],
        "downloaded": completed,
        "running": running,
        "failed": failed,
        "receipt": str(receipt_path),
    }, ensure_ascii=False))
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
