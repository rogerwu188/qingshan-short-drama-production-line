#!/usr/bin/env python3
"""Finalize local-only QA for the already completed E40 U02 DIA-001 TTS task.

This recovery tool has no provider submission code path. It only verifies the
persisted task/output, queries that exact task once, classifies its credit and
rights metadata, and runs local audio/ASR QA.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from faster_whisper import WhisperModel
from giggle_credit_statements import fetch_task_credit_net_by_task_id


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, "/Users/rogerwu/code/backlot-os/components/agentcut")
from agentcut.speech import query_speech  # noqa: E402

TRANSACTION = ROOT / "workflow/tasks/giggle_audio_submit_transactions/E40/E40-U02-DIA001-clone_20251022_101843_460135-EXACTLY-ONE-TTS-V1.json"
MP3 = ROOT / "working_assets/e40_production_20260814/u02_v11_exact_yunfei_audio_v1/E40-U02-DIA001.mp3"
WAV = ROOT / "working_assets/e40_production_20260814/u02_v11_exact_yunfei_audio_v1/E40-U02-DIA001.wav"
QA = ROOT / "qa/e40_production_20260814/u02_v11_exact_yunfei_audio_v1/E40_U02_DIA001_EXACT_AUDIO_MACHINE_QA_V1.json"
RESUME = ROOT / "qa/e40_production_20260814/u02_v11_exact_yunfei_audio_v1/E40_U02_DIA001_LOCAL_QA_RECOVERY_V1.json"
RECEIPT = ROOT / "workflow/tasks/E40_U02_DIA001_SELECTION_BOUND_TTS_EXECUTION_20260814.json"
FAILURE_MEMORY = ROOT / "qa/e40_production_20260814/u02_v11_exact_yunfei_audio_v1/E40_U02_DIA001_TTS_FAILURE_MEMORY_V1.json"
TEXT = "阿栓，在本宫手上。"
VOICE_ID = "clone_20251022_101843_460135"
TASK_ID = "b121d245-735a-4c79-a321-af77c3193faa"
FINGERPRINT = "c25c9785e0c5310206dd203e42ab476ab0b6d5f196746742c6ec05cfef29a4c8"
EXPECTED_MP3_SHA = "433d12bb98081a57306b8aa79a271d97da03ddc703060a92940a45573b3cf139"
EXPECTED_WAV_SHA = "856742736a0772d31e8de309a7eb6a5bab8188c74c63e45fb8b0e863774e25e1"
MODEL = Path("/Users/rogerwu/.cache/faster-whisper/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120")
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"
HAN = re.compile(r"[\u3400-\u9fffA-Za-z0-9]")


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def norm(value: str) -> str:
    return "".join(HAN.findall(value)).lower()


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def exact_credit() -> dict[str, Any]:
    latest: dict[str, Any] = {}
    for _ in range(8):
        latest = fetch_task_credit_net_by_task_id(TASK_ID, event_description="SingleGenerateAudio")
        if latest.get("status") != "INCOMPLETE":
            return latest
        time.sleep(2)
    return latest


def metrics() -> dict[str, Any]:
    probe = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration:stream=codec_name,sample_rate,channels", "-of", "json", str(WAV)],
        capture_output=True, text=True, check=True,
    )
    loud = subprocess.run(
        [FFMPEG, "-nostats", "-i", str(WAV), "-filter_complex", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    )
    summary = loud.stderr.rsplit("Summary:", 1)[-1]
    integrated = re.search(r"I:\s+(-?[0-9.]+) LUFS", summary)
    true_peak = re.search(r"Peak:\s+(-?[0-9.]+) dBFS", summary)
    payload = json.loads(probe.stdout)
    return {
        "probe": payload,
        "duration_seconds": float(payload["format"]["duration"]),
        "integrated_lufs": float(integrated.group(1)) if integrated else None,
        "true_peak_dbfs": float(true_peak.group(1)) if true_peak else None,
    }


def main() -> int:
    transaction = json.loads(TRANSACTION.read_text(encoding="utf-8"))
    if (
        transaction.get("state") != "REMOTE_TASK_BOUND_POLLING"
        or transaction.get("last_remote_status") != "completed"
        or transaction.get("provider_post_count") != 1
        or transaction.get("maximum_new_submissions") != 0
        or transaction.get("task_id") != TASK_ID
        or transaction.get("generation_fingerprint_sha256") != FINGERPRINT
        or sha(MP3) != EXPECTED_MP3_SHA
        or sha(WAV) != EXPECTED_WAV_SHA
        or not MODEL.joinpath("model.bin").is_file()
    ):
        raise SystemExit("FAIL_CLOSED_NOT_BOUND_COMPLETED_TASK_OUTPUT_OR_LOCAL_MODEL")

    remote = query_speech(TASK_ID)
    remote_urls = remote.pop("_urls", None)
    if remote.get("status") != "completed":
        raise SystemExit("FAIL_CLOSED_BOUND_REMOTE_TASK_NOT_COMPLETED")
    credit = exact_credit()
    rights = transaction.get("provider_submit_response", {}).get("commercialUseMetadata") or remote.get("commercialUseMetadata") or {}

    atomic_json(RESUME, {
        "schema": "qingshan.e40.local_audio_qa_recovery.v1",
        "status": "RUNNING_LOCAL_ONLY_NO_PROVIDER_POST",
        "task_id": TASK_ID,
        "provider_post_count_preserved": 1,
        "maximum_new_submissions_preserved": 0,
        "root_cause": "STALE_ABSOLUTE_FASTER_WHISPER_CACHE_PATH_AFTER_COMPLETED_PROVIDER_TASK_AND_DOWNLOAD",
        "recovery_model": str(MODEL),
        "repost": False,
        "remote_url_count_observed_not_downloaded": len(remote_urls or []),
    })

    audio = metrics()
    model = WhisperModel(str(MODEL), device="cpu", compute_type="int8", local_files_only=True)
    segments, _ = model.transcribe(str(WAV), language="zh", vad_filter=True, beam_size=5, initial_prompt="以下是简体中文普通话对白。", hotwords=TEXT)
    transcript = "".join(segment.text.strip() for segment in segments)
    similarity = difflib.SequenceMatcher(None, norm(TEXT), norm(transcript)).ratio()
    failures = []
    if similarity != 1.0:
        failures.append("ASR_NORMALIZED_EXACT_TEXT_SIMILARITY_NOT_1P0")
    if not 1.2 <= audio["duration_seconds"] <= 3.5:
        failures.append("DURATION_OUTSIDE_1P2_TO_3P5_SECONDS")
    if audio["integrated_lufs"] is None or not -22.0 <= audio["integrated_lufs"] <= -14.0:
        failures.append("SOURCE_LOUDNESS_OUTSIDE_MINUS22_TO_MINUS14_LUFS")
    if audio["true_peak_dbfs"] is None or audio["true_peak_dbfs"] > -1.0:
        failures.append("SOURCE_TRUE_PEAK_ABOVE_MINUS1_DBFS_OR_UNKNOWN")
    if rights.get("present") is not True or rights.get("releaseBlocked") is not False:
        failures.append("COMMERCIAL_USE_METADATA_NOT_RELEASE_CLEAR")
    if credit.get("status") == "INCOMPLETE":
        failures.append("AUTHORITATIVE_CREDIT_CLASSIFICATION_INCOMPLETE")

    qa = {
        "schema": "qingshan.e40.u02.dia001.exact_audio_machine_qa.v1",
        "status": "PASS_MACHINE_QA_HUMAN_LISTEN_PENDING" if not failures else "FAIL_NO_RETRY",
        "expected_text": TEXT,
        "asr_transcript": transcript,
        "asr_similarity": round(similarity, 4),
        "voice_id": VOICE_ID,
        "commercial_use_metadata": rights,
        "task_id": TASK_ID,
        "mp3_path": str(MP3.relative_to(ROOT)),
        "mp3_sha256": sha(MP3),
        "wav_path": str(WAV.relative_to(ROOT)),
        "wav_sha256": sha(WAV),
        "audio_metrics": audio,
        "credit": credit,
        "failures": failures,
        "human_listen_status": "PENDING" if not failures else "NOT_REACHED",
        "agentcut_admission": "CLOSED_UNTIL_HUMAN_LISTEN_PASS" if not failures else "CLOSED_FAILURE_GATE",
    }
    atomic_json(QA, qa)

    if failures:
        status = "TERMINAL_COMPLETED_QA_OR_RIGHTS_FAIL_NO_RETRY"
        memory = {
            "schema": "qingshan.e40.tts_failure_memory.v1",
            "status": status,
            "episode": "E40",
            "unit": "U02",
            "line_id": "E40-DIA-001",
            "task_id": TASK_ID,
            "generation_fingerprint_sha256": FINGERPRINT,
            "failed_audio_sha256": sha(WAV),
            "failures": failures,
            "original_text": TEXT,
            "voice_id": VOICE_ID,
            "replay_forbidden": True,
            "required_before_retry": [
                "authoritative terminal and credit classification",
                "commercial-rights-cleared replacement route",
                "material prompt or voice change",
                "new durable transaction",
            ],
        }
        atomic_json(FAILURE_MEMORY, memory)
    else:
        status = "TERMINAL_COMPLETED_MACHINE_QA_PASS_HUMAN_LISTEN_PENDING_NO_REPLAY"

    transaction.update({
        "state": status,
        "finished_at": now(),
        "provider_response": remote,
        "credit": credit,
        "output_path": str(MP3.relative_to(ROOT)),
        "output_sha256": sha(MP3),
        "normalized_wav_path": str(WAV.relative_to(ROOT)),
        "normalized_wav_sha256": sha(WAV),
        "qa_receipt": str(QA.relative_to(ROOT)),
        "qa_receipt_sha256": sha(QA),
        "automatic_retry": False,
        "maximum_new_submissions": 0,
    })
    if FAILURE_MEMORY.is_file():
        transaction["failure_memory"] = str(FAILURE_MEMORY.relative_to(ROOT))
        transaction["failure_memory_sha256"] = sha(FAILURE_MEMORY)
    atomic_json(TRANSACTION, transaction)

    atomic_json(RESUME, {
        "schema": "qingshan.e40.local_audio_qa_recovery.v1",
        "status": "TERMINAL_LOCAL_QA_COMPLETE",
        "task_id": TASK_ID,
        "provider_post_count_preserved": 1,
        "maximum_new_submissions_preserved": 0,
        "root_cause": "STALE_ABSOLUTE_FASTER_WHISPER_CACHE_PATH_AFTER_COMPLETED_PROVIDER_TASK_AND_DOWNLOAD",
        "recovery_model": str(MODEL),
        "repost": False,
        "new_provider_posts": 0,
        "final_qa": str(QA.relative_to(ROOT)),
        "final_qa_sha256": sha(QA),
    })
    receipt = {
        "schema": "qingshan.e40.u02.dia001.selection_bound_tts_execution.v1",
        "status": status,
        "task_id": TASK_ID,
        "transaction": str(TRANSACTION.relative_to(ROOT)),
        "transaction_sha256": sha(TRANSACTION),
        "qa_receipt": str(QA.relative_to(ROOT)),
        "qa_receipt_sha256": sha(QA),
        "local_qa_recovery": str(RESUME.relative_to(ROOT)),
        "local_qa_recovery_sha256": sha(RESUME),
        "credit": credit,
        "provider_post_count": 1,
        "maximum_new_submissions": 0,
    }
    if FAILURE_MEMORY.is_file():
        receipt["failure_memory"] = str(FAILURE_MEMORY.relative_to(ROOT))
        receipt["failure_memory_sha256"] = sha(FAILURE_MEMORY)
    atomic_json(RECEIPT, receipt)
    print(json.dumps({
        "status": status,
        "task_id": TASK_ID,
        "duration_seconds": audio["duration_seconds"],
        "lufs": audio["integrated_lufs"],
        "true_peak_dbfs": audio["true_peak_dbfs"],
        "asr_transcript": transcript,
        "asr_similarity": round(similarity, 4),
        "rights": rights,
        "credit": credit,
        "failures": failures,
    }, ensure_ascii=False))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
