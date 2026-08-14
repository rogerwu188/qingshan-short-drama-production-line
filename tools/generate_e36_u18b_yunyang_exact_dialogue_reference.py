#!/usr/bin/env python3
"""Generate and verify the exact second Yunyang line for E36 U18."""

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


ROOT = Path(__file__).resolve().parents[1]
AGENTCUT = ROOT / ".agentcut_env/bin/agentcut"
OUT = ROOT / "working_assets/e36_dialogue_audio_refs_20260730/u18b"
QA = ROOT / "qa/e36_v2_stills_repair_20260729/u18_video_runtime/E36_U18B_YUNYANG_EXACT_DIALOGUE_AUDIO_QA_V1.json"
RECEIPT = ROOT / "workflow/tasks/E36_U18B_YUNYANG_EXACT_DIALOGUE_AUDIO_GENERATION_V1.json"
TEXT = "满门殁尽、无一活口，案子早结了、封了档，凶手都伏了法！"
VOICE_ID = "clone_20250922_190214_400934"
WHISPER = Path("/Users/rogerwu/.cache/huggingface/hub/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120")
FFMPEG = shutil.which("ffmpeg") or str(next((ROOT / ".agentcut_env").glob("lib/python*/site-packages/agentcut/vendor/darwin-arm64/ffmpeg")))
FFPROBE = shutil.which("ffprobe") or str(Path(FFMPEG).with_name("ffprobe"))
HAN = re.compile(r"[\u3400-\u9fffA-Za-z0-9]")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def norm(value: str) -> str:
    return "".join(HAN.findall(value)).lower()


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
        response = _get("/api/v1/payment/credit-statements", {"credit_type": "Pay", "page": 1, "page_size": 40, "project_id": task_id})
        rows = [row for row in ((response.get("data") or {}).get("list") or []) if str(row.get("project_id") or "") == task_id and row.get("event_type") == "Pay"]
        if rows:
            total = sum(abs(Decimal(str(row["credit"]))) for row in rows)
            return {"status": "KNOWN_EXACT_TASK_STATEMENT", "task_id": task_id, "charged_credits": int(total), "statement_rows": rows, "query_attempt": attempt}
        time.sleep(2)
    return {"status": "UNKNOWN_NOT_ESTIMATED", "task_id": task_id, "charged_credits": None, "statement_rows": []}


def main() -> int:
    if not os.environ.get("GIGGLE_API_KEY"):
        raise SystemExit("GIGGLE_API_KEY is required")
    OUT.mkdir(parents=True, exist_ok=True)
    mp3 = OUT / "E36-U18B-D01.mp3"
    command = [
        str(AGENTCUT), "speech-generate", TEXT,
        "--voice-id", VOICE_ID,
        "--emotion", "十七岁云羊在震惊中急促补全案情，气息发紧但每个字清楚，自然中文普通话，不喊麦，不做现代播音腔",
        "--speed", "1.12",
        "--output-dir", str(OUT),
        "--file-name", mp3.name,
        "--poll-interval", "2",
        "--timeout", "300",
        "--overwrite",
    ]
    started = datetime.now(timezone.utc).isoformat()
    completed = subprocess.run(command, capture_output=True, text=True, env=os.environ.copy())
    payload = last_json(completed.stdout or completed.stderr)
    if completed.returncode or payload.get("status") != "completed":
        result = {"schema": "qingshan.exact_dialogue_audio_generation.v1", "status": "FAIL", "started_at_utc": started, "finished_at_utc": datetime.now(timezone.utc).isoformat(), "response": payload, "stderr": completed.stderr[-4000:], "credit": {"status": "NO_CONFIRMED_SUCCESS_ZERO", "charged_credits": 0}}
        RECEIPT.parent.mkdir(parents=True, exist_ok=True)
        RECEIPT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return 2
    mp3 = Path(payload["file"]["path"])
    wav = OUT / "E36-U18B-D01.wav"
    subprocess.run([str(FFMPEG), "-y", "-i", str(mp3), "-vn", "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(wav)], check=True, capture_output=True)
    probe = subprocess.run([str(FFPROBE), "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(wav)], check=True, capture_output=True, text=True)
    duration = float(probe.stdout.strip())
    model = WhisperModel(str(WHISPER), device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(wav), language="zh", vad_filter=True, beam_size=5, initial_prompt="以下是简体中文普通话对白。", hotwords=TEXT)
    transcript = "".join(segment.text.strip() for segment in segments)
    similarity = difflib.SequenceMatcher(None, norm(TEXT), norm(transcript)).ratio()
    status = "PASS" if similarity >= 0.80 and 3.0 <= duration <= 7.0 else "FAIL"
    credit = exact_credit(payload["taskId"])
    qa = {"schema": "qingshan.dialogue_audio_reference_qa.v1", "episode": "E36", "dia_id": "E36-U18B-D01", "status": status, "expected_text": TEXT, "asr_transcript": transcript, "asr_similarity": round(similarity, 4), "duration_seconds": duration, "wav_path": str(wav), "wav_sha256": sha(wav), "failures": [] if status == "PASS" else ["ASR_RECALL_OR_DURATION_FAIL"]}
    QA.parent.mkdir(parents=True, exist_ok=True)
    QA.write_text(json.dumps(qa, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = {"schema": "qingshan.exact_dialogue_audio_generation.v1", "status": status, "started_at_utc": started, "finished_at_utc": datetime.now(timezone.utc).isoformat(), "task_id": payload["taskId"], "voice_id": VOICE_ID, "spoken_text": TEXT, "mp3_path": str(mp3), "mp3_sha256": sha(mp3), "wav_path": str(wav), "wav_sha256": sha(wav), "qa_receipt": str(QA), "credit": credit}
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "task_id": payload["taskId"], "charged_credits": credit["charged_credits"], "asr_similarity": round(similarity, 4), "duration_seconds": duration, "wav_path": str(wav)}, ensure_ascii=False))
    return 0 if status == "PASS" and credit["status"] == "KNOWN_EXACT_TASK_STATEMENT" else 2


if __name__ == "__main__":
    raise SystemExit(main())
