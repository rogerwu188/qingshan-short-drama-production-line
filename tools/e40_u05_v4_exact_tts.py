#!/usr/bin/env python3
"""Durable, exactly-once TTS for E40 U05 DIA-004.

Prepare persists the no-submit package, live preflight, autonomous authorization,
and transaction intent. Execute consumes that intent once and immediately binds
the returned provider task id before polling and machine QA.
"""

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
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from faster_whisper import WhisperModel
from giggle_api_client import _get
from giggle_credit_statements import fetch_task_credit_net_by_task_id
from submit_giggle_task_manifest import ensure_giggle_api_key


ROOT = Path(__file__).resolve().parents[1]
AGENTCUT_SOURCE = Path("/Users/rogerwu/code/backlot-os/components/agentcut")
sys.path.insert(0, str(AGENTCUT_SOURCE))
from agentcut.speech import _download, query_speech, submit_speech  # noqa: E402

SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E40剧本_ClaudeWriter_v3.md"
MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E40_manifest_v3.json"
VOICE_REF = ROOT / "libraries/audio/voice_refs/native_multimodal_20260709/VOICE-陈迹-古装/e09_shot01_chenji_native_voice_ref.wav"
WORK_QUEUE = ROOT / "workflow/work_queue.json"
PACKAGE = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u05_v4_dia004_exact_tts_v1/E40_U05_V4_DIA004_EXACT_TTS_NO_SUBMIT_PACKAGE_V1.json"
PREFLIGHT = ROOT / "qa/e40_preproduction_20260814/u05_v4_dia004_exact_tts_v1/E40_U05_V4_DIA004_EXACT_TTS_PREFLIGHT_V1.json"
AUTH = ROOT / "workflow/approvals/E40_U05_DIA004_EXACTLY_ONE_TTS_AUTHORIZATION_20260814.json"
TX = ROOT / "workflow/tasks/giggle_audio_submit_transactions/E40/E40-U05-DIA004-EXACTLY-ONE-TTS-V1.json"
OUT = ROOT / "working_assets/e40_production_20260814/u05_v4_dia004_exact_audio_v1"
MP3 = OUT / "E40-U05-DIA004.mp3"
WAV = OUT / "E40-U05-DIA004.wav"
QA = ROOT / "qa/e40_production_20260814/u05_v4_dia004_exact_audio_v1/E40_U05_DIA004_EXACT_AUDIO_QA_V1.json"
RECEIPT = ROOT / "workflow/tasks/E40_U05_DIA004_EXACTLY_ONE_TTS_EXECUTION_20260814.json"
FAILURE = ROOT / "qa/e40_production_20260814/u05_v4_dia004_exact_audio_v1/E40_U05_DIA004_TTS_FAILURE_MEMORY_V1.json"
TEXT = "先请教娘娘——扣他，为何不杀？"
VOICE_ID = "clone_20251022_092746_158444"
EMOTION = "20岁陈迹将两页空白账页按落案面后抬眼隔帘追问，冷静克制、锋利但不喊叫；自然普通话，非旁白腔；逐字准确，不增删重复"
SPEED = 1.0
SCRIPT_SHA = "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b"
MANIFEST_SHA = "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1"
VOICE_REF_SHA = "c63b69430a0fe29af41529759846fb3645935668b1a3aaa0ba237c6dae916eb5"
WHISPER = Path("/Users/rogerwu/.cache/faster-whisper/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120")
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
    data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def live_price() -> tuple[int | None, dict[str, Any] | None]:
    response = _get("/api/v1/payment/credit-statements", {"credit_type": "Pay", "page": 1, "page_size": 100, "project_id": ""})
    rows = (response.get("data") or {}).get("list") or []
    rows = [row for row in rows if row.get("event_description") == "SingleGenerateAudio" and row.get("model_name") == "MinMax-Speech-2.8-hd"]
    rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    if not rows:
        return None, None
    try:
        return int(abs(Decimal(str(rows[0].get("credit"))))), rows[0]
    except (InvalidOperation, ValueError):
        return None, rows[0]


def credit_for(task_id: str) -> dict[str, Any]:
    latest: dict[str, Any] = {}
    for _ in range(8):
        latest = fetch_task_credit_net_by_task_id(task_id, event_description="SingleGenerateAudio")
        if latest.get("status") != "INCOMPLETE":
            return latest
        time.sleep(2)
    return latest


