#!/usr/bin/env python3
"""Generate, verify and register exact expressive E38 dialogue audio assets."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

from faster_whisper import WhisperModel
from giggle_api_client import _get
from upload_giggle_asset import upload as upload_giggle_asset


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e38_claude_writer_v2_3f08265c_20260804"
PROFILES = BASE / "E38_EXPRESSIVE_VOICE_PROFILES_V1.json"
OUT = ROOT / "working_assets/e38_v6_exact_expressive_audio_20260805"
QA = ROOT / "qa/e38_v6_exact_expressive_audio_20260805"
RECEIPT = ROOT / "workflow/tasks/E38_V6_EXACT_EXPRESSIVE_AUDIO_ASSETS_20260805.json"
AGENTCUT = ROOT / ".agentcut_env/bin/agentcut"
WHISPER = Path("/Users/rogerwu/.cache/huggingface/hub/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120")
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
HAN = re.compile(r"[\u3400-\u9fffA-Za-z0-9]")
TARGET_UNITS = {"U01", "U02", "U03", "U05", "U09", "U10", "U11"}
VOICE_IDS = {
    "陈迹": "clone_20251022_092746_158444",
    "皎兔": "clone_20251022_111637_754851",
    "云羊": "clone_20250922_190214_400934",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
        response = _get("/api/v1/payment/credit-statements", {"page": 1, "page_size": 40, "project_id": task_id})
        rows = [row for row in ((response.get("data") or {}).get("list") or []) if str(row.get("project_id") or "") == task_id and row.get("event_type") in {"Pay", "Refund"}]
        if rows:
            pay = sum(abs(Decimal(str(row["credit"]))) for row in rows if row.get("event_type") == "Pay")
            refund = sum(abs(Decimal(str(row["credit"]))) for row in rows if row.get("event_type") == "Refund")
            return {"status": "KNOWN_EXACT_TASK_STATEMENT", "task_id": task_id, "pay": int(pay), "refund": int(refund), "net": int(pay - refund), "statement_rows": rows, "query_attempt": attempt}
        time.sleep(2)
    return {"status": "UNKNOWN_NOT_ESTIMATED", "task_id": task_id, "pay": None, "refund": None, "net": None, "statement_rows": []}


def generate(index: int, row: dict) -> dict:
    line_id = f"{row['unit_id']}-D{index:02d}"
    unit_dir = OUT / row["unit_id"]
    unit_dir.mkdir(parents=True, exist_ok=True)
    mp3 = unit_dir / f"E38-{line_id}.mp3"
    wav = unit_dir / f"E38-{line_id}.wav"
    emotion = (
        f"中国古装悬疑短剧人物。心理：{row['psychological_state']}。情绪：{row['emotion']}，"
        f"强度{row['emotion_intensity']}级。语速：{row['pace']}。停连：{row['pause_map']}。"
        f"重音：{'、'.join(row['emphasis_words'])}。音量：{row['volume_arc']}。气息：{row['breath_pattern']}。"
        f"句内变化：{row['delivery_transition']}。自然普通话，不用播音腔，不添加、不重复、不省略任何字。"
    )
    command = [
        str(AGENTCUT), "speech-generate", row["text"],
        "--voice-id", VOICE_IDS[row["speaker"]],
        "--emotion", emotion,
        "--speed", "1.0",
        "--output-dir", str(unit_dir),
        "--file-name", mp3.name,
        "--poll-interval", "2",
        "--timeout", "300",
        "--overwrite",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, env=os.environ.copy())
    payload = last_json(completed.stdout or completed.stderr)
    if completed.returncode or payload.get("status") != "completed":
        return {"line_id": line_id, "unit_id": row["unit_id"], "status": "FAIL_GENERATION", "response": payload, "stderr": completed.stderr[-2000:]}
    source = Path(payload["file"]["path"])
    subprocess.run([FFMPEG, "-y", "-v", "error", "-i", str(source), "-vn", "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(wav)], check=True)
    model = WhisperModel(str(WHISPER), device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(wav), language="zh", vad_filter=True, beam_size=5, initial_prompt="以下是简体中文普通话对白。", hotwords=row["text"])
    transcript = "".join(segment.text.strip() for segment in segments)
    similarity = difflib.SequenceMatcher(None, norm(row["text"]), norm(transcript)).ratio()
    credit = exact_credit(payload["taskId"])
    if similarity < 0.80:
        return {"line_id": line_id, "unit_id": row["unit_id"], "speaker": row["speaker"], "text": row["text"], "status": "FAIL_ASR", "task_id": payload["taskId"], "transcript": transcript, "similarity": round(similarity, 4), "wav_path": str(wav), "wav_sha256": sha(wav), "credit": credit}
    registration = upload_giggle_asset(wav, True)
    asset_id = (registration.get("data") or {}).get("asset_id")
    if registration.get("code") != 200 or not asset_id:
        return {"line_id": line_id, "unit_id": row["unit_id"], "status": "FAIL_ASSET_REGISTRATION", "task_id": payload["taskId"], "registration": registration, "credit": credit}
    result = {
        "line_id": line_id,
        "unit_id": row["unit_id"],
        "speaker": row["speaker"],
        "text": row["text"],
        "status": "PASS_REGISTERED",
        "task_id": payload["taskId"],
        "voice_id": VOICE_IDS[row["speaker"]],
        "emotion_contract": emotion,
        "transcript": transcript,
        "similarity": round(similarity, 4),
        "mp3_path": str(source),
        "mp3_sha256": sha(source),
        "wav_path": str(wav),
        "wav_sha256": sha(wav),
        "registered_asset_id": asset_id,
        "credit": credit,
    }
    (QA / f"{line_id}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    if not os.environ.get("GIGGLE_API_KEY"):
        raise SystemExit("GIGGLE_API_KEY is required")
    QA.mkdir(parents=True, exist_ok=True)
    profiles = [row for row in json.loads(PROFILES.read_text(encoding="utf-8"))["profiles"] if row["unit_id"] in TARGET_UNITS]
    indexed = []
    counts: dict[str, int] = {}
    for row in profiles:
        counts[row["unit_id"]] = counts.get(row["unit_id"], 0) + 1
        indexed.append((counts[row["unit_id"]], row))
    results = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(generate, index, row): (index, row) for index, row in indexed}
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda item: item["line_id"])
    credits = [item.get("credit") or {} for item in results]
    payload = {
        "schema": "qingshan.e38_exact_expressive_audio_assets.v1",
        "episode": "E38",
        "recorded_at": now(),
        "status": "PASS" if results and all(item["status"] == "PASS_REGISTERED" for item in results) else "PARTIAL_OR_FAILED",
        "profile_sha256": sha(PROFILES),
        "results": results,
        "credits": {
            "pay": sum(item.get("pay") or 0 for item in credits),
            "refund": sum(item.get("refund") or 0 for item in credits),
            "net": sum(item.get("net") or 0 for item in credits),
        },
    }
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "passed": sum(item["status"] == "PASS_REGISTERED" for item in results), "total": len(results), "credits": payload["credits"], "receipt": str(RECEIPT)}, ensure_ascii=False))
    return 0 if payload["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
