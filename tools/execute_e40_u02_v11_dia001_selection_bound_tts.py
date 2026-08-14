#!/usr/bin/env python3
"""Selection-bound, exactly-once executor for E40 U02 DIA-001 speech."""

from __future__ import annotations

import argparse
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

SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E40剧本_ClaudeWriter_v3.md"
MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E40_manifest_v3.json"
PACKAGE = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u02_v11_dia001_selection_bound_tts_v1/E40_U02_V11_DIA001_SELECTION_BOUND_TTS_NO_SUBMIT_PACKAGE_V1.json"
AUTHORIZATION = ROOT / "workflow/approvals/E40_U02_DIA001_YUNFEI_SELECTION_AUTHORIZATION.json"
OUT = ROOT / "working_assets/e40_production_20260814/u02_v11_exact_yunfei_audio_v1"
MP3 = OUT / "E40-U02-DIA001.mp3"
WAV = OUT / "E40-U02-DIA001.wav"
QA = ROOT / "qa/e40_production_20260814/u02_v11_exact_yunfei_audio_v1/E40_U02_DIA001_EXACT_AUDIO_MACHINE_QA_V1.json"
RECEIPT = ROOT / "workflow/tasks/E40_U02_DIA001_SELECTION_BOUND_TTS_EXECUTION_20260814.json"
FAILURE_MEMORY = ROOT / "qa/e40_production_20260814/u02_v11_exact_yunfei_audio_v1/E40_U02_DIA001_TTS_FAILURE_MEMORY_V1.json"
TEXT = "阿栓，在本宫手上。"
SCRIPT_SHA = "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b"
MANIFEST_SHA = "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1"
PACKAGE_SHA = "42c9ab2b8256a533a4ab4126ac0085206dbcada87e16431b354eac5490d894e4"
CONFIRMATION_TOKEN = "E40-U02-DIA001-ONE-POST"
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


def candidate_from_authorization(package: dict[str, Any], authorization: dict[str, Any]) -> dict[str, Any]:
    selected = [
        row for row in package["candidate_request_envelopes"]
        if row["choice"] == authorization.get("selected_choice")
        and row["voice_id"] == authorization.get("selected_voice_id")
    ]
    if len(selected) != 1:
        raise SystemExit("FAIL_CLOSED_SELECTION_NOT_ONE_PACKAGED_CANDIDATE")
    candidate = selected[0]
    request = candidate["request"]
    required = {
        "schema": "qingshan.e40.u02.dia001.yunfei_selection_authorization.v1",
        "episode": "E40",
        "unit": "U02",
        "line_id": "E40-DIA-001",
        "selected_voice_id": candidate["voice_id"],
        "emotion": request["emotion"],
        "speed": request["speed"],
        "generation_fingerprint_sha256": candidate["generation_fingerprint_sha256"],
        "maximum_new_submissions": 1,
        "maximum_gross_credits": 2,
    }
    mismatches = [key for key, value in required.items() if authorization.get(key) != value]
    if mismatches or not authorization.get("explicit_user_confirmation"):
        raise SystemExit(f"FAIL_CLOSED_AUTHORIZATION_FIELDS:{','.join(mismatches)}")
    return candidate


def base_validation(require_authorization: bool) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None]:
    failures = []
    for path, expected in ((SCRIPT, SCRIPT_SHA), (MANIFEST, MANIFEST_SHA), (PACKAGE, PACKAGE_SHA)):
        if not path.is_file() or sha(path) != expected:
            failures.append(f"SHA_MISMATCH:{path.relative_to(ROOT)}")
    if TEXT not in SCRIPT.read_text(encoding="utf-8"):
        failures.append("CANONICAL_TEXT_MISSING")
    package = json.loads(PACKAGE.read_text(encoding="utf-8"))
    if package.get("status") != "PASS_READY_FOR_ONE_HUMAN_SELECTION_NO_SUBMIT":
        failures.append("PACKAGE_NOT_PASS")
    if failures:
        raise SystemExit("FAIL_CLOSED_COMMON_PREFLIGHT:" + ";".join(failures))
    if not AUTHORIZATION.exists():
        if require_authorization:
            raise SystemExit("WAITING_EXPLICIT_USER_VOICE_AND_EMOTION_SELECTION_AUTHORIZATION")
        return package, None, None
    authorization = json.loads(AUTHORIZATION.read_text(encoding="utf-8"))
    candidate = candidate_from_authorization(package, authorization)
    return package, authorization, candidate


