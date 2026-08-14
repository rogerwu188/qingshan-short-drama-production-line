#!/usr/bin/env python3
"""Query only the bound U05 V3 task and download its single asset at most once."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
PIPELINE_TOOLS = Path("/Users/rogerwu/.local/share/backlotos/share/pipeline-tools")
sys.path.insert(0, str(PIPELINE_TOOLS))
from giggle_api_client import query_task  # noqa: E402
from submit_giggle_task_manifest import ensure_giggle_api_key  # noqa: E402


TASK_ID = "36e91c3b-0c31-4e65-9146-a2d6c26bf092"
TASK_KEY = "E40-U05-V3-FAST720-ADMITTED-FRAME-NATIVE-EXACT-DIA004-V1"
TX = ROOT / "workflow/tasks/giggle_video_submit_transactions/E40/E40-U05-V3-FAST720-ADMITTED-FRAME-NATIVE-EXACT-DIA004-V1__166276fd8a025f48.json"
RAW_DIR = ROOT / "working_assets/e40_production_20260814/raw_u05_v3_fast720"
OUTPUT = ROOT / f"working_assets/e40_production_20260814/u05_v3_fast720/{TASK_KEY}_{TASK_ID}.mp4"
REPORT = ROOT / "workflow/tasks/E40_U05_V3_FAST720_HARVEST_20260814.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def portable(path: Path) -> str:
    return str(path.relative_to(ROOT))


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def download_once(url: str) -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    if OUTPUT.exists():
        return
    partial = OUTPUT.with_suffix(".mp4.part")
    if partial.exists():
        raise RuntimeError("partial output exists; manual classification required")
    request = urllib.request.Request(url, headers={"User-Agent": "qingshan-e40-u05-v3-bound-harvester/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=600) as response, partial.open("wb") as stream:
            for chunk in iter(lambda: response.read(1024 * 1024), b""):
                stream.write(chunk)
        if partial.stat().st_size <= 0:
            raise RuntimeError("empty downloaded video")
        os.replace(partial, OUTPUT)
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def main() -> None:
    if ensure_giggle_api_key() in {"MISSING", "UNSAFE_FILE_PERMISSIONS"}:
        raise SystemExit("GIGGLE_API_KEY unavailable")
    tx = json.loads(TX.read_text(encoding="utf-8"))
    if tx.get("state") != "SUBMITTED_TASK_ID_BOUND" or tx.get("task_id") != TASK_ID:
        raise SystemExit("transaction binding mismatch")
    prior = json.loads(REPORT.read_text(encoding="utf-8")) if REPORT.exists() else None
    if prior and prior.get("status") in {"COMPLETED_DOWNLOADED_PENDING_QA", "REMOTE_TERMINAL_FAILURE_NO_RETRY"}:
        print(json.dumps(prior, ensure_ascii=False))
        return

    queried_at = now()
    response = query_task(SimpleNamespace(task_id=TASK_ID))
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw = RAW_DIR / f"{TASK_KEY}_{TASK_ID}_{queried_at.replace(':', '').replace('-', '')}.json"
    atomic_json(raw, response)
    data = response.get("data") or {}
    remote_status = str(data.get("status") or "unknown").lower()
    history = list((prior or {}).get("query_history") or [])
    history.append({"queried_at": queried_at, "remote_status": remote_status, "raw_response": portable(raw), "raw_response_sha256": sha256(raw)})
    report = {
        "schema": "qingshan.e40.u05.v3.fast720_video_harvest.v1",
        "recorded_at": queried_at,
        "task_key": TASK_KEY,
        "task_id": TASK_ID,
        "transaction": portable(TX),
        "transaction_sha256": sha256(TX),
        "query_count": len(history),
        "download_count": 0,
        "remote_status": remote_status,
        "query_history": history,
        "provider_posts": 0,
        "new_transactions": 0,
        "new_credits": 0,
    }
    if remote_status == "completed":
        assets = data.get("asset_info") or []
        if len(assets) != 1:
            raise SystemExit(f"completed task asset count must be 1, got {len(assets)}")
        asset = assets[0]
        url = asset.get("download_url") or asset.get("signed_url")
        if not url:
            raise SystemExit("completed task missing signed download URL")
        already = OUTPUT.exists()
        download_once(url)
        report.update({
            "status": "COMPLETED_DOWNLOADED_PENDING_QA",
            "download_count": 0 if already else 1,
            "output_path": portable(OUTPUT),
            "output_sha256": sha256(OUTPUT),
            "output_size_bytes": OUTPUT.stat().st_size,
            "remote_asset_id": asset.get("asset_id"),
            "next_action": "Run mandatory technical, exact-frame, frame0 continuity, exact-line ASR, sole-speaker, lip-sync, OCR and original-resolution human QA.",
        })
    elif remote_status in {"failed", "error", "cancelled", "canceled"}:
        report.update({
            "status": "REMOTE_TERMINAL_FAILURE_NO_RETRY",
            "failure_reason": data.get("err_msg") or remote_status,
            "next_action": "Classify authoritative terminal/refund, persist failure memory and materially change prompt before any retry.",
        })
    else:
        report.update({
            "status": "REMOTE_RUNNING_NO_DOWNLOAD",
            "next_action": "Keep task-local REMOTE_WAIT and query only this exact task_id once at the next scheduled wakeup.",
        })
    atomic_json(REPORT, report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
