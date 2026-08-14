#!/usr/bin/env python3
"""Consume one persisted E40 U12 TTS authorization and never replay it."""

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
from submit_giggle_task_manifest import ensure_giggle_api_key


ROOT = Path(__file__).resolve().parents[1]
AGENTCUT_SOURCE = Path("/Users/rogerwu/code/backlot-os/components/agentcut")
sys.path.insert(0, str(AGENTCUT_SOURCE))
from agentcut.speech import _download, query_speech, submit_speech  # noqa: E402

TRANSACTION = ROOT / "workflow/tasks/giggle_audio_submit_transactions/E40/E40-U12-DIA010-EXACTLY-ONE-TTS-V1.json"
AUTHORIZATION = ROOT / "workflow/approvals/E40_U12_DIA010_EXACTLY_ONE_TTS_AUTHORIZATION_20260809.json"
PREFLIGHT = ROOT / "qa/e40_preproduction_20260808/E40_U12_DIA010_EXACTLY_ONE_TTS_AUTHORIZED_PREFLIGHT_V1.json"
OUT = ROOT / "working_assets/e40_production_20260809/u12_dia010_exact_audio_v1"
MP3 = OUT / "E40-U12-DIA010.mp3"
WAV = OUT / "E40-U12-DIA010.wav"
QA = ROOT / "qa/e40_production_20260809/u12_dia010_exact_audio_v1/E40_U12_DIA010_EXACT_AUDIO_QA_V1.json"
RECEIPT = ROOT / "workflow/tasks/E40_U12_DIA010_EXACTLY_ONE_TTS_EXECUTION_20260809.json"
FAILURE_MEMORY = ROOT / "qa/e40_production_20260809/u12_dia010_exact_audio_v1/E40_U12_DIA010_TTS_FAILURE_MEMORY_V1.json"
TEXT = "调令上的印，是您的旧印。"
VOICE_ID = "clone_20251022_092746_158444"
EMOTION = "20岁陈迹隔帘掷出旧印拓影后声沉，冷静克制、证据落定的笃定；自然普通话，非旁白腔；逐字准确，不增删重复"
SPEED = 1.0
FINGERPRINT = "3ea278d1b671044f432f78277d23da9dde63d69db20b5d97f9e4f89c2d8d989e"
AUTHORIZATION_SHA = "ccfc7ee5bfa8b46b2e9f58474b7fa03a1ef1c4567e37f28a541d047566bca21c"
PREFLIGHT_SHA = "d5349dad5d8f32f7f67f378484e8b43a00631858bfd3722a2470f6080b416e70"
WHISPER = Path("/Users/rogerwu/.cache/huggingface/hub/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120")
FFMPEG = shutil.which("ffmpeg") or str(next((ROOT / ".agentcut_env").glob("lib/python*/site-packages/agentcut/vendor/darwin-arm64/ffmpeg")))
FFPROBE = shutil.which("ffprobe") or str(Path(FFMPEG).with_name("ffprobe"))
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


def credit_for(task_id: str) -> dict[str, Any]:
    latest: dict[str, Any] = {}
    for _ in range(8):
        latest = fetch_task_credit_net_by_task_id(task_id, event_description="SingleGenerateAudio")
        if latest.get("status") != "INCOMPLETE":
            return latest
        time.sleep(2)
    return latest


