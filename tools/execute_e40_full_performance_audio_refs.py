#!/usr/bin/env python3
"""Exactly-once audio-reference executor for E40 full-performance Seedance tasks."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from submit_giggle_task_manifest import ensure_giggle_api_key  # noqa: E402

try:
    from agentcut.speech import _download, query_speech, submit_speech
except ModuleNotFoundError as exc:
    raise SystemExit("Run with .agentcut_env/bin/python so agentcut speech is available") from exc

PLAN = ROOT / "workflow/claude_writer_agent/production/e40_remake_v1_20260817/full_performance_native_dialogue_v1/E40_FULL_PERFORMANCE_EXACT_DIALOGUE_AUDIO_REFERENCE_PLAN_20_V2.json"
TX_DIR = ROOT / "workflow/tasks/giggle_audio_submit_transactions/E40/full_performance_native_dialogue_v1"
OUT_DIR = ROOT / "working_assets/e40_remake_20260822/full_performance_native_dialogue_v1/audio_refs_v1"
RECEIPT = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/audio_refs_v1/E40_FULL_PERFORMANCE_AUDIO_REFERENCE_EXECUTION_V1.json"
AUTHORIZATION = "ROGER-20260821-E40-REBUILD-BUDGET-5000"
FFMPEG = shutil.which("ffmpeg") or str(next((ROOT / ".agentcut_env").glob("lib/python*/site-packages/agentcut/vendor/darwin-arm64/ffmpeg")))


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def fingerprint(item: dict[str, Any]) -> str:
    payload = {key: item[key] for key in ("audio_key", "dialogue_id", "text", "voice_id", "emotion", "speed")}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def tx_path(item: dict[str, Any]) -> Path:
    return TX_DIR / f"{item['audio_key']}__{fingerprint(item)[:16]}.json"


def prepare() -> int:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    prepared = []
    for item in plan["items"]:
        path = tx_path(item)
        if path.is_file():
            row = json.loads(path.read_text(encoding="utf-8"))
            if row.get("generation_fingerprint_sha256") != fingerprint(item):
                raise SystemExit(f"FINGERPRINT_COLLISION:{item['audio_key']}")
            prepared.append({"audio_key": item["audio_key"], "state": row.get("state"), "existing": True})
            continue
        transaction = {
            "schema": "qingshan.giggle_audio_submit_transaction.v1",
            "transaction_key": path.stem,
            "state": "INTENT_PERSISTED_NO_PROVIDER_POST_YET",
            "intent_persisted_at": now(),
            "episode": "E40",
            "authorization_ref": AUTHORIZATION,
            "generation_fingerprint_sha256": fingerprint(item),
            "request": {key: item[key] for key in ("text", "voice_id", "emotion", "speed")},
            "audio_key": item["audio_key"],
            "dialogue_id": item["dialogue_id"],
            "unit_id": item["unit_id"],
            "purpose": item["purpose"],
            "provider_post_count": 0,
            "maximum_new_submissions": 1,
            "maximum_gross_credits": 2,
            "automatic_retry": False,
            "timeout_rule": "QUERY_BOUND_TASK; RESPONSE_LOST_REQUIRES_LEDGER_CLASSIFICATION; NO_BLIND_REPOST",
        }
        atomic_json(path, transaction)
        prepared.append({"audio_key": item["audio_key"], "state": transaction["state"], "existing": False})
    print(json.dumps({"status": "PREPARED", "count": len(prepared), "transactions": prepared}, ensure_ascii=False))
    return 0


def execute() -> int:
    ensure_giggle_api_key()
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    rows: dict[str, dict[str, Any]] = {}
    for item in plan["items"]:
        path = tx_path(item)
        if not path.is_file():
            raise SystemExit(f"MISSING_PERSISTED_TRANSACTION:{item['audio_key']}")
        tx = json.loads(path.read_text(encoding="utf-8"))
        if tx.get("state") == "INTENT_PERSISTED_NO_PROVIDER_POST_YET":
            tx.update({"state": "POST_AUTHORIZATION_CONSUMED", "provider_post_count": 1, "maximum_new_submissions": 0, "submitted_at": now()})
            atomic_json(path, tx)
            try:
                response = submit_speech(item["text"], voice_id=item["voice_id"], emotion=item["emotion"], speed=float(item["speed"]))
            except Exception as exc:
                tx.update({"state": "POST_RESULT_UNKNOWN_NO_REPOST_REQUIRES_AUTHORITATIVE_CLASSIFICATION", "error": f"{type(exc).__name__}:{exc}", "automatic_retry": False})
                atomic_json(path, tx)
                rows[item["audio_key"]] = {"status": tx["state"], "task_id": None}
                continue
            task_id = str(response["taskId"])
            tx.update({"state": "REMOTE_TASK_BOUND_POLLING", "task_id": task_id, "task_id_bound_at": now(), "provider_submit_response": response})
            atomic_json(path, tx)
        elif tx.get("state") not in {"REMOTE_TASK_BOUND_POLLING", "TERMINAL_COMPLETED_DOWNLOADED"}:
            rows[item["audio_key"]] = {"status": tx.get("state"), "task_id": tx.get("task_id")}
            continue
        rows[item["audio_key"]] = {"status": tx.get("state"), "task_id": tx.get("task_id")}
        if tx.get("state") == "TERMINAL_COMPLETED_DOWNLOADED":
            wav = tx.get("output_wav")
            wav_sha256 = tx.get("output_wav_sha256")
            if not isinstance(wav, str) or not wav or not isinstance(wav_sha256, str) or not wav_sha256:
                raise SystemExit(f"COMPLETED_TRANSACTION_OUTPUT_MISSING:{item['audio_key']}")
            rows[item["audio_key"]].update({"wav": wav, "wav_sha256": wav_sha256})

    deadline = time.monotonic() + 300
    pending = {item["audio_key"]: item for item in plan["items"] if rows.get(item["audio_key"], {}).get("status") == "REMOTE_TASK_BOUND_POLLING"}
    while pending and time.monotonic() < deadline:
        for audio_key, item in list(pending.items()):
            path = tx_path(item)
            tx = json.loads(path.read_text(encoding="utf-8"))
            response = query_speech(tx["task_id"])
            tx.update({"last_query_at": now(), "last_remote_status": response.get("status")})
            atomic_json(path, tx)
            if response.get("status") == "failed":
                tx.update({"state": "TERMINAL_FAILED_NO_AUTOMATIC_RETRY", "finished_at": now(), "provider_response": response, "automatic_retry": False})
                atomic_json(path, tx)
                rows[audio_key] = {"status": tx["state"], "task_id": tx["task_id"]}
                pending.pop(audio_key)
            elif response.get("status") == "completed":
                urls = response.get("_urls") or []
                if not urls:
                    tx.update({"state": "TERMINAL_COMPLETED_WITHOUT_URL_NO_REPOST", "finished_at": now(), "provider_response": response})
                    atomic_json(path, tx)
                    rows[audio_key] = {"status": tx["state"], "task_id": tx["task_id"]}
                    pending.pop(audio_key)
                    continue
                OUT_DIR.mkdir(parents=True, exist_ok=True)
                mp3 = OUT_DIR / f"{audio_key}.mp3"
                wav = OUT_DIR / f"{audio_key}.wav"
                # A materially changed failed-only retry intentionally keeps the
                # canonical audio_key.  Replacement is safe only here, after the
                # newly bound task is authoritatively completed; no provider POST
                # occurs on this resume path.
                downloaded = _download(urls[0], mp3, overwrite=True)
                subprocess.run([FFMPEG, "-y", "-i", str(mp3), "-vn", "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(wav)], capture_output=True, check=True)
                tx.update({
                    "state": "TERMINAL_COMPLETED_DOWNLOADED",
                    "finished_at": now(),
                    "provider_response": response,
                    "output_mp3": rel(mp3),
                    "output_mp3_sha256": downloaded["sha256"],
                    "output_wav": rel(wav),
                    "output_wav_sha256": sha(wav),
                    "provider_audio_task_id": tx["task_id"],
                    "requires_asr_exactness_and_remote_asset_upload_before_video": True,
                    "maximum_new_submissions": 0,
                })
                atomic_json(path, tx)
                rows[audio_key] = {"status": tx["state"], "task_id": tx["task_id"], "wav": tx["output_wav"], "wav_sha256": tx["output_wav_sha256"]}
                pending.pop(audio_key)
        if pending:
            time.sleep(3)

    for audio_key, item in pending.items():
        path = tx_path(item)
        tx = json.loads(path.read_text(encoding="utf-8"))
        tx.update({"state": "REMOTE_TASK_BOUND_QUERY_NEXT_HEARTBEAT_NO_REPOST", "last_query_at": now(), "automatic_retry": False})
        atomic_json(path, tx)
        rows[audio_key] = {"status": tx["state"], "task_id": tx["task_id"]}
    atomic_json(RECEIPT, {
        "schema": "qingshan.e40.full_performance_audio_reference_execution.v1",
        "episode": "E40",
        "recorded_at": now(),
        "status_counts": {status: sum(1 for row in rows.values() if row["status"] == status) for status in sorted({row["status"] for row in rows.values()})},
        "items": [{"audio_key": key, **value} for key, value in rows.items()],
        "postproduction_replacement_forbidden": True,
        "next_gate": "ASR_EXACT_TEXT_PLUS_PROVIDER_ASSET_UPLOAD_BEFORE_SEEDANCE_VIDEO_POST",
    })
    print(json.dumps({"status": "EXECUTION_CHECKPOINT", "receipt": rel(RECEIPT), "receipt_sha256": sha(RECEIPT), "counts": json.loads(RECEIPT.read_text(encoding="utf-8"))["status_counts"]}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    return prepare() if args.prepare else execute()


if __name__ == "__main__":
    raise SystemExit(main())
