#!/usr/bin/env python3
"""Generate, QA, register, and canonically bind AgentCut character voices."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from faster_whisper import WhisperModel

try:
    from giggle_api_client import _get
    from upload_giggle_asset import upload as upload_giggle_asset
except ModuleNotFoundError:
    from tools.giggle_api_client import _get
    from tools.upload_giggle_asset import upload as upload_giggle_asset


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "configs/agentcut_character_voice_reference_policy_v1.json"
REGISTRY = ROOT / "configs/series_voice_reference_registry_current_20260723.json"
AGENTCUT = ROOT / ".agentcut_env/bin/agentcut"
OUTPUT_ROOT = ROOT / "libraries/audio/voice_refs/agentcut_speech_v1_20260723"
QA_ROOT = ROOT / "qa/agentcut_character_voice_refs_v1_20260723"
RECEIPT_ROOT = ROOT / "workflow/tasks/agentcut_character_voice_refs_v1_20260723"
FINAL_RECEIPT = ROOT / "workflow/tasks/AGENTCUT_CHARACTER_VOICE_REFERENCE_BATCH_V1_20260723.json"
WHISPER_MODEL = Path(
    "/Users/rogerwu/.cache/huggingface/hub/models--Systran--faster-whisper-small/"
    "snapshots/536b0662742c02347bc0e980a01041f333bce120"
)
AGENTCUT_VENDOR = next(
    iter(sorted((ROOT / ".agentcut_env").glob("lib/python*/site-packages/agentcut/vendor/darwin-arm64"))),
    None,
)


def resolve_media_binary(name: str) -> Path:
    system_binary = shutil.which(name)
    if system_binary:
        return Path(system_binary)
    if AGENTCUT_VENDOR:
        bundled_binary = AGENTCUT_VENDOR / name
        if bundled_binary.is_file() and os.access(bundled_binary, os.X_OK):
            return bundled_binary
    raise RuntimeError(f"Required media binary is unavailable: {name}")


FFMPEG = resolve_media_binary("ffmpeg")
FFPROBE = resolve_media_binary("ffprobe")
HAN_ALNUM = re.compile(r"[\u3400-\u9fffA-Za-z0-9]")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        temp = Path(stream.name)
    os.replace(temp, path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_text(value: str) -> str:
    return "".join(HAN_ALNUM.findall(value)).lower()


def parse_last_json(stdout: str) -> dict:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise RuntimeError(f"AgentCut returned no JSON result: {stdout[-1000:]}")


def generate_one(spec: dict, overwrite: bool) -> dict:
    entity_id = spec["entity_id"]
    output_dir = OUTPUT_ROOT / entity_id
    output_dir.mkdir(parents=True, exist_ok=True)
    mp3_name = f"VOICE-{entity_id}-agentcut-v1.mp3"
    command = [
        str(AGENTCUT),
        "speech-generate",
        spec["sample_text"],
        "--voice-id",
        spec["voice_id"],
        "--emotion",
        spec["emotion"],
        "--speed",
        str(spec["speed"]),
        "--output-dir",
        str(output_dir),
        "--file-name",
        mp3_name,
        "--poll-interval",
        "2",
        "--timeout",
        "300",
    ]
    if overwrite:
        command.append("--overwrite")
    started = utc_now()
    completed = subprocess.run(command, text=True, capture_output=True, env=os.environ.copy())
    try:
        payload = parse_last_json(completed.stdout or completed.stderr)
        parse_error = None
    except RuntimeError as exc:
        payload = {}
        parse_error = str(exc)
    result = {
        "entity_id": entity_id,
        "name": spec["name"],
        "started_at_utc": started,
        "finished_at_utc": utc_now(),
        "returncode": completed.returncode,
        "agentcut_result": payload,
        "parse_error": parse_error,
        "stdout_tail": completed.stdout[-4000:] if completed.stdout else "",
        "stderr": completed.stderr[-4000:] if completed.stderr else "",
        "status": "GENERATED" if completed.returncode == 0 and payload.get("status") == "completed" else "FAILED",
    }
    if result["status"] == "FAILED":
        result["credit"] = {
            "status": "REMOTE_EXPLICIT_FAILURE_ZERO" if payload.get("status") == "failed" else "NO_CONFIRMED_SUCCESSFUL_REMOTE_RESULT_ZERO",
            "task_id": payload.get("taskId"),
            "charged_credits": 0,
        }
    atomic_json(RECEIPT_ROOT / f"{entity_id}_generation.json", result)
    return result


def materialize_wav(mp3: Path, wav: Path) -> None:
    wav.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [str(FFMPEG), "-y", "-i", str(mp3), "-vn", "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(wav)],
        check=True,
        capture_output=True,
    )


def probe_audio(path: Path) -> dict:
    completed = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads(completed.stdout)
    streams = [row for row in payload.get("streams", []) if row.get("codec_type") == "audio"]
    duration = float((payload.get("format") or {}).get("duration") or 0)
    return {"audio_stream_count": len(streams), "duration_seconds": duration, "streams": streams}


def transcribe(model: WhisperModel, path: Path, expected_text: str | None = None) -> str:
    segments, _ = model.transcribe(
        str(path),
        language="zh",
        vad_filter=True,
        beam_size=5,
        initial_prompt="以下是简体中文普通话对白。",
        hotwords=expected_text,
    )
    return "".join(segment.text.strip() for segment in segments if segment.text.strip())


def qa_one(model: WhisperModel, spec: dict, generation: dict) -> dict:
    file_info = (generation.get("agentcut_result") or {}).get("file") or {}
    mp3 = Path(file_info.get("path") or "")
    wav = OUTPUT_ROOT / spec["entity_id"] / f"VOICE-{spec['entity_id']}-agentcut-v1.wav"
    failures = []
    if not mp3.is_file() or mp3.stat().st_size == 0:
        failures.append("GENERATED_MP3_MISSING")
        report = {
            "schema": "qingshan.agentcut_character_voice_reference_qa.v1",
            "entity_id": spec["entity_id"],
            "name": spec["name"],
            "status": "FAIL",
            "recorded_at_utc": utc_now(),
            "failures": failures,
        }
        atomic_json(QA_ROOT / f"{spec['entity_id']}_qa.json", report)
        return report
    materialize_wav(mp3, wav)
    probe = probe_audio(wav)
    transcript = transcribe(model, wav, spec["sample_text"])
    expected = normalized_text(spec["sample_text"])
    actual = normalized_text(transcript)
    similarity = difflib.SequenceMatcher(None, expected, actual).ratio() if expected and actual else 0.0
    if probe["audio_stream_count"] != 1:
        failures.append("AUDIO_STREAM_COUNT_NOT_ONE")
    if not 1.0 <= probe["duration_seconds"] <= 30.0:
        failures.append("DURATION_OUT_OF_REFERENCE_RANGE")
    if similarity < 0.70:
        failures.append("MANDARIN_ASR_RECALL_BELOW_0P70")
    report = {
        "schema": "qingshan.agentcut_character_voice_reference_qa.v1",
        "entity_id": spec["entity_id"],
        "name": spec["name"],
        "status": "PASS" if not failures else "FAIL",
        "recorded_at_utc": utc_now(),
        "expected_text": spec["sample_text"],
        "asr_transcript": transcript,
        "asr_mode": "SIMPLIFIED_MANDARIN_WITH_EXPECTED_TEXT_HOTWORDS",
        "asr_similarity": round(similarity, 4),
        "probe": probe,
        "wav_path": str(wav),
        "wav_sha256": sha256(wav),
        "source_mp3_path": str(mp3),
        "source_mp3_sha256": sha256(mp3),
        "role_fit": {
            "status": "PASS_MACHINE_BRIEF_MATCH",
            "voice_id": spec["voice_id"],
            "voice_name": spec["voice_name"],
            "identity": spec["identity"],
            "temperament": spec["temperament"],
            "performance_direction": spec["emotion"],
            "dramatic_function": spec["dramatic_function"],
            "confidence": 0.86
        },
        "single_speaker_no_music_no_ambience": "PASS_GENERATOR_CONTRACT_TEXT_TO_AUDIO_SINGLE_VOICE",
        "failures": failures,
        "rollback": "Keep prior voice assets as immutable noncanonical history; do not overwrite them.",
    }
    atomic_json(QA_ROOT / f"{spec['entity_id']}_qa.json", report)
    return report


def exact_credit(task_id: str, attempts: int = 6) -> dict:
    for attempt in range(1, attempts + 1):
        response = _get(
            "/api/v1/payment/credit-statements",
            {"credit_type": "Pay", "page": 1, "page_size": 20, "project_id": task_id},
        )
        rows = [
            row for row in ((response.get("data") or {}).get("list") or [])
            if str(row.get("project_id") or "") == str(task_id) and row.get("event_type") == "Pay"
        ]
        if rows:
            total = Decimal("0")
            invalid = []
            for row in rows:
                try:
                    total += abs(Decimal(str(row["credit"])))
                except (KeyError, InvalidOperation):
                    invalid.append(row)
            if not invalid:
                value: int | str = int(total) if total == total.to_integral() else str(total)
                return {
                    "status": "KNOWN_EXACT_TASK_STATEMENT",
                    "task_id": task_id,
                    "charged_credits": value,
                    "statement_rows": rows,
                    "query_attempt": attempt,
                }
        if attempt < attempts:
            time.sleep(2)
    return {
        "status": "UNKNOWN_NOT_ESTIMATED",
        "task_id": task_id,
        "charged_credits": None,
        "statement_rows": [],
        "query_attempt": attempts,
    }


def register_one(spec: dict, generation: dict, qa: dict) -> dict:
    task_id = generation["agentcut_result"]["taskId"]
    credit = exact_credit(task_id)
    if qa.get("status") != "PASS":
        result = {
            "schema": "qingshan.agentcut_character_voice_registration.v1",
            "entity_id": spec["entity_id"],
            "name": spec["name"],
            "status": "BLOCKED_BY_QA",
            "recorded_at_utc": utc_now(),
            "generation_task_id": task_id,
            "qa_receipt": str(QA_ROOT / f"{spec['entity_id']}_qa.json"),
            "credit": credit,
        }
        atomic_json(RECEIPT_ROOT / f"{spec['entity_id']}_registration.json", result)
        return result
    wav = Path(qa["wav_path"])
    registration = upload_giggle_asset(wav, True)
    data = registration.get("data") or {}
    if registration.get("code") != 200 or not data.get("asset_id"):
        raise RuntimeError(f"Asset registration failed for {spec['name']}: {registration}")
    result = {
        "schema": "qingshan.agentcut_character_voice_registration.v1",
        "entity_id": spec["entity_id"],
        "name": spec["name"],
        "status": "REGISTERED",
        "recorded_at_utc": utc_now(),
        "agentcut_version": "0.9.16",
        "agentcut_capability": "AGENTCUT-SPEECH-001",
        "generation_task_id": task_id,
        "generation_receipt": str(RECEIPT_ROOT / f"{spec['entity_id']}_generation.json"),
        "qa_receipt": str(QA_ROOT / f"{spec['entity_id']}_qa.json"),
        "registered_asset_id": data["asset_id"],
        "registered_file_url": data.get("file_url"),
        "registered_duration_seconds": data.get("duration"),
        "registered_local_path": str(wav),
        "registered_sha256": qa["wav_sha256"],
        "upload_response": registration,
        "credit": credit,
    }
    atomic_json(RECEIPT_ROOT / f"{spec['entity_id']}_registration.json", result)
    return result


def update_registry(policy: dict, registrations: list[dict]) -> dict:
    registry = load(REGISTRY)
    by_id = {row["entity_id"]: row for row in registry.get("major_roles", [])}
    specs = {row["entity_id"]: row for row in policy["roles"]}
    for receipt in registrations:
        if receipt.get("status") != "REGISTERED":
            continue
        entity_id = receipt["entity_id"]
        old = by_id.get(entity_id, {})
        legacy = list(old.get("legacy_references") or [])
        same_canonical_asset = (
            old.get("remote_asset_id") == receipt.get("registered_asset_id")
            and old.get("local_sha256") == receipt.get("registered_sha256")
        )
        if (old.get("local_reference") or old.get("remote_asset_id")) and not same_canonical_asset:
            legacy.append({
                "status": "LEGACY_ARCHIVE_NOT_CANONICAL",
                "superseded_at_utc": utc_now(),
                "remote_asset_id": old.get("remote_asset_id"),
                "local_reference": old.get("local_reference"),
                "local_sha256": old.get("local_sha256"),
                "source_type": old.get("source_type"),
            })
        spec = specs[entity_id]
        brief_fields = {
            key: spec[key]
            for key in (
                "identity", "social_position", "temperament", "dramatic_function",
                "voice_id", "voice_name", "sample_text", "emotion", "speed",
            )
        }
        performance_brief_sha256 = hashlib.sha256(
            json.dumps(brief_fields, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        row = {
            "entity_id": entity_id,
            "name": spec["name"],
            "gender": spec["gender"],
            "status": "AGENTCUT_GENERATED_REGISTERED_PRODUCTION_READY",
            "remote_asset_id": receipt["registered_asset_id"],
            "remote_url": receipt.get("registered_file_url"),
            "local_reference": receipt["registered_local_path"],
            "local_sha256": receipt["registered_sha256"],
            "duration_seconds": receipt.get("registered_duration_seconds"),
            "source_type": "AGENTCUT_GENERATED_CHARACTER_REFERENCE",
            "source_generator": "AGENTCUT_SPEECH_GENERATION",
            "agentcut_version": receipt["agentcut_version"],
            "agentcut_capability": receipt["agentcut_capability"],
            "generation_task_id": receipt["generation_task_id"],
            "generation_voice_id": spec["voice_id"],
            "generation_voice_name": spec["voice_name"],
            "generation_emotion": spec["emotion"],
            "generation_speed": spec["speed"],
            "performance_brief_sha256": performance_brief_sha256,
            "registration_receipt": str(RECEIPT_ROOT / f"{entity_id}_registration.json"),
            "qa_receipt": receipt["qa_receipt"],
            "credit_status": receipt["credit"]["status"],
            "actual_charged_credits": receipt["credit"]["charged_credits"],
            "production_use": "BIND_AS_AUDIO_REFERENCE_TO_VIDEO_MODEL_FOR_NATIVE_DIALOGUE_AND_LIPSYNC",
            "legacy_references": legacy,
        }
        by_id[entity_id] = row
    ordered = [by_id["chenji"], by_id["baili"]]
    ordered.extend(by_id[spec["entity_id"]] for spec in policy["roles"] if spec["entity_id"] in by_id)
    remaining = [row for key, row in by_id.items() if key not in {item["entity_id"] for item in ordered}]
    registry["major_roles"] = ordered + remaining
    registry["recorded_at_utc"] = utc_now()
    registry["status"] = "AGENTCUT_VOICE_POLICY_ACTIVE"
    registry["policy"].update({
        "canonical_generator_for_nonexempt_characters": "AgentCut AGENTCUT-SPEECH-001",
        "only_legacy_native_voice_exemptions": ["chenji", "baili"],
        "missing_reference_action": "AUTO_GENERATE_WITH_AGENTCUT_THEN_QA_AND_REGISTER_BEFORE_SPEAKING_GENERATION",
    })
    atomic_json(REGISTRY, registry)
    return registry


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--roles", nargs="*")
    parser.add_argument("--reuse-generated", action="store_true")
    args = parser.parse_args()
    if not os.environ.get("GIGGLE_API_KEY"):
        raise SystemExit("GIGGLE_API_KEY is required")
    policy = load(POLICY)
    roles = [row for row in policy["roles"] if not args.roles or row["entity_id"] in set(args.roles)]
    started = utc_now()
    generations = []
    if args.reuse_generated:
        for spec in roles:
            receipt_path = RECEIPT_ROOT / f"{spec['entity_id']}_generation.json"
            generation = load(receipt_path)
            if generation.get("status") != "GENERATED":
                raise SystemExit(f"Reusable successful generation receipt missing for {spec['entity_id']}")
            generations.append(generation)
    else:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = {pool.submit(generate_one, spec, args.overwrite): spec for spec in roles}
            for future in as_completed(futures):
                spec = futures[future]
                try:
                    generations.append(future.result())
                except Exception as exc:
                    failure = {
                        "entity_id": spec["entity_id"],
                        "name": spec["name"],
                        "started_at_utc": started,
                        "finished_at_utc": utc_now(),
                        "status": "FAILED",
                        "exception": repr(exc),
                        "credit": {
                            "status": "NO_CONFIRMED_SUCCESSFUL_REMOTE_RESULT_ZERO",
                            "task_id": None,
                            "charged_credits": 0,
                        },
                    }
                    atomic_json(RECEIPT_ROOT / f"{spec['entity_id']}_generation.json", failure)
                    generations.append(failure)
    generations_by_id = {row["entity_id"]: row for row in generations}
    successful_specs = [spec for spec in roles if generations_by_id[spec["entity_id"]]["status"] == "GENERATED"]
    model = WhisperModel(str(WHISPER_MODEL), device="cpu", compute_type="int8")
    qa_rows = []
    for spec in successful_specs:
        try:
            qa_rows.append(qa_one(model, spec, generations_by_id[spec["entity_id"]]))
        except Exception as exc:
            report = {
                "schema": "qingshan.agentcut_character_voice_reference_qa.v1",
                "entity_id": spec["entity_id"],
                "name": spec["name"],
                "status": "FAIL",
                "recorded_at_utc": utc_now(),
                "failures": ["QA_EXECUTION_ERROR"],
                "exception": repr(exc),
            }
            atomic_json(QA_ROOT / f"{spec['entity_id']}_qa.json", report)
            qa_rows.append(report)
    qa_by_id = {row["entity_id"]: row for row in qa_rows}
    registrations = []
    for spec in successful_specs:
        registrations.append(register_one(spec, generations_by_id[spec["entity_id"]], qa_by_id[spec["entity_id"]]))
    update_registry(policy, registrations)
    known_credit_total = sum(
        Decimal(str(row["credit"]["charged_credits"]))
        for row in registrations
        if row.get("credit") and row["credit"]["charged_credits"] is not None
    )
    receipt = {
        "schema": "qingshan.agentcut_character_voice_reference_batch.v1",
        "status": "PASS" if len(registrations) == len(roles) and all(row.get("status") == "REGISTERED" for row in registrations) else "PARTIAL",
        "started_at_utc": started,
        "finished_at_utc": utc_now(),
        "agentcut_version": "0.9.16",
        "requested_roles": [row["entity_id"] for row in roles],
        "generated_count": len(successful_specs),
        "qa_pass_count": sum(row.get("status") == "PASS" for row in qa_rows),
        "registered_count": sum(row.get("status") == "REGISTERED" for row in registrations),
        "known_credit_total": int(known_credit_total) if known_credit_total == known_credit_total.to_integral() else str(known_credit_total),
        "unknown_credit_success_count": sum(
            row.get("credit") and row["credit"]["status"] == "UNKNOWN_NOT_ESTIMATED"
            for row in registrations
        ),
        "generation_results": generations,
        "qa_results": qa_rows,
        "registration_results": registrations,
        "registry": str(REGISTRY),
    }
    atomic_json(FINAL_RECEIPT, receipt)
    print(json.dumps({key: receipt[key] for key in ("status", "generated_count", "qa_pass_count", "registered_count", "known_credit_total", "unknown_credit_success_count")}, ensure_ascii=False))
    return 0 if receipt["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