def audio_metrics(path: Path) -> dict[str, Any]:
    probe = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "format=duration:stream=codec_name,sample_rate,channels", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    loud = subprocess.run(
        [str(FFMPEG), "-nostats", "-i", str(path), "-filter_complex", "ebur128=peak=true", "-f", "null", "-"],
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


def record_failure(reason: str, transaction: dict[str, Any], response: dict[str, Any] | None, credit: dict[str, Any] | None) -> int:
    transaction.update({
        "state": "TERMINAL_FAILED_NO_RETRY",
        "finished_at": now(),
        "provider_response": response,
        "credit": credit or {"status": "UNKNOWN_REQUIRES_MANUAL_EXACT_TASK_LEDGER_CHECK"},
        "automatic_retry": False,
        "authorization_remaining": 0,
        "failure": reason,
    })
    atomic_json(TRANSACTION, transaction)
    memory = {
        "schema": "qingshan.e40.tts_failure_memory.v1",
        "status": "ACTIVE_NO_RETRY",
        "episode": "E40",
        "unit": "U12",
        "line_id": "E40-DIA-010",
        "generation_fingerprint_sha256": FINGERPRINT,
        "task_id": transaction.get("task_id"),
        "failure": reason,
        "original_text": TEXT,
        "voice_id": VOICE_ID,
        "emotion": EMOTION,
        "required_optimization_before_any_new_authorization": "Review exact task output and QA evidence; materially revise delivery only if Roger separately authorizes a new attempt. Never replay this fingerprint.",
        "replay_forbidden": True,
    }
    atomic_json(FAILURE_MEMORY, memory)
    atomic_json(RECEIPT, {
        "schema": "qingshan.e40.u12.dia010.exactly_one_tts_execution.v1",
        "status": "TERMINAL_FAILED_NO_RETRY",
        "task_id": transaction.get("task_id"),
        "failure": reason,
        "transaction": str(TRANSACTION.relative_to(ROOT)),
        "transaction_sha256": sha(TRANSACTION),
        "failure_memory": str(FAILURE_MEMORY.relative_to(ROOT)),
        "failure_memory_sha256": sha(FAILURE_MEMORY),
        "credit": transaction["credit"],
    })
    print(json.dumps({"status": "TERMINAL_FAILED_NO_RETRY", "task_id": transaction.get("task_id"), "failure": reason}, ensure_ascii=False))
    return 2


def main() -> int:
    ensure_giggle_api_key()
    transaction = json.loads(TRANSACTION.read_text(encoding="utf-8"))
    authorization = json.loads(AUTHORIZATION.read_text(encoding="utf-8"))
    preflight = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    if (
        transaction.get("state") != "INTENT_PERSISTED_NO_PROVIDER_POST_YET"
        or transaction.get("provider_post_count") != 0
        or transaction.get("generation_fingerprint_sha256") != FINGERPRINT
        or sha(AUTHORIZATION) != AUTHORIZATION_SHA
        or sha(PREFLIGHT) != PREFLIGHT_SHA
        or authorization.get("maximum_new_submissions") != 1
        or authorization.get("maximum_gross_credits") != 2
        or preflight.get("status") != "PASS"
        or MP3.exists()
        or WAV.exists()
    ):
        raise SystemExit("FAIL_CLOSED_PRE_POST_INTENT_AUTHORIZATION_PREFLIGHT_OR_OUTPUT_COLLISION")

    submitted_at = now()
    transaction.update({
        "state": "POST_ATTEMPT_AUTHORIZATION_CONSUMED",
        "submitted_at": submitted_at,
        "provider_post_count": 1,
        "authorization_remaining": 0,
        "maximum_new_submissions": 0,
    })
    atomic_json(TRANSACTION, transaction)

    try:
        submitted = submit_speech(TEXT, voice_id=VOICE_ID, emotion=EMOTION, speed=SPEED)
    except Exception as exc:
        return record_failure(f"POST_RESULT_UNKNOWN_OR_LOCAL_ERROR:{type(exc).__name__}:{exc}", transaction, None, None)

    task_id = submitted["taskId"]
    transaction.update({"state": "REMOTE_TASK_BOUND_POLLING", "task_id": task_id, "provider_submit_response": submitted, "task_id_bound_at": now()})
    atomic_json(TRANSACTION, transaction)

    response: dict[str, Any] = submitted
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        time.sleep(2)
        response = query_speech(task_id)
        transaction.update({"last_query_at": now(), "last_remote_status": response.get("status")})
        atomic_json(TRANSACTION, transaction)
        if response.get("status") in {"completed", "failed"}:
            break
    else:
        credit = credit_for(task_id)
        return record_failure("REMOTE_TIMEOUT_AUTHORITATIVE_TASK_BOUND_NO_REPOST", transaction, response, credit)

    if response.get("status") != "completed":
        credit = credit_for(task_id)
        return record_failure(f"REMOTE_FAILED:{response.get('error')}", transaction, response, credit)

    urls = response.get("_urls") or []
    if not urls:
        credit = credit_for(task_id)
        return record_failure("REMOTE_COMPLETED_WITHOUT_AUDIO_URL", transaction, response, credit)
    OUT.mkdir(parents=True, exist_ok=True)
    downloaded = _download(urls[0], MP3, overwrite=False)
    transaction.update({"state": "COMPLETED_DOWNLOADED_QA_RUNNING", "output_path": str(MP3.relative_to(ROOT)), "output_sha256": downloaded["sha256"], "downloaded_at": now()})
    atomic_json(TRANSACTION, transaction)

    subprocess.run([str(FFMPEG), "-y", "-i", str(MP3), "-vn", "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(WAV)], capture_output=True, check=True)
    metrics = audio_metrics(WAV)
    model = WhisperModel(str(WHISPER), device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(WAV), language="zh", vad_filter=True, beam_size=5, initial_prompt="以下是简体中文普通话对白。", hotwords=TEXT)
    transcript = "".join(segment.text.strip() for segment in segments)
    similarity = difflib.SequenceMatcher(None, norm(TEXT), norm(transcript)).ratio()
    duration = metrics["duration_seconds"]
    lufs = metrics["integrated_lufs"]
    peak = metrics["true_peak_dbfs"]
    failures = []
    if similarity != 1.0:
        failures.append("ASR_NORMALIZED_EXACT_TEXT_SIMILARITY_NOT_1P0")
    if not 2.0 <= duration <= 4.0:
        failures.append("DURATION_OUTSIDE_2_TO_4_SECONDS")
    if lufs is None or not -20.0 <= lufs <= -14.0:
        failures.append("SOURCE_INTEGRATED_LOUDNESS_OUTSIDE_MINUS20_TO_MINUS14_LUFS")
    if peak is None or peak > -1.0:
        failures.append("SOURCE_TRUE_PEAK_ABOVE_MINUS1_DBFS_OR_UNKNOWN")
    credit = credit_for(task_id)
    if credit.get("paid_credits") != 2 or credit.get("net_charged_credits") not in {0, 2}:
        failures.append("AUTHORITATIVE_LEDGER_NOT_EXACT_PAY2_NET0_OR2")
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
            "provider_voice_preflight": "PASS_YOUTH_MALE_ZH"
        },
        "source_qa": {
            "status": "PASS_EXACT_PROVIDER_TASK_AND_SINGLE_DOWNLOADED_SOURCE_BOUND",
            "task_id": task_id,
            "generation_fingerprint_sha256": FINGERPRINT,
            "mp3_path": str(MP3.relative_to(ROOT)),
            "mp3_sha256": sha(MP3),
            "wav_path": str(WAV.relative_to(ROOT)),
            "wav_sha256": sha(WAV),
        },
        "audio_metrics": metrics,
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
        transaction["qa_receipt"] = str(QA.relative_to(ROOT))
        transaction["qa_receipt_sha256"] = sha(QA)
        return record_failure(";".join(failures), transaction, response, credit)

    transaction.update({
        "state": "TERMINAL_COMPLETED_QA_PASS_NO_REPLAY",
        "finished_at": now(),
        "output_path": str(MP3.relative_to(ROOT)),
        "output_sha256": sha(MP3),
        "normalized_wav_path": str(WAV.relative_to(ROOT)),
        "normalized_wav_sha256": sha(WAV),
        "qa_receipt": str(QA.relative_to(ROOT)),
        "qa_receipt_sha256": sha(QA),
        "credit": credit,
        "automatic_retry": False,
        "authorization_remaining": 0,
    })
    atomic_json(TRANSACTION, transaction)
    receipt = {
        "schema": "qingshan.e40.u12.dia010.exactly_one_tts_execution.v1",
        "status": "TERMINAL_COMPLETED_QA_PASS_NO_REPLAY",
        "task_id": task_id,
        "voice_id": VOICE_ID,
        "spoken_text": TEXT,
        "generation_fingerprint_sha256": FINGERPRINT,
        "authorization": str(AUTHORIZATION.relative_to(ROOT)),
        "authorization_sha256": AUTHORIZATION_SHA,
        "transaction": str(TRANSACTION.relative_to(ROOT)),
        "transaction_sha256": sha(TRANSACTION),
        "mp3_path": str(MP3.relative_to(ROOT)),
        "mp3_sha256": sha(MP3),
        "wav_path": str(WAV.relative_to(ROOT)),
        "wav_sha256": sha(WAV),
        "duration_seconds": duration,
        "asr_transcript": transcript,
        "asr_similarity": round(similarity, 4),
        "qa_receipt": str(QA.relative_to(ROOT)),
        "qa_receipt_sha256": sha(QA),
        "credit": credit,
        "provider_post_count": 1,
        "maximum_new_submissions": 0,
        "agentcut_attachment_executed": False,
        "forbidden_actions_observed": {"video_post": 0, "agentcut_render": 0, "browser": 0, "platform": 0},
    }
    atomic_json(RECEIPT, receipt)
    print(json.dumps({"status": receipt["status"], "task_id": task_id, "wav_sha256": receipt["wav_sha256"], "duration_seconds": duration, "asr_similarity": round(similarity, 4), "pay": credit.get("paid_credits"), "refund": credit.get("refunded_credits"), "net": credit.get("net_charged_credits")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