def transaction_path(candidate: dict[str, Any]) -> Path:
    return ROOT / candidate["future_transaction_path"]


def record_terminal(transaction_path_value: Path, transaction: dict[str, Any], status: str, reason: str, response: dict[str, Any] | None, credit: dict[str, Any]) -> int:
    transaction.update({
        "state": status,
        "finished_at": now(),
        "provider_response": response,
        "credit": credit,
        "failure": reason,
        "automatic_retry": False,
        "maximum_new_submissions": 0,
    })
    atomic_json(transaction_path_value, transaction)
    memory = {
        "schema": "qingshan.e40.tts_failure_memory.v1",
        "status": status,
        "episode": "E40",
        "unit": "U02",
        "line_id": "E40-DIA-001",
        "task_id": transaction.get("task_id"),
        "generation_fingerprint_sha256": transaction["generation_fingerprint_sha256"],
        "failure": reason,
        "original_text": TEXT,
        "voice_id": transaction["request"]["voice_id"],
        "emotion": transaction["request"]["emotion"],
        "required_before_retry": ["authoritative remote terminal", "authoritative cost/refund classification", "material prompt change", "new explicit authorization"],
        "replay_forbidden": True,
    }
    atomic_json(FAILURE_MEMORY, memory)
    atomic_json(RECEIPT, {
        "schema": "qingshan.e40.u02.dia001.selection_bound_tts_execution.v1",
        "status": status,
        "task_id": transaction.get("task_id"),
        "failure": reason,
        "transaction": str(transaction_path_value.relative_to(ROOT)),
        "transaction_sha256": sha(transaction_path_value),
        "failure_memory": str(FAILURE_MEMORY.relative_to(ROOT)),
        "failure_memory_sha256": sha(FAILURE_MEMORY),
        "credit": credit,
    })
    print(json.dumps({"status": status, "task_id": transaction.get("task_id"), "failure": reason}, ensure_ascii=False))
    return 2


