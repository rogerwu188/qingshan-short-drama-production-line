#!/usr/bin/env python3
"""Query/download the one bound R04 I2V native-dialogue pilot without replay."""

from __future__ import annotations

import argparse
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

TASK_KEY = "E40-FP-R04-YUNFEI-B-V1-VIDEO-V2"
TX_DIR = ROOT / "workflow/tasks/giggle_video_submit_transactions/E40"
ASSET = ROOT / "working_assets/e40_remake_20260822/full_performance_native_dialogue_v1/i2v_native_text_pilot_v2/E40-FP-R04-YUNFEI-B-V1-VIDEO-V2.mp4"
OUT = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/videos/E40_FULL_PERFORMANCE_VIDEO_I2V_NATIVE_TEXT_PILOT_HARVEST_V2.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def download_once(url: str, asset: Path) -> bool:
    if asset.is_file():
        return False
    asset.parent.mkdir(parents=True, exist_ok=True)
    temporary = asset.with_suffix(asset.suffix + ".part")
    with urllib.request.urlopen(url, timeout=300) as response, temporary.open("wb") as stream:
        while chunk := response.read(1024 * 1024):
            stream.write(chunk)
    if not temporary.is_file() or temporary.stat().st_size <= 0:
        raise RuntimeError("provider returned an empty pilot video")
    os.replace(temporary, asset)
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-key", default=TASK_KEY)
    parser.add_argument("--asset", default=rel(ASSET))
    parser.add_argument("--out", default=rel(OUT))
    args = parser.parse_args()
    task_key = str(args.task_key)
    asset = ROOT / args.asset
    out = ROOT / args.out
    api_key = os.environ.get("GIGGLE_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("Missing GIGGLE_API_KEY")
    matches = sorted(TX_DIR.glob(f"{task_key}__*.json"))
    if len(matches) != 1:
        raise SystemExit(f"transaction cardinality error: {len(matches)}")
    transaction = json.loads(matches[0].read_text(encoding="utf-8"))
    if transaction.get("state") != "SUBMITTED_TASK_ID_BOUND" or not transaction.get("task_id"):
        raise SystemExit(f"pilot is not durably bound: {transaction.get('state')}")
    response = query(api_key, str(transaction["task_id"]))
    data = response.get("data") or {}
    status = str(data.get("status") or "unknown").lower()
    payload = {
        "schema": "qingshan.e40.full_performance_i2v_native_text_pilot_harvest.v2",
        "episode": "E40",
        "task_key": task_key,
        "task_id": str(transaction["task_id"]),
        "observed_at": now(),
        "remote_status": status,
        "query_count_this_run": 1,
        "download_count_this_run": 0,
        "duplicate_post_forbidden": True,
        "transaction": rel(matches[0]),
        "transaction_sha256": sha(matches[0]),
    }
    urls = data.get("urls") or []
    if status == "completed" and urls:
        downloaded = download_once(str(urls[0]), asset)
        payload.update({
            "status": "COMPLETED_DOWNLOADED_PENDING_REGISTERED_Q2",
            "download_count_this_run": 1 if downloaded else 0,
            "video_path": rel(asset),
            "video_sha256": sha(asset),
            "bytes": asset.stat().st_size,
            "native_audio_must_be_preserved": True,
        })
    elif status in {"failed", "error", "canceled", "cancelled"}:
        payload.update({
            "status": "TERMINAL_FAILED_PENDING_EXACT_CREDIT_CLASSIFICATION",
            "terminal_error": data.get("err_msg") or data.get("fail_reason") or response.get("msg"),
        })
    else:
        payload["status"] = "REMOTE_RUNNING"
    write(out, payload)
    print(json.dumps({"status": payload["status"], "task_id": payload["task_id"], "out": rel(out), "sha256": sha(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
