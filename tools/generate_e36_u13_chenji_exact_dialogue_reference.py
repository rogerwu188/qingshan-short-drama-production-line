#!/usr/bin/env python3
"""Generate and verify E36 U13's exact Chenji dialogue reference."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from faster_whisper import WhisperModel
from giggle_api_client import _get
from submit_giggle_task_manifest import ensure_giggle_api_key


ROOT = Path(__file__).resolve().parents[1]
AGENTCUT = ROOT / ".agentcut_env/bin/agentcut"
UNIT_ID = os.environ.get("E36_EXACT_DIALOGUE_UNIT_ID", "U13")
DIA_ID = os.environ.get("E36_EXACT_DIALOGUE_DIA_ID", f"E36-{UNIT_ID}-D01")
TEXT = os.environ.get("E36_EXACT_DIALOGUE_TEXT", "这折痕的样式，对得上王府账房的记号。")
CANONICAL_TEXT = os.environ.get("E36_EXACT_DIALOGUE_CANONICAL_TEXT", TEXT)
CANONICAL_SCRIPT = ROOT / os.environ.get(
    "E36_EXACT_DIALOGUE_CANONICAL_SCRIPT",
    "workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md",
)
CANONICAL_MANIFEST = ROOT / os.environ.get(
    "E36_EXACT_DIALOGUE_CANONICAL_MANIFEST",
    "workflow/claude_writer_agent/scripts/E36_manifest_v2.json",
)
PREFLIGHT_ONLY = os.environ.get("E36_EXACT_DIALOGUE_PREFLIGHT_ONLY", "0") == "1"
EMOTION = os.environ.get(
    "E36_EXACT_DIALOGUE_EMOTION",
    "十七岁陈迹在密室验看空信封折痕后低声确认线索，冷静克制、略带发现真相的笃定，自然中文普通话，不做旁白腔",
)
OUT = ROOT / os.environ.get("E36_EXACT_DIALOGUE_OUT", "working_assets/e36_dialogue_audio_refs_20260730/u13")
QA = ROOT / os.environ.get(
    "E36_EXACT_DIALOGUE_QA",
    "qa/e36_agentcut_20260730/u13_video_runtime/E36-U13-D01_EXACT_DIALOGUE_AUDIO_QA_V1.json",
)
RECEIPT = ROOT / os.environ.get(
    "E36_EXACT_DIALOGUE_RECEIPT",
    "workflow/tasks/E36_U13_CHENJI_EXACT_DIALOGUE_AUDIO_GENERATION_V1.json",
)
VOICE_ID = os.environ.get("E36_EXACT_DIALOGUE_VOICE_ID", "clone_20251022_092746_158444")
SPEED = os.environ.get("E36_EXACT_DIALOGUE_SPEED", "1.00")
MIN_DURATION_SECONDS = float(os.environ.get("E36_EXACT_DIALOGUE_MIN_DURATION_SECONDS", "2.0"))
MAX_DURATION_SECONDS = float(os.environ.get("E36_EXACT_DIALOGUE_MAX_DURATION_SECONDS", "15.0"))
MIN_ASR_SIMILARITY = float(os.environ.get("E36_EXACT_DIALOGUE_MIN_ASR_SIMILARITY", "1.0"))
WHISPER = Path("/Users/rogerwu/.cache/huggingface/hub/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120")
FFMPEG = shutil.which("ffmpeg") or str(next((ROOT / ".agentcut_env").glob("lib/python*/site-packages/agentcut/vendor/darwin-arm64/ffmpeg")))
FFPROBE = shutil.which("ffprobe") or str(Path(FFMPEG).with_name("ffprobe"))
HAN = re.compile(r"[\u3400-\u9fffA-Za-z0-9]")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def norm(value: str) -> str:
    return "".join(HAN.findall(value)).lower()


def write_preflight_result(status: str, failures: list[str], **evidence: object) -> int:
    result = {
        "schema": "qingshan.exact_dialogue_audio_generation.v1",
        "episode": "E36",
        "unit_id": UNIT_ID,
        "status": status,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "spoken_text": TEXT,
        "canonical_text": CANONICAL_TEXT,
        "canonical_script": str(CANONICAL_SCRIPT),
        "canonical_manifest": str(CANONICAL_MANIFEST),
        "failures": failures,
        "credit": {"status": "PREFLIGHT_BLOCKED_ZERO" if failures else "PREFLIGHT_ONLY_ZERO", "charged_credits": 0},
        **evidence,
    }
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "charged_credits": 0}, ensure_ascii=False))
    return 2 if failures else 0


def last_json(value: str) -> dict:
    for line in reversed(value.splitlines()):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def exact_credit(task_id: str) -> dict:
    for attempt in range(1, 8):
        response = _get(
            "/api/v1/payment/credit-statements",
            {"credit_type": "Pay", "page": 1, "page_size": 40, "project_id": task_id},
        )
        rows = [
            row
            for row in ((response.get("data") or {}).get("list") or [])
            if str(row.get("project_id") or "") == task_id and row.get("event_type") == "Pay"
        ]
        if rows:
            total = sum(abs(Decimal(str(row["credit"]))) for row in rows)
            return {
                "status": "KNOWN_EXACT_TASK_STATEMENT",
                "task_id": task_id,
                "charged_credits": int(total),
                "statement_rows": rows,
                "query_attempt": attempt,
            }
        time.sleep(2)
    return {"status": "UNKNOWN_NOT_ESTIMATED", "task_id": task_id, "charged_credits": None, "statement_rows": []}


def main() -> int:
    if not CANONICAL_SCRIPT.is_file() or not CANONICAL_MANIFEST.is_file():
        return write_preflight_result(
            "BLOCKED_ZERO_CHARGE_CANONICAL_AUTHORITY_MISSING",
            ["CANONICAL_SCRIPT_OR_MANIFEST_MISSING"],
            canonical_script_exists=CANONICAL_SCRIPT.is_file(),
            canonical_manifest_exists=CANONICAL_MANIFEST.is_file(),
        )

    try:
        manifest = json.loads(CANONICAL_MANIFEST.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return write_preflight_result(
            "BLOCKED_ZERO_CHARGE_CANONICAL_MANIFEST_INVALID",
            ["CANONICAL_MANIFEST_UNREADABLE_OR_INVALID_JSON"],
            manifest_error=str(exc),
        )

    script_sha256 = sha(CANONICAL_SCRIPT)
    manifest_script_sha256 = str(manifest.get("sha256") or "")
    if manifest.get("episode") != "E36" or script_sha256 != manifest_script_sha256:
        return write_preflight_result(
            "BLOCKED_ZERO_CHARGE_CANONICAL_AUTHORITY_SHA_MISMATCH",
            ["CANONICAL_SCRIPT_SHA_DOES_NOT_MATCH_E36_MANIFEST"],
            manifest_episode=manifest.get("episode"),
            script_sha256=script_sha256,
            manifest_script_sha256=manifest_script_sha256,
        )

    normalized_script = norm(CANONICAL_SCRIPT.read_text(encoding="utf-8"))
    if not norm(CANONICAL_TEXT) or norm(CANONICAL_TEXT) not in normalized_script:
        return write_preflight_result(
            "BLOCKED_ZERO_CHARGE_CANONICAL_TEXT_NOT_IN_SCRIPT",
            ["CANONICAL_TEXT_NOT_FOUND_IN_SHA_VERIFIED_SCRIPT"],
            script_sha256=script_sha256,
            manifest_script_sha256=manifest_script_sha256,
            normalized_canonical_text=norm(CANONICAL_TEXT),
        )

    if norm(TEXT) != norm(CANONICAL_TEXT):
        return write_preflight_result(
            "BLOCKED_ZERO_CHARGE_CANONICAL_TEXT_MISMATCH",
            ["PAID_SOURCE_TEXT_NOT_CANONICAL_EQUIVALENT"],
            script_sha256=script_sha256,
            manifest_script_sha256=manifest_script_sha256,
            normalized_spoken_text=norm(TEXT),
            normalized_canonical_text=norm(CANONICAL_TEXT),
        )

    if PREFLIGHT_ONLY:
        return write_preflight_result(
            "PASS_ZERO_CHARGE_CANONICAL_AUTHORITY_PREFLIGHT_ONLY",
            [],
            script_sha256=script_sha256,
            manifest_script_sha256=manifest_script_sha256,
            normalized_spoken_text=norm(TEXT),
            normalized_canonical_text=norm(CANONICAL_TEXT),
        )

    ensure_giggle_api_key()
    OUT.mkdir(parents=True, exist_ok=True)
    QA.parent.mkdir(parents=True, exist_ok=True)
    mp3 = OUT / f"{DIA_ID}.mp3"
    command = [
        str(AGENTCUT),
        "speech-generate",
        TEXT,
        "--voice-id",
        VOICE_ID,
        "--emotion",
        EMOTION,
        "--speed",
        SPEED,
        "--output-dir",
        str(OUT),
        "--file-name",
        mp3.name,
        "--poll-interval",
        "2",
        "--timeout",
        "300",
        "--overwrite",
    ]
    started = datetime.now(timezone.utc).isoformat()
    completed = subprocess.run(command, capture_output=True, text=True, env=os.environ.copy())
    payload = last_json(completed.stdout or completed.stderr)
    if completed.returncode or payload.get("status") != "completed":
        result = {
            "schema": "qingshan.exact_dialogue_audio_generation.v1",
            "episode": "E36",
            "unit_id": UNIT_ID,
            "status": "FAIL",
            "started_at_utc": started,
            "finished_at_utc": datetime.now(timezone.utc).isoformat(),
            "response": payload,
            "stderr": completed.stderr[-4000:],
            "credit": {"status": "NO_CONFIRMED_SUCCESS_ZERO", "charged_credits": 0},
        }
        RECEIPT.parent.mkdir(parents=True, exist_ok=True)
        RECEIPT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return 2

    mp3 = Path(payload["file"]["path"])
    wav = OUT / f"{DIA_ID}.wav"
    subprocess.run(
        [str(FFMPEG), "-y", "-i", str(mp3), "-vn", "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(wav)],
        check=True,
        capture_output=True,
    )
    probe = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(wav)],
        check=True,
        capture_output=True,
        text=True,
    )
    duration = float(probe.stdout.strip())
    model = WhisperModel(str(WHISPER), device="cpu", compute_type="int8")
    segments, _ = model.transcribe(
        str(wav),
        language="zh",
        vad_filter=True,
        beam_size=5,
        initial_prompt="以下是简体中文普通话对白。",
        hotwords=TEXT,
    )
    transcript = "".join(segment.text.strip() for segment in segments)
    similarity = difflib.SequenceMatcher(None, norm(TEXT), norm(transcript)).ratio()
    status = "PASS" if similarity >= MIN_ASR_SIMILARITY and MIN_DURATION_SECONDS <= duration <= MAX_DURATION_SECONDS else "FAIL"
    credit = exact_credit(payload["taskId"])
    qa = {
        "schema": "qingshan.dialogue_audio_reference_qa.v1",
        "episode": "E36",
        "unit_id": UNIT_ID,
        "dia_id": DIA_ID,
        "status": status,
        "expected_text": TEXT,
        "asr_transcript": transcript,
        "asr_similarity": round(similarity, 4),
        "minimum_asr_similarity": MIN_ASR_SIMILARITY,
        "duration_seconds": duration,
        "duration_bounds_seconds": [MIN_DURATION_SECONDS, MAX_DURATION_SECONDS],
        "wav_path": str(wav),
        "wav_sha256": sha(wav),
        "failures": [] if status == "PASS" else ["ASR_EXACTNESS_OR_CONFIGURED_DURATION_FAIL"],
    }
    QA.write_text(json.dumps(qa, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = {
        "schema": "qingshan.exact_dialogue_audio_generation.v1",
        "episode": "E36",
        "unit_id": UNIT_ID,
        "status": status,
        "started_at_utc": started,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "task_id": payload["taskId"],
        "voice_id": VOICE_ID,
        "spoken_text": TEXT,
        "mp3_path": str(mp3),
        "mp3_sha256": sha(mp3),
        "wav_path": str(wav),
        "wav_sha256": sha(wav),
        "duration_seconds": duration,
        "qa_receipt": str(QA),
        "credit": credit,
    }
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "task_id": payload["taskId"], "charged_credits": credit["charged_credits"], "asr_similarity": round(similarity, 4), "duration_seconds": duration, "wav_path": str(wav)}, ensure_ascii=False))
    return 0 if status == "PASS" and credit["status"] == "KNOWN_EXACT_TASK_STATEMENT" else 2


if __name__ == "__main__":
    raise SystemExit(main())