def prepare() -> int:
    ensure_giggle_api_key()
    if TX.exists():
        tx = json.loads(TX.read_text(encoding="utf-8"))
        print(json.dumps({"status": "EXISTING_TRANSACTION_NO_REPREPARE", "state": tx.get("state"), "task_id": tx.get("task_id")}, ensure_ascii=False))
        return 0
    failures: list[str] = []
    expected = {SCRIPT: SCRIPT_SHA, MANIFEST: MANIFEST_SHA, VOICE_REF: VOICE_REF_SHA}
    hashes = {}
    for path, wanted in expected.items():
        actual = sha(path) if path.is_file() else None
        hashes[str(path.relative_to(ROOT))] = {"expected": wanted, "actual": actual, "pass": actual == wanted}
        if actual != wanted:
            failures.append(f"SHA_MISMATCH:{path.relative_to(ROOT)}")
    if TEXT not in SCRIPT.read_text(encoding="utf-8"):
        failures.append("CANONICAL_TEXT_MISSING")
    if not WHISPER.is_dir():
        failures.append("LOCAL_WHISPER_MODEL_MISSING")
    voice_result = subprocess.run([str(ROOT / ".agentcut_env/bin/agentcut"), "speech-voices"], capture_output=True, text=True, check=True)
    voices = json.loads(voice_result.stdout.splitlines()[-1]).get("voices", [])
    voice_matches = [row for row in voices if row.get("voiceId") == VOICE_ID]
    if len(voice_matches) != 1 or voice_matches[0].get("gender") != "male" or voice_matches[0].get("age") != "youth":
        failures.append("CURRENT_PROVIDER_VOICE_BINDING_FAIL")
    price, statement = live_price()
    if price is None or price > 2:
        failures.append("CURRENT_AUDIO_PRICE_UNKNOWN_OR_ABOVE_PAY2")
    credits = (json.loads(WORK_QUEUE.read_text(encoding="utf-8")).get("e40_credits") or {})
    projected_net = int(credits.get("net") or 0) + int(price or 0)
    if projected_net > int(credits.get("cap") or 0):
        failures.append("E40_CREDIT_CAP_FAIL")
    collisions = []
    audio_tx_dir = ROOT / "workflow/tasks/giggle_audio_submit_transactions/E40"
    for path in audio_tx_dir.glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        request = payload.get("request") or {}
        if request.get("text") == TEXT and request.get("voice_id") == VOICE_ID:
            collisions.append(str(path.relative_to(ROOT)))
    if collisions or MP3.exists() or WAV.exists():
        failures.append("EXACT_AUDIO_COLLISION")
    package = {
        "schema": "qingshan.e40.u05.v4.dia004.exact_tts.no_submit.v1",
        "status": "PASS_READY_NO_SUBMIT" if not failures else "FAIL_CLOSED_NO_SUBMIT",
        "recorded_at": now(),
        "canonical": {"episode": "E40", "unit": "U05", "line_id": "E40-DIA-004", "speaker": "陈迹", "text": TEXT, "script_sha256": SCRIPT_SHA, "manifest_sha256": MANIFEST_SHA},
        "voice": {"voice_id": VOICE_ID, "owner_contract": "VOICE-E40-CHENJI-NATIVE-MULTIMODAL-CANONICAL", "reference_path": str(VOICE_REF.relative_to(ROOT)), "reference_sha256": VOICE_REF_SHA, "current_provider_match": voice_matches},
        "request": {"text": TEXT, "voice_id": VOICE_ID, "emotion": EMOTION, "speed": SPEED},
        "output": {"mp3": str(MP3.relative_to(ROOT)), "wav": str(WAV.relative_to(ROOT))},
        "rights": {"commercial_release_required": True, "provider_release_blocked_must_be_false": True},
        "provider_posts": 0,
        "failures": failures,
    }
    atomic_json(PACKAGE, package)
    fingerprint_payload = {"canonical_script_sha256": SCRIPT_SHA, "canonical_manifest_sha256": MANIFEST_SHA, "package_sha256": sha(PACKAGE), "request": package["request"], "output": package["output"]}
    fingerprint = hashlib.sha256(json.dumps(fingerprint_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    preflight = {"schema": "qingshan.e40.u05.v4.dia004.exact_tts.preflight.v1", "status": "PASS" if not failures else "FAIL_CLOSED", "recorded_at": now(), "failures": failures, "hashes": hashes, "package": str(PACKAGE.relative_to(ROOT)), "package_sha256": sha(PACKAGE), "generation_fingerprint_sha256": fingerprint, "current_price_credits": price, "latest_price_statement": statement, "e40_credits_before": credits, "projected_net_after": projected_net, "collisions": collisions, "network_actions": {"voice_list_get": 1, "ledger_get": 1, "provider_post": 0}}
    atomic_json(PREFLIGHT, preflight)
    if failures:
        print(json.dumps({"status": "FAIL_CLOSED", "failures": failures}, ensure_ascii=False))
        return 2
    authorization = {"schema": "qingshan.exactly_one_tts_authorization.v1", "status": "AUTHORIZED_EXACTLY_ONE_TTS", "authorized_at": now(), "episode": "E40", "unit": "U05", "line_id": "E40-DIA-004", "source_authority": ["ROGER_STANDING_EPISODE_CREDIT_CAP_10000_20260730", "ROGER_AUTONOMOUS_ROUTINE_PRODUCTION_CHOICES_20260814"], "authorized_text": TEXT, "authorized_voice_id": VOICE_ID, "authorized_emotion": EMOTION, "authorized_speed": SPEED, "generation_fingerprint_sha256": fingerprint, "preflight": str(PREFLIGHT.relative_to(ROOT)), "preflight_sha256": sha(PREFLIGHT), "maximum_gross_credits": 2, "maximum_new_submissions": 1, "automatic_retry": False, "timeout_rule": "QUERY_EXACT_TASK_AND_AUTHORITATIVE_LEDGER; NO_BLIND_REPOST"}
    atomic_json(AUTH, authorization)
    transaction = {"schema": "qingshan.giggle_audio_submit_transaction.v1", "transaction_key": TX.stem, "state": "INTENT_PERSISTED_NO_PROVIDER_POST_YET", "intent_persisted_at": now(), "episode": "E40", "unit": "U05", "line_id": "E40-DIA-004", "generation_fingerprint_sha256": fingerprint, "request": package["request"], "package": {"path": str(PACKAGE.relative_to(ROOT)), "sha256": sha(PACKAGE)}, "preflight": {"path": str(PREFLIGHT.relative_to(ROOT)), "sha256": sha(PREFLIGHT)}, "authorization": {"path": str(AUTH.relative_to(ROOT)), "sha256": sha(AUTH)}, "provider_post_count": 0, "task_id": None, "maximum_new_submissions": 1, "maximum_gross_credits": 2, "automatic_retry": False, "timeout_rule": authorization["timeout_rule"]}
    atomic_json(TX, transaction)
    print(json.dumps({"status": transaction["state"], "transaction": str(TX.relative_to(ROOT)), "fingerprint": fingerprint, "price": price}, ensure_ascii=False))
    return 0


def audio_metrics(path: Path) -> dict[str, Any]:
    probe = subprocess.run([str(FFPROBE), "-v", "error", "-show_entries", "format=duration:stream=codec_name,sample_rate,channels", "-of", "json", str(path)], capture_output=True, text=True, check=True)
    loud = subprocess.run([str(FFMPEG), "-nostats", "-i", str(path), "-filter_complex", "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True, check=True)
    summary = loud.stderr.rsplit("Summary:", 1)[-1]
    integrated = re.search(r"I:\s+(-?[0-9.]+) LUFS", summary)
    peak = re.search(r"Peak:\s+(-?[0-9.]+) dBFS", summary)
    payload = json.loads(probe.stdout)
    return {"probe": payload, "duration_seconds": float(payload["format"]["duration"]), "integrated_lufs": float(integrated.group(1)) if integrated else None, "true_peak_dbfs": float(peak.group(1)) if peak else None}


def terminal_failure(transaction: dict[str, Any], reason: str, response: dict[str, Any] | None, credit: dict[str, Any] | None) -> int:
    transaction.update({"state": "TERMINAL_FAILED_NO_RETRY", "finished_at": now(), "failure": reason, "provider_response": response, "credit": credit or {"status": "UNKNOWN_REQUIRES_EXACT_TASK_LEDGER_CLASSIFICATION"}, "automatic_retry": False, "maximum_new_submissions": 0})
    atomic_json(TX, transaction)
    memory = {"schema": "qingshan.e40.tts_failure_memory.v1", "status": "ACTIVE_NO_RETRY", "episode": "E40", "unit": "U05", "line_id": "E40-DIA-004", "task_id": transaction.get("task_id"), "generation_fingerprint_sha256": transaction.get("generation_fingerprint_sha256"), "failure": reason, "original_text": TEXT, "voice_id": VOICE_ID, "emotion": EMOTION, "replay_forbidden": True, "required_before_retry": ["authoritative terminal", "authoritative pay/refund classification", "failure memory", "material prompt change"]}
    atomic_json(FAILURE, memory)
    atomic_json(RECEIPT, {"schema": "qingshan.e40.u05.dia004.exact_tts_execution.v1", "status": transaction["state"], "task_id": transaction.get("task_id"), "failure": reason, "transaction": str(TX.relative_to(ROOT)), "transaction_sha256": sha(TX), "failure_memory": str(FAILURE.relative_to(ROOT)), "failure_memory_sha256": sha(FAILURE), "credit": transaction["credit"]})
    print(json.dumps({"status": transaction["state"], "task_id": transaction.get("task_id"), "failure": reason}, ensure_ascii=False))
    return 2


def execute() -> int:
    ensure_giggle_api_key()
    if not TX.is_file():
        raise SystemExit("FAIL_CLOSED_NO_PERSISTED_TRANSACTION")
    transaction = json.loads(TX.read_text(encoding="utf-8"))
    if transaction.get("state") != "INTENT_PERSISTED_NO_PROVIDER_POST_YET" or transaction.get("provider_post_count") != 0 or transaction.get("maximum_new_submissions") != 1:
        raise SystemExit("FAIL_CLOSED_TRANSACTION_ALREADY_CONSUMED_NO_REPOST")
    for key, path in (("package", PACKAGE), ("preflight", PREFLIGHT), ("authorization", AUTH)):
        if sha(path) != transaction[key]["sha256"]:
            raise SystemExit(f"FAIL_CLOSED_{key.upper()}_SHA_MISMATCH")
    if json.loads(PREFLIGHT.read_text(encoding="utf-8")).get("status") != "PASS" or MP3.exists() or WAV.exists():
        raise SystemExit("FAIL_CLOSED_PREFLIGHT_OR_OUTPUT_COLLISION")
    transaction.update({"state": "POST_ATTEMPT_AUTHORIZATION_CONSUMED", "submitted_at": now(), "provider_post_count": 1, "maximum_new_submissions": 0})
    atomic_json(TX, transaction)
    try:
        submitted = submit_speech(TEXT, voice_id=VOICE_ID, emotion=EMOTION, speed=SPEED)
    except Exception as exc:
        transaction.update({"state": "POST_RESULT_UNKNOWN_NO_REPOST_REQUIRES_AUTHORITATIVE_CLASSIFICATION", "failure": f"{type(exc).__name__}:{exc}", "automatic_retry": False})
        atomic_json(TX, transaction)
        print(json.dumps({"status": transaction["state"], "transaction": str(TX.relative_to(ROOT))}, ensure_ascii=False))
        return 3
    task_id = submitted["taskId"]
    transaction.update({"state": "REMOTE_TASK_BOUND_POLLING", "task_id": task_id, "provider_submit_response": submitted, "task_id_bound_at": now()})
    atomic_json(TX, transaction)
    response: dict[str, Any] = submitted
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        time.sleep(2)
        response = query_speech(task_id)
        transaction.update({"last_query_at": now(), "last_remote_status": response.get("status")})
        atomic_json(TX, transaction)
        if response.get("status") in {"completed", "failed"}:
            break
    else:
        return terminal_failure(transaction, "REMOTE_TIMEOUT_BOUND_NO_REPOST", response, credit_for(task_id))
    credit = credit_for(task_id)
    if response.get("status") != "completed":
        return terminal_failure(transaction, f"REMOTE_FAILED:{response.get('error')}", response, credit)
    urls = response.get("_urls") or []
    if not urls:
        return terminal_failure(transaction, "REMOTE_COMPLETED_WITHOUT_AUDIO_URL", response, credit)
    OUT.mkdir(parents=True, exist_ok=True)
    downloaded = _download(urls[0], MP3, overwrite=False)
    subprocess.run([str(FFMPEG), "-y", "-i", str(MP3), "-vn", "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(WAV)], capture_output=True, check=True)
    metrics = audio_metrics(WAV)
    model = WhisperModel(str(WHISPER), device="cpu", compute_type="int8", local_files_only=True)
    segments, _ = model.transcribe(str(WAV), language="zh", vad_filter=True, beam_size=5, initial_prompt="以下是简体中文普通话对白。", hotwords=TEXT)
    transcript = "".join(segment.text.strip() for segment in segments)
    similarity = difflib.SequenceMatcher(None, norm(TEXT), norm(transcript)).ratio()
    rights = transaction.get("provider_submit_response", {}).get("commercialUseMetadata") or response.get("commercialUseMetadata") or {}
    failures = []
    if similarity != 1.0:
        failures.append("ASR_NORMALIZED_EXACT_TEXT_SIMILARITY_NOT_1P0")
    if not 2.5 <= metrics["duration_seconds"] <= 4.2:
        failures.append("DURATION_OUTSIDE_2P5_TO_4P2_SECONDS")
    if metrics["integrated_lufs"] is None or not -22.0 <= metrics["integrated_lufs"] <= -14.0:
        failures.append("LOUDNESS_OUTSIDE_MINUS22_TO_MINUS14_LUFS")
    if metrics["true_peak_dbfs"] is None or metrics["true_peak_dbfs"] > -1.0:
        failures.append("TRUE_PEAK_ABOVE_MINUS1_DBFS")
    if rights.get("present") is not True or rights.get("releaseBlocked") is not False:
        failures.append("COMMERCIAL_USE_METADATA_NOT_RELEASE_CLEAR")
    if credit.get("status") == "INCOMPLETE":
        failures.append("AUTHORITATIVE_CREDIT_CLASSIFICATION_INCOMPLETE")
    qa = {"schema": "qingshan.e40.u05.dia004.exact_audio_qa.v1", "status": "PASS" if not failures else "FAIL", "expected_text": TEXT, "asr_transcript": transcript, "asr_similarity": round(similarity, 4), "speaker": "陈迹", "voice_id": VOICE_ID, "commercial_use_metadata": rights, "task_id": task_id, "mp3_path": str(MP3.relative_to(ROOT)), "mp3_sha256": downloaded["sha256"], "wav_path": str(WAV.relative_to(ROOT)), "wav_sha256": sha(WAV), "audio_metrics": metrics, "credit": credit, "failures": failures, "human_listen_status": "PENDING" if not failures else "NOT_ADMITTED"}
    atomic_json(QA, qa)
    if failures:
        transaction.update({"output_path": str(MP3.relative_to(ROOT)), "output_sha256": downloaded["sha256"], "qa_receipt": str(QA.relative_to(ROOT)), "qa_receipt_sha256": sha(QA)})
        return terminal_failure(transaction, ";".join(failures), response, credit)
    transaction.update({"state": "TERMINAL_COMPLETED_MACHINE_QA_PASS_HUMAN_LISTEN_PENDING_NO_REPLAY", "finished_at": now(), "output_path": str(MP3.relative_to(ROOT)), "output_sha256": downloaded["sha256"], "normalized_wav_path": str(WAV.relative_to(ROOT)), "normalized_wav_sha256": sha(WAV), "qa_receipt": str(QA.relative_to(ROOT)), "qa_receipt_sha256": sha(QA), "credit": credit, "maximum_new_submissions": 0, "automatic_retry": False})
    atomic_json(TX, transaction)
    atomic_json(RECEIPT, {"schema": "qingshan.e40.u05.dia004.exact_tts_execution.v1", "status": transaction["state"], "task_id": task_id, "transaction": str(TX.relative_to(ROOT)), "transaction_sha256": sha(TX), "qa_receipt": str(QA.relative_to(ROOT)), "qa_receipt_sha256": sha(QA), "credit": credit, "maximum_new_submissions": 0})
    print(json.dumps({"status": transaction["state"], "task_id": task_id, "wav_sha256": sha(WAV), "asr": transcript, "credit": credit}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prepare", action="store_true")
    group.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    return prepare() if args.prepare else execute()


if __name__ == "__main__":
    raise SystemExit(main())
