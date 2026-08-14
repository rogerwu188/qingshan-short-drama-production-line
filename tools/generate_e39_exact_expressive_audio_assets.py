#!/usr/bin/env python3
"""Generate and register exact-line expressive audio for E39 independent units."""

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
BASE = ROOT / "workflow/claude_writer_agent/production/e39_claude_writer_v3_2726b69b_20260805"
INPUT = BASE / "E39_DIALOGUE_EXPRESSIVE_INPUT_V1.json"
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E39剧本_ClaudeWriter_v3.md"
OUT = ROOT / "working_assets/e39_video_v1/exact_dialogue_audio_r2"
QA = ROOT / "qa/e39_video_v1/exact_dialogue_audio_r2"
RECEIPT = ROOT / "workflow/tasks/E39_INDEPENDENT_R2_EXACT_DIALOGUE_AUDIO_ASSETS_20260806.json"
AGENTCUT = ROOT / ".agentcut_env/bin/agentcut"
WHISPER = Path("/Users/rogerwu/.cache/huggingface/hub/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120")
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
HAN = re.compile(r"[\u3400-\u9fffA-Za-z0-9]")
TARGET_UNITS = {"U01", "U02", "U03", "U04", "U05", "U10", "U11", "U12", "U13", "U14", "U15"}
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


def emotion_contract(row: dict) -> str:
    delivery = row["delivery"]
    return (
        f"中国古装悬疑短剧人物。表演意图：{delivery['acting_verb']}。潜台词：{delivery['subtext']}。"
        f"心理：{delivery['psychological_state']}。语气：{delivery['tone']}，强度{delivery['emotion_intensity']}级。"
        f"语速：{delivery['pace']}。停连：{delivery['pause_map']}。重音：{'、'.join(delivery['stress'])}。"
        f"音量变化：{delivery['volume_arc']}。气息：{delivery['breath']}。"
        "自然普通话，像人物在现场真实说话，不用播音腔；逐字准确，不添加、不重复、不省略。"
    )


def generate(row: dict, line_index: int) -> dict:
    line_id = f"{row['unit']}-D{line_index:02d}"
    unit_dir = OUT / row["unit"]
    unit_dir.mkdir(parents=True, exist_ok=True)
    mp3 = unit_dir / f"E39-{line_id}.mp3"
    wav = unit_dir / f"E39-{line_id}.wav"
    command = [
        str(AGENTCUT), "speech-generate", row["text"],
        "--voice-id", VOICE_IDS[row["speaker"]],
        "--emotion", emotion_contract(row),
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
        return {"line_id": line_id, "source_line_id": row["id"], "unit_id": row["unit"], "status": "FAIL_GENERATION", "response": payload, "stderr": completed.stderr[-2000:]}
    source = Path(payload["file"]["path"])
    subprocess.run([FFMPEG, "-y", "-v", "error", "-i", str(source), "-vn", "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(wav)], check=True)
    return {
        "line_id": line_id,
        "source_line_id": row["id"],
        "unit_id": row["unit"],
        "speaker": row["speaker"],
        "text": row["text"],
        "status": "GENERATED_PENDING_QA",
        "task_id": payload["taskId"],
        "voice_id": VOICE_IDS[row["speaker"]],
        "emotion_contract": emotion_contract(row),
        "mp3_path": str(source),
        "mp3_sha256": sha(source),
        "wav_path": str(wav),
        "wav_sha256": sha(wav),
    }


def verify_and_register(item: dict, model: WhisperModel) -> dict:
    if item["status"] != "GENERATED_PENDING_QA":
        return item
    segments, _ = model.transcribe(item["wav_path"], language="zh", vad_filter=True, beam_size=5, initial_prompt="以下是简体中文普通话对白。", hotwords=item["text"])
    transcript = "".join(segment.text.strip() for segment in segments)
    similarity = difflib.SequenceMatcher(None, norm(item["text"]), norm(transcript)).ratio()
    item["transcript"] = transcript
    item["similarity"] = round(similarity, 4)
    item["credit"] = exact_credit(item["task_id"])
    if similarity < 0.80:
        item["status"] = "FAIL_ASR"
        return item
    registration = upload_giggle_asset(Path(item["wav_path"]), True)
    asset_id = (registration.get("data") or {}).get("asset_id")
    if registration.get("code") != 200 or not asset_id:
        item["status"] = "FAIL_ASSET_REGISTRATION"
        item["registration"] = registration
        return item
    item["registered_asset_id"] = asset_id
    item["status"] = "PASS_REGISTERED"
    (QA / f"{item['line_id']}.json").write_text(json.dumps(item, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return item


def main() -> int:
    if not os.environ.get("GIGGLE_API_KEY"):
        raise SystemExit("GIGGLE_API_KEY is required")
    payload = json.loads(INPUT.read_text(encoding="utf-8"))
    if sha(SCRIPT) != payload["canonical_script_sha256"]:
        raise SystemExit("canonical script SHA mismatch")
    rows = [row for row in payload["lines"] if row["unit"] in TARGET_UNITS]
    counts: dict[str, int] = {}
    indexed = []
    for row in rows:
        counts[row["unit"]] = counts.get(row["unit"], 0) + 1
        indexed.append((row, counts[row["unit"]]))
    QA.mkdir(parents=True, exist_ok=True)
    generated = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(generate, row, index) for row, index in indexed]
        for future in as_completed(futures):
            generated.append(future.result())
    model = WhisperModel(str(WHISPER), device="cpu", compute_type="int8")
    results = [verify_and_register(item, model) for item in sorted(generated, key=lambda value: value["line_id"])]
    credits = [item.get("credit") or {} for item in results]
    receipt = {
        "schema": "qingshan.e39_exact_expressive_audio_assets.v1",
        "episode": "E39",
        "recorded_at": now(),
        "status": "PASS" if results and all(item["status"] == "PASS_REGISTERED" for item in results) else "PARTIAL_OR_FAILED",
        "canonical_script_sha256": sha(SCRIPT),
        "expressive_input_sha256": sha(INPUT),
        "results": results,
        "credits": {
            "pay": sum(item.get("pay") or 0 for item in credits),
            "refund": sum(item.get("refund") or 0 for item in credits),
            "net": sum(item.get("net") or 0 for item in credits),
        },
    }
    RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "passed": sum(item["status"] == "PASS_REGISTERED" for item in results), "total": len(results), "credits": receipt["credits"], "receipt": str(RECEIPT)}, ensure_ascii=False))
    return 0 if receipt["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
