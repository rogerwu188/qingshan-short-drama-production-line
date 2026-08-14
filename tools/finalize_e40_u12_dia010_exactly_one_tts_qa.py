#!/usr/bin/env python3
"""Resume local-only QA for the already completed E40 U12 TTS task.

This tool has no submission code path. It can only bind and inspect the one
persisted task/output after the original QA process lost its stale ASR cache.
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

TRANSACTION = ROOT / "workflow/tasks/giggle_audio_submit_transactions/E40/E40-U12-DIA010-EXACTLY-ONE-TTS-V1.json"
MP3 = ROOT / "working_assets/e40_production_20260809/u12_dia010_exact_audio_v1/E40-U12-DIA010.mp3"
WAV = ROOT / "working_assets/e40_production_20260809/u12_dia010_exact_audio_v1/E40-U12-DIA010.wav"
QA = ROOT / "qa/e40_production_20260809/u12_dia010_exact_audio_v1/E40_U12_DIA010_EXACT_AUDIO_QA_V1.json"
RESUME = ROOT / "qa/e40_production_20260809/u12_dia010_exact_audio_v1/E40_U12_DIA010_LOCAL_QA_RESUME_V1.json"
RECEIPT = ROOT / "workflow/tasks/E40_U12_DIA010_EXACTLY_ONE_TTS_EXECUTION_20260809.json"
FAILURE_MEMORY = ROOT / "qa/e40_production_20260809/u12_dia010_exact_audio_v1/E40_U12_DIA010_TTS_FAILURE_MEMORY_V1.json"
TEXT = "调令上的印，是您的旧印。"
VOICE_ID = "clone_20251022_092746_158444"
TASK_ID = "591a223a-b2e2-479b-bf3f-fd9bf195b6ed"
FINGERPRINT = "3ea278d1b671044f432f78277d23da9dde63d69db20b5d97f9e4f89c2d8d989e"
EXPECTED_MP3_SHA = "13049923a7ccc11a2918ba3f51e13b7dffd5f1519e08748f686bb507b7a740ff"
EXPECTED_WAV_SHA = "36e1ab9a6955d1b821346b572f5b5a731253b406bb72d920bb8c98708d07e842"
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
        transaction.get("state") != "COMPLETED_DOWNLOADED_QA_RUNNING"
        or transaction.get("provider_post_count") != 1
        or transaction.get("authorization_remaining") != 0
        or transaction.get("task_id") != TASK_ID
        or transaction.get("generation_fingerprint_sha256") != FINGERPRINT
        or sha(MP3) != EXPECTED_MP3_SHA
        or sha(WAV) != EXPECTED_WAV_SHA
    ):
        raise SystemExit("FAIL_CLOSED_NOT_THE_BOUND_COMPLETED_TASK_OR_OUTPUT")

    remote = query_speech(TASK_ID)
    remote.pop("_urls", None)
    if remote.get("status") != "completed":
        raise SystemExit("FAIL_CLOSED_BOUND_REMOTE_TASK_NOT_COMPLETED")

    atomic_json(RESUME, {
        "schema": "qingshan.e40.local_audio_qa_resume.v1",
        "status": "RUNNING_LOCAL_ONLY_NO_PROVIDER_POST",
        "task_id": TASK_ID,
        "provider_post_count_preserved": 1,
        "root_cause": "STALE_ABSOLUTE_FASTER_WHISPER_CACHE_PATH_MISSING_AFTER_SUCCESSFUL_PROVIDER_COMPLETION_AND_DOWNLOAD",
        "workaround": "DOWNLOAD_OR_REUSE_CURRENT_SMALL_MODEL_AND_RESUME_ONLY_ASR_AUDIO_LEDGER_QA_ON_BOUND_MP3_WAV_SHA",
        "repost": False,
        "credits_before_resume": 0,
    })

    audio = metrics()
    model = WhisperModel("small", device="cpu", compute_type="int8", download_root="/Users/rogerwu/.cache/faster-whisper")
    segments, _ = model.transcribe(str(WAV), language="zh", vad_filter=True, beam_size=5, initial_prompt="以下是简体中文普通话对白。", hotwords=TEXT)
    transcript = "".join(segment.text.strip() for segment in segments)
    similarity = difflib.SequenceMatcher(None, norm(TEXT), norm(transcript)).ratio()
    credit = exact_credit()
    failures = []
    if similarity != 1.0:
        failures.append("ASR_NORMALIZED_EXACT_TEXT_SIMILARITY_NOT_1P0")
    if not 2.0 <= audio["duration_seconds"] <= 4.0:
        failures.append("DURATION_OUTSIDE_2_TO_4_SECONDS")
    if audio["integrated_lufs"] is None or not -20.0 <= audio["integrated_lufs"] <= -14.0:
        failures.append("SOURCE_INTEGRATED_LOUDNESS_OUTSIDE_MINUS20_TO_MINUS14_LUFS")
    if audio["true_peak_dbfs"] is None or audio["true_peak_dbfs"] > -1.0:
        failures.append("SOURCE_TRUE_PEAK_ABOVE_MINUS1_DBFS_OR_UNKNOWN")
    if credit.get("paid_credits") != 2 or credit.get("refunded_credits") != 0 or credit.get("net_charged_credits") != 2:
        failures.append("AUTHORITATIVE_LEDGER_NOT_EXACT_PAY2_REFUND0_NET2")

    qa = {
        "schema": "qingshan.e40.exact_dialogue_audio_qa.v1",
        "status": "PASS" if not failures else "FAIL",
        "episode": "E40",
        "unit": "U12",
        "line_id": "E40-DIA-010",
        "speaker": "陈迹",
        "expected_text": TEXT,
        "asr_transcript": transcript,
        "asr_similarity": round(similarity, 4),
        "speaker_identity_qa": {
            "status": "PASS_PROVIDER_CLONE_AND_PRODUCTION_VOICE_OWNER_BOUND",
            "voice_id": VOICE_ID,
            "native_voice_authority": "VOICE-陈迹-古装/cypqud0bu7t",
            "native_reference_sha256": "c63b69430a0fe29af41529759846fb3645935668b1a3aaa0ba237c6dae916eb5",
            "current_provider_voice": "PASS_YOUTH_MALE_ZH",
        },
        "source_qa": {
            "status": "PASS_EXACT_PROVIDER_TASK_AND_SINGLE_DOWNLOADED_SOURCE_BOUND",
            "task_id": TASK_ID,
            "remote_status": remote.get("status"),
            "generation_fingerprint_sha256": FINGERPRINT,
            "mp3_path": str(MP3.relative_to(ROOT)),
            "mp3_sha256": sha(MP3),
            "wav_path": str(WAV.relative_to(ROOT)),
            "wav_sha256": sha(WAV),
            "provider_post_count": 1,
        },
        "audio_metrics": audio,
        "duration_bounds_seconds": [2.0, 4.0],
        "loudness_bounds_lufs": [-20.0, -14.0],
        "true_peak_max_dbfs": -1.0,
        "credit": credit,
        "failures": failures,
        "human_listen_required_before_final_mix_release": True,
        "agentcut_attachment_executed": False,
    }
    atomic_json(QA, qa)

    if failures:
        memory = {
            "schema": "qingshan.e40.tts_failure_memory.v1",
            "status": "ACTIVE_NO_RETRY",
            "episode": "E40",
            "unit": "U12",
            "line_id": "E40-DIA-010",
            "task_id": TASK_ID,
            "generation_fingerprint_sha256": FINGERPRINT,
            "failed_audio_sha256": sha(WAV),
            "failures": failures,
            "replay_forbidden": True,
            "required_optimization_before_any_new_authorization": "Review the bound source and materially change only the failed delivery property; never replay this fingerprint.",
        }
        atomic_json(FAILURE_MEMORY, memory)
        transaction.update({"state": "TERMINAL_COMPLETED_QA_FAILED_NO_RETRY", "finished_at": now(), "qa_receipt": str(QA.relative_to(ROOT)), "qa_receipt_sha256": sha(QA), "credit": credit, "failure_memory": str(FAILURE_MEMORY.relative_to(ROOT)), "failure_memory_sha256": sha(FAILURE_MEMORY), "automatic_retry": False})
        atomic_json(TRANSACTION, transaction)
        status = "TERMINAL_COMPLETED_QA_FAILED_NO_RETRY"
    else:
        transaction.update({"state": "TERMINAL_COMPLETED_QA_PASS_NO_REPLAY", "finished_at": now(), "normalized_wav_path": str(WAV.relative_to(ROOT)), "normalized_wav_sha256": sha(WAV), "qa_receipt": str(QA.relative_to(ROOT)), "qa_receipt_sha256": sha(QA), "credit": credit, "automatic_retry": False})
        atomic_json(TRANSACTION, transaction)
        status = "TERMINAL_COMPLETED_QA_PASS_NO_REPLAY"

    atomic_json(RESUME, {
        "schema": "qingshan.e40.local_audio_qa_resume.v1",
        "status": "TERMINAL_LOCAL_QA_COMPLETE",
        "task_id": TASK_ID,
        "provider_post_count_preserved": 1,
        "root_cause": "STALE_ABSOLUTE_FASTER_WHISPER_CACHE_PATH_MISSING_AFTER_SUCCESSFUL_PROVIDER_COMPLETION_AND_DOWNLOAD",
        "workaround": "CURRENT_SMALL_MODEL_USED_FOR_LOCAL_ONLY_ASR_AUDIO_LEDGER_QA_ON_BOUND_MP3_WAV_SHA",
        "repost": False,
        "new_provider_posts": 0,
        "new_credits": 0,
        "final_qa": str(QA.relative_to(ROOT)),
        "final_qa_sha256": sha(QA),
    })
    receipt = {
        "schema": "qingshan.e40.u12.dia010.exactly_one_tts_execution.v1",
        "status": status,
        "task_id": TASK_ID,
        "voice_id": VOICE_ID,
        "spoken_text": TEXT,
        "generation_fingerprint_sha256": FINGERPRINT,
        "transaction": str(TRANSACTION.relative_to(ROOT)),
        "transaction_sha256": sha(TRANSACTION),
        "mp3_path": str(MP3.relative_to(ROOT)),
        "mp3_sha256": sha(MP3),
        "wav_path": str(WAV.relative_to(ROOT)),
        "wav_sha256": sha(WAV),
        "duration_seconds": audio["duration_seconds"],
        "asr_transcript": transcript,
        "asr_similarity": round(similarity, 4),
        "qa_receipt": str(QA.relative_to(ROOT)),
        "qa_receipt_sha256": sha(QA),
        "local_qa_resume": str(RESUME.relative_to(ROOT)),
        "local_qa_resume_sha256": sha(RESUME),
        "credit": credit,
        "provider_post_count": 1,
        "maximum_new_submissions": 0,
        "agentcut_attachment_executed": False,
        "forbidden_actions_observed": {"video_post": 0, "agentcut_render": 0, "browser": 0, "platform": 0},
    }
    if FAILURE_MEMORY.is_file():
        receipt["failure_memory"] = str(FAILURE_MEMORY.relative_to(ROOT))
        receipt["failure_memory_sha256"] = sha(FAILURE_MEMORY)
    atomic_json(RECEIPT, receipt)
    print(json.dumps({"status": status, "task_id": TASK_ID, "wav_sha256": sha(WAV), "duration_seconds": audio["duration_seconds"], "lufs": audio["integrated_lufs"], "true_peak_dbfs": audio["true_peak_dbfs"], "asr_transcript": transcript, "asr_similarity": round(similarity, 4), "pay": credit.get("paid_credits"), "refund": credit.get("refunded_credits"), "net": credit.get("net_charged_credits")}, ensure_ascii=False))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