def audio_metrics(path: Path) -> dict[str, Any]:
    probe = subprocess.run([str(FFPROBE), "-v", "error", "-show_entries", "format=duration:stream=codec_name,sample_rate,channels", "-of", "json", str(path)], capture_output=True, text=True, check=True)
    loud = subprocess.run([str(FFMPEG), "-nostats", "-i", str(path), "-filter_complex", "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True, check=True)
    summary = loud.stderr.rsplit("Summary:", 1)[-1]
    integrated = re.search(r"I:\s+(-?[0-9.]+) LUFS", summary)
    true_peak = re.search(r"Peak:\s+(-?[0-9.]+) dBFS", summary)
    payload = json.loads(probe.stdout)
    return {"probe": payload, "duration_seconds": float(payload["format"]["duration"]), "integrated_lufs": float(integrated.group(1)) if integrated else None, "true_peak_dbfs": float(true_peak.group(1)) if true_peak else None}


def resume(transaction_path_value: Path, transaction: dict[str, Any]) -> int:
    task_id = transaction.get("task_id")
    if not task_id:
        raise SystemExit("FAIL_CLOSED_NO_BOUND_TASK_ID_NO_REPOST")
    response: dict[str, Any] = transaction.get("provider_submit_response") or {}
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        response = query_speech(task_id)
        transaction.update({"state": "REMOTE_TASK_BOUND_POLLING", "last_query_at": now(), "last_remote_status": response.get("status")})
        atomic_json(transaction_path_value, transaction)
        if response.get("status") in {"completed", "failed"}:
            break
        time.sleep(3)
    else:
        credit = credit_for(task_id)
        transaction.update({"state": "REMOTE_TIMEOUT_BOUND_REQUIRES_FUTURE_QUERY_NO_REPOST", "credit": credit, "last_query_at": now(), "automatic_retry": False})
        atomic_json(transaction_path_value, transaction)
        print(json.dumps({"status": transaction["state"], "task_id": task_id, "credit": credit}, ensure_ascii=False))
        return 3
    credit = credit_for(task_id)
    if response.get("status") != "completed":
        return record_terminal(transaction_path_value, transaction, "TERMINAL_FAILED_NO_RETRY", f"REMOTE_FAILED:{response.get('error')}", response, credit)
    rights = transaction.get("provider_submit_response", {}).get("commercialUseMetadata") or response.get("commercialUseMetadata") or {}
    urls = response.get("_urls") or []
    if not urls:
        return record_terminal(transaction_path_value, transaction, "TERMINAL_FAILED_NO_RETRY", "REMOTE_COMPLETED_WITHOUT_AUDIO_URL", response, credit)
    OUT.mkdir(parents=True, exist_ok=True)
    downloaded = _download(urls[0], MP3, overwrite=False)
    subprocess.run([str(FFMPEG), "-y", "-i", str(MP3), "-vn", "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(WAV)], capture_output=True, check=True)
    metrics = audio_metrics(WAV)
    model = WhisperModel(str(WHISPER), device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(WAV), language="zh", vad_filter=True, beam_size=5, initial_prompt="以下是简体中文普通话对白。", hotwords=TEXT)
    transcript = "".join(segment.text.strip() for segment in segments)
    similarity = difflib.SequenceMatcher(None, norm(TEXT), norm(transcript)).ratio()
    failures = []
    if similarity != 1.0:
        failures.append("ASR_NORMALIZED_EXACT_TEXT_SIMILARITY_NOT_1P0")
    if not 1.2 <= metrics["duration_seconds"] <= 3.5:
        failures.append("DURATION_OUTSIDE_1P2_TO_3P5_SECONDS")
    if metrics["integrated_lufs"] is None or not -22.0 <= metrics["integrated_lufs"] <= -14.0:
        failures.append("SOURCE_LOUDNESS_OUTSIDE_MINUS22_TO_MINUS14_LUFS")
    if metrics["true_peak_dbfs"] is None or metrics["true_peak_dbfs"] > -1.0:
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
        "voice_id": transaction["request"]["voice_id"],
        "commercial_use_metadata": rights,
        "task_id": task_id,
        "mp3_path": str(MP3.relative_to(ROOT)),
        "mp3_sha256": downloaded["sha256"],
        "wav_path": str(WAV.relative_to(ROOT)),
        "wav_sha256": sha(WAV),
        "audio_metrics": metrics,
        "credit": credit,
        "failures": failures,
        "human_listen_status": "PENDING",
        "agentcut_admission": "CLOSED_UNTIL_HUMAN_LISTEN_PASS",
    }
    atomic_json(QA, qa)
    if failures:
        transaction.update({"qa_receipt": str(QA.relative_to(ROOT)), "qa_receipt_sha256": sha(QA), "output_path": str(MP3.relative_to(ROOT)), "output_sha256": downloaded["sha256"]})
        return record_terminal(transaction_path_value, transaction, "TERMINAL_COMPLETED_QA_OR_RIGHTS_FAIL_NO_RETRY", ";".join(failures), response, credit)
    transaction.update({"state": "TERMINAL_COMPLETED_MACHINE_QA_PASS_HUMAN_LISTEN_PENDING_NO_REPLAY", "finished_at": now(), "output_path": str(MP3.relative_to(ROOT)), "output_sha256": downloaded["sha256"], "normalized_wav_path": str(WAV.relative_to(ROOT)), "normalized_wav_sha256": sha(WAV), "qa_receipt": str(QA.relative_to(ROOT)), "qa_receipt_sha256": sha(QA), "credit": credit, "automatic_retry": False})
    atomic_json(transaction_path_value, transaction)
    atomic_json(RECEIPT, {"schema": "qingshan.e40.u02.dia001.selection_bound_tts_execution.v1", "status": transaction["state"], "task_id": task_id, "transaction": str(transaction_path_value.relative_to(ROOT)), "transaction_sha256": sha(transaction_path_value), "qa_receipt": str(QA.relative_to(ROOT)), "qa_receipt_sha256": sha(QA), "credit": credit, "maximum_new_submissions": 0})
    print(json.dumps({"status": transaction["state"], "task_id": task_id, "wav_sha256": sha(WAV), "human_listen_status": "PENDING", "credit": credit}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--validate-only", action="store_true")
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--resume", action="store_true")
    parser.add_argument("--confirmation-token")
    args = parser.parse_args()
    package, authorization, candidate = base_validation(require_authorization=not args.validate_only)
    if args.validate_only:
        print(json.dumps({"status": "PASS_ZERO_NETWORK_WAITING_HUMAN_SELECTION" if authorization is None else "PASS_ZERO_NETWORK_SELECTION_AUTHORIZATION_PRESENT", "authorization_present": authorization is not None, "candidate_count": len(package["candidate_request_envelopes"]), "provider_posts": 0, "provider_queries": 0, "transactions": 0, "credits": 0}, ensure_ascii=False))
        return 0
    assert authorization is not None and candidate is not None
    selected_transaction = transaction_path(candidate)
    if args.resume:
        ensure_giggle_api_key()
        if not selected_transaction.is_file():
            raise SystemExit("FAIL_CLOSED_NO_TRANSACTION_TO_RESUME")
        return resume(selected_transaction, json.loads(selected_transaction.read_text(encoding="utf-8")))
    if args.confirmation_token != CONFIRMATION_TOKEN:
        raise SystemExit("FAIL_CLOSED_CONFIRMATION_TOKEN_REQUIRED")
    ensure_giggle_api_key()
    if selected_transaction.exists() or MP3.exists() or WAV.exists():
        raise SystemExit("FAIL_CLOSED_TRANSACTION_OR_OUTPUT_COLLISION_NO_REPOST")
    transaction = {
        "schema": "qingshan.giggle_audio_submit_transaction.v1",
        "transaction_key": selected_transaction.stem,
        "state": "INTENT_PERSISTED_NO_PROVIDER_POST_YET",
        "intent_persisted_at": now(),
        "episode": "E40",
        "unit": "U02",
        "line_id": "E40-DIA-001",
        "generation_fingerprint_sha256": candidate["generation_fingerprint_sha256"],
        "authorization": {"path": str(AUTHORIZATION.relative_to(ROOT)), "sha256": sha(AUTHORIZATION), "maximum_new_submissions": 1, "maximum_gross_credits": 2},
        "request": candidate["request"],
        "provider_post_count": 0,
        "task_id": None,
        "automatic_retry": False,
        "maximum_new_submissions": 1,
        "timeout_rule": "QUERY_EXACT_TASK_AND_AUTHORITATIVE_PAY_REFUND_LEDGER; NO_BLIND_REPOST",
    }
    atomic_json(selected_transaction, transaction)
    transaction.update({"state": "POST_ATTEMPT_AUTHORIZATION_CONSUMED", "submitted_at": now(), "provider_post_count": 1, "maximum_new_submissions": 0})
    atomic_json(selected_transaction, transaction)
    try:
        submitted = submit_speech(TEXT, voice_id=candidate["voice_id"], emotion=candidate["request"]["emotion"], speed=candidate["request"]["speed"])
    except Exception as exc:
        transaction.update({"state": "POST_RESULT_UNKNOWN_NO_REPOST_REQUIRES_AUTHORITATIVE_LEDGER_CLASSIFICATION", "failure": f"{type(exc).__name__}:{exc}", "automatic_retry": False})
        atomic_json(selected_transaction, transaction)
        print(json.dumps({"status": transaction["state"], "transaction": str(selected_transaction.relative_to(ROOT))}, ensure_ascii=False))
        return 3
    transaction.update({"state": "REMOTE_TASK_BOUND_POLLING", "task_id": submitted["taskId"], "provider_submit_response": submitted, "task_id_bound_at": now()})
    atomic_json(selected_transaction, transaction)
    return resume(selected_transaction, transaction)


if __name__ == "__main__":
    raise SystemExit(main())
