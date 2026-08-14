#!/usr/bin/env python3
"""Generate and verify the two exact Yunyang lines for E36 U08."""

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
OUT = ROOT / "working_assets/e36_dialogue_audio_refs_20260730/u08"
QA_DIR = ROOT / "qa/e36_agentcut_20260730/u08_video_runtime"
RECEIPT = ROOT / "workflow/tasks/E36_U08_YUNYANG_EXACT_DIALOGUE_AUDIO_GENERATION_V1.json"
VOICE_ID = "clone_20250922_190214_400934"
WHISPER = Path("/Users/rogerwu/.cache/huggingface/hub/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120")
FFMPEG = shutil.which("ffmpeg") or str(next((ROOT / ".agentcut_env").glob("lib/python*/site-packages/agentcut/vendor/darwin-arm64/ffmpeg")))
FFPROBE = shutil.which("ffprobe") or str(Path(FFMPEG).with_name("ffprobe"))
HAN = re.compile(r"[\u3400-\u9fffA-Za-z0-9]")
LINES = [
    {
        "dia_id": "E36-U08-D01",
        "text": "换出来了！",
        "emotion": "十七岁云羊边跑边压低声音确认换人成功，短促急切但克制，自然中文普通话，不喊麦，不做现代播音腔",
        "speed": "1.00",
    },
    {
        "dia_id": "E36-U08-D02",
        "text": "走——别回头！",
        "emotion": "十七岁云羊在奔跑中压低声音下撤离命令，坚决急促，破折号为短气口，自然中文普通话，不喊麦，不做现代播音腔",
        "speed": "1.00",
    },
]


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
        response = _get(
            "/api/v1/payment/credit-statements",
            {"credit_type": "Pay", "page": 1, "page_size": 40, "project_id": task_id},
        )
        rows = [
            row
            for row in ((response.get("data") or {}).get("list") or [])
            if str(row.get("project_id") or "") == task_id
            and row.get("event_type") == "Pay"
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
    return {
        "status": "UNKNOWN_NOT_ESTIMATED",
        "task_id": task_id,
        "charged_credits": None,
        "statement_rows": [],
    }


def main() -> int:
    ensure_giggle_api_key()
    OUT.mkdir(parents=True, exist_ok=True)
    QA_DIR.mkdir(parents=True, exist_ok=True)
    model = WhisperModel(str(WHISPER), device="cpu", compute_type="int8")
    results = []
    overall = "PASS"
    for row in LINES:
        dia_id = row["dia_id"]
        text = row["text"]
        mp3 = OUT / f"{dia_id}.mp3"
        command = [
            str(AGENTCUT),
            "speech-generate",
            text,
            "--voice-id",
            VOICE_ID,
            "--emotion",
            row["emotion"],
            "--speed",
            row["speed"],
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
        completed = subprocess.run(
            command, capture_output=True, text=True, env=os.environ.copy()
        )
        payload = last_json(completed.stdout or completed.stderr)
        if completed.returncode or payload.get("status") != "completed":
            results.append(
                {
                    "dia_id": dia_id,
                    "status": "FAIL",
                    "started_at_utc": started,
                    "finished_at_utc": datetime.now(timezone.utc).isoformat(),
                    "response": payload,
                    "stderr": completed.stderr[-4000:],
                    "credit": {
                        "status": "NO_CONFIRMED_SUCCESS_ZERO",
                        "charged_credits": 0,
                    },
                }
            )
            overall = "FAIL"
            break
        mp3 = Path(payload["file"]["path"])
        wav = OUT / f"{dia_id}.wav"
        subprocess.run(
            [
                str(FFMPEG),
                "-y",
                "-i",
                str(mp3),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "48000",
                "-c:a",
                "pcm_s16le",
                str(wav),
            ],
            check=True,
            capture_output=True,
        )
        probe = subprocess.run(
            [
                str(FFPROBE),
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(wav),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        duration = float(probe.stdout.strip())
        segments, _ = model.transcribe(
            str(wav),
            language="zh",
            vad_filter=True,
            beam_size=5,
            initial_prompt="以下是简体中文普通话对白。",
            hotwords=text,
        )
        transcript = "".join(segment.text.strip() for segment in segments)
        similarity = difflib.SequenceMatcher(None, norm(text), norm(transcript)).ratio()
        status = "PASS" if similarity >= 0.80 and 0.25 <= duration <= 3.0 else "FAIL"
        credit = exact_credit(payload["taskId"])
        qa = {
            "schema": "qingshan.dialogue_audio_reference_qa.v1",
            "episode": "E36",
            "dia_id": dia_id,
            "status": status,
            "expected_text": text,
            "asr_transcript": transcript,
            "asr_similarity": round(similarity, 4),
            "duration_seconds": duration,
            "wav_path": str(wav),
            "wav_sha256": sha(wav),
            "failures": [] if status == "PASS" else ["ASR_RECALL_OR_DURATION_FAIL"],
        }
        qa_path = QA_DIR / f"{dia_id}_EXACT_DIALOGUE_AUDIO_QA_V1.json"
        qa_path.write_text(
            json.dumps(qa, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        results.append(
            {
                "dia_id": dia_id,
                "status": status,
                "started_at_utc": started,
                "finished_at_utc": datetime.now(timezone.utc).isoformat(),
                "task_id": payload["taskId"],
                "voice_id": VOICE_ID,
                "spoken_text": text,
                "mp3_path": str(mp3),
                "mp3_sha256": sha(mp3),
                "wav_path": str(wav),
                "wav_sha256": sha(wav),
                "duration_seconds": duration,
                "qa_receipt": str(qa_path),
                "credit": credit,
            }
        )
        if status != "PASS" or credit["status"] != "KNOWN_EXACT_TASK_STATEMENT":
            overall = "FAIL"
            break
    receipt = {
        "schema": "qingshan.exact_dialogue_audio_generation_batch.v1",
        "episode": "E36",
        "unit_id": "U08",
        "status": overall,
        "results": results,
        "actual_charged_credits_known_total": sum(
            int((result.get("credit") or {}).get("charged_credits") or 0)
            for result in results
        ),
    }
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": overall,
                "charged_credits": receipt["actual_charged_credits_known_total"],
                "results": [
                    {
                        "dia_id": result["dia_id"],
                        "task_id": result.get("task_id"),
                        "duration_seconds": result.get("duration_seconds"),
                        "wav_path": result.get("wav_path"),
                    }
                    for result in results
                ],
            },
            ensure_ascii=False,
        )
    )
    return 0 if overall == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
