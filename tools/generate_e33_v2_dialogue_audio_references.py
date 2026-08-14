#!/usr/bin/env python3
"""Generate and QA E33 v2 exact dialogue references from the current voice registry."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from faster_whisper import WhisperModel

from giggle_api_client import _get


ROOT = Path(__file__).resolve().parents[1]
AGENTCUT = ROOT / ".agentcut_env/bin/agentcut"
POLICY = ROOT / "configs/agentcut_character_voice_reference_policy_v1.json"
REGISTRY = ROOT / "configs/series_voice_reference_registry_current_20260723.json"
INVENTORY = ROOT / "workflow/claude_writer_agent/production/e33_claude_writer_v2_e19276d4_20260723/E33_SCRIPT_BEAT_DIALOGUE_INVENTORY_V2.json"
OUT_DIR = ROOT / "working_assets/e33_dialogue_audio_refs_v2_20260723"
QA_DIR = ROOT / "qa/e33_dialogue_audio_refs_v2_20260723"
MANIFEST = OUT_DIR / "E33_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V2.json"
WHISPER = Path("/Users/rogerwu/.cache/huggingface/hub/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120")
FFMPEG = shutil.which("ffmpeg") or str(next((ROOT / ".agentcut_env").glob("lib/python*/site-packages/agentcut/vendor/darwin-arm64/ffmpeg")))
FFPROBE = shutil.which("ffprobe") or str(Path(FFMPEG).with_name("ffprobe"))
HAN = re.compile(r"[\u3400-\u9fffA-Za-z0-9]")
SEEDANCE_AUDIO_MIN_SECONDS = 2.0
SEEDANCE_AUDIO_PAD_SECONDS = 2.2
SEEDANCE_AUDIO_MAX_SECONDS = 15.0


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def normalize_seedance_audio_duration(path: Path) -> dict:
    original_duration = probe_duration(path)
    if original_duration > SEEDANCE_AUDIO_MAX_SECONDS:
        raise RuntimeError(f"Seedance reference audio exceeds {SEEDANCE_AUDIO_MAX_SECONDS}s: {path}: {original_duration:.3f}s")
    if original_duration >= SEEDANCE_AUDIO_MIN_SECONDS:
        return {"applied": False, "original_duration_seconds": original_duration, "final_duration_seconds": original_duration}
    temp = path.with_name(f"{path.stem}.seedance-normalized{path.suffix}")
    subprocess.run(
        [
            str(FFMPEG), "-y", "-i", str(path), "-af", f"apad=whole_dur={SEEDANCE_AUDIO_PAD_SECONDS}",
            "-t", str(SEEDANCE_AUDIO_PAD_SECONDS), "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(temp),
        ],
        check=True,
        capture_output=True,
    )
    temp.replace(path)
    final_duration = probe_duration(path)
    if not (SEEDANCE_AUDIO_MIN_SECONDS <= final_duration <= SEEDANCE_AUDIO_MAX_SECONDS):
        raise RuntimeError(f"Seedance reference audio normalization failed: {path}: {final_duration:.3f}s")
    return {
        "applied": True,
        "method": "TAIL_SILENCE_ONLY",
        "original_duration_seconds": original_duration,
        "final_duration_seconds": final_duration,
        "provider_range_seconds": [SEEDANCE_AUDIO_MIN_SECONDS, SEEDANCE_AUDIO_MAX_SECONDS],
    }


def norm(value: str) -> str:
    return "".join(HAN.findall(value)).lower()


def last_json(value: str) -> dict:
    for line in reversed(value.splitlines()):
        try:
            result = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(result, dict):
            return result
    return {}


def task_credit(task_id: str) -> dict:
    for _ in range(7):
        response = _get("/api/v1/payment/credit-statements", {"credit_type": "Pay", "page": 1, "page_size": 40, "project_id": task_id})
        rows = [row for row in ((response.get("data") or {}).get("list") or []) if str(row.get("project_id") or "") == task_id and row.get("event_type") == "Pay"]
        if rows:
            try:
                total = sum(abs(Decimal(str(row["credit"]))) for row in rows)
            except (KeyError, InvalidOperation):
                total = None
            if total is not None:
                return {"status": "KNOWN_EXACT_TASK_STATEMENT", "charged_credits": int(total), "task_id": task_id, "statement_rows": rows}
        time.sleep(2)
    return {"status": "UNKNOWN_NOT_ESTIMATED", "charged_credits": None, "task_id": task_id, "statement_rows": []}


def generate(row: dict, specs: dict[str, dict], canonical: dict[str, dict]) -> dict:
    dia_id = row["dialogue_id"]
    role = row["speaker"]
    text = row["text"]
    spec = specs[role]
    raw = OUT_DIR / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    name = f"{dia_id}.mp3"
    command = [
        str(AGENTCUT), "speech-generate", text,
        "--voice-id", spec["voice_id"],
        "--emotion", spec["emotion"],
        "--speed", str(spec["speed"]),
        "--output-dir", str(raw),
        "--file-name", name,
        "--poll-interval", "2",
        "--timeout", "300",
        "--overwrite",
    ]
    result = subprocess.run(command, capture_output=True, text=True, env=os.environ.copy())
    payload = last_json(result.stdout or result.stderr)
    if result.returncode or payload.get("status") != "completed":
        return {
            "dia_id": dia_id,
            "video_unit_id": row["video_unit_id"],
            "speaker_id": role,
            "speaker": spec["name"],
            "spoken_text": text,
            "status": "FAIL",
            "credit": {"status": "REMOTE_EXPLICIT_FAILURE_ZERO" if payload.get("status") == "failed" else "NO_CONFIRMED_SUCCESS_ZERO", "charged_credits": 0},
            "response": payload,
        }
    voice = canonical[role]
    return {
        "dia_id": dia_id,
        "video_unit_id": row["video_unit_id"],
        "speaker_id": role,
        "speaker": spec["name"],
        "spoken_text": text,
        "status": "GENERATED",
        "mp3_path": payload["file"]["path"],
        "task_id": payload["taskId"],
        "credit": task_credit(payload["taskId"]),
        "source_voice": f"AGENTCUT_SPEECH_GENERATION:{spec['voice_id']}",
        "voice_gender": spec["gender"],
        "voice_derivation_status": "PASS",
        "voice_reference_asset_id": voice["remote_asset_id"],
    }


def main() -> int:
    if not os.environ.get("GIGGLE_API_KEY"):
        raise SystemExit("GIGGLE_API_KEY is required")
    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    lines = inventory["lines"]
    if len(lines) != 25:
        raise SystemExit("E33 v2 dialogue inventory must contain 25 lines")
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    specs = {row["entity_id"]: row for row in policy["roles"]}
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    canonical = {row["entity_id"]: row for row in registry["major_roles"]}
    generated_lines = [row for row in lines if row["speaker"] != "chenji"]
    if any(row["speaker"] not in {"chenji", "jiaotu", "yunyang"} for row in lines):
        raise SystemExit("E33 v2 dialogue contains an unregistered speaker")

    generated: list[dict] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(generate, row, specs, canonical) for row in generated_lines]
        for future in as_completed(futures):
            generated.append(future.result())
    by_id = {row["dia_id"]: row for row in generated}

    model = WhisperModel(str(WHISPER), device="cpu", compute_type="int8")
    QA_DIR.mkdir(parents=True, exist_ok=True)
    wav_dir = OUT_DIR / "wav"
    wav_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for line in lines:
        dia_id = line["dialogue_id"]
        unit_id = line["video_unit_id"]
        role = line["speaker"]
        text = line["text"]
        if role == "chenji":
            voice = canonical[role]
            source = Path(voice["local_reference"])
            rows.append({
                "dia_id": dia_id,
                "video_unit_id": unit_id,
                "speaker_id": role,
                "speaker": voice["name"],
                "spoken_text": text,
                "audio_mode": "CANONICAL_NATIVE_VOICE_STYLE_REFERENCE_WITH_EXACT_TEXT_PROMPT",
                "path": rel(source),
                "sha256": sha(source),
                "duration_seconds": voice["duration_seconds"],
                "remote_asset_id": voice["remote_asset_id"],
                "credit": {"status": "NO_NEW_GENERATION", "charged_credits": 0},
                "status": "PASS",
            })
            continue
        item = by_id[dia_id]
        if item["status"] != "GENERATED":
            rows.append(item)
            continue
        mp3 = Path(item["mp3_path"])
        wav = wav_dir / f"{dia_id}.wav"
        subprocess.run([str(FFMPEG), "-y", "-i", str(mp3), "-vn", "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(wav)], check=True, capture_output=True)
        segments, info = model.transcribe(str(wav), language="zh", vad_filter=True, beam_size=5, initial_prompt="以下是简体中文普通话对白。", hotwords=text)
        transcript = "".join(segment.text.strip() for segment in segments)
        similarity = difflib.SequenceMatcher(None, norm(text), norm(transcript)).ratio()
        duration_normalization = normalize_seedance_audio_duration(wav)
        duration = duration_normalization["final_duration_seconds"]
        status = "PASS" if similarity >= 0.70 and duration > 0 else "FAIL"
        qa = {
            "schema": "qingshan.dialogue_audio_reference_qa.v1",
            "dia_id": dia_id,
            "status": status,
            "expected_text": text,
            "asr_transcript": transcript,
            "asr_similarity": round(similarity, 4),
            "duration_seconds": duration,
            "wav_sha256": sha(wav),
            "provider_duration_normalization": duration_normalization,
            "failures": [] if status == "PASS" else ["ASR_RECALL_OR_DURATION_FAIL"],
        }
        (QA_DIR / f"{dia_id}_qa.json").write_text(json.dumps(qa, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        rows.append({**item, "audio_mode": "EXACT_DIALOGUE_AUDIO_REFERENCE", "path": rel(wav), "sha256": sha(wav), "duration_seconds": duration, "provider_duration_normalization": duration_normalization, "asr_transcript": transcript, "asr_similarity": round(similarity, 4), "status": status})

    rows.sort(key=lambda row: row["dia_id"])
    known = sum(Decimal(str(row["credit"]["charged_credits"])) for row in rows if row.get("credit", {}).get("charged_credits") is not None)
    unknown = sum(row.get("credit", {}).get("status") == "UNKNOWN_NOT_ESTIMATED" for row in rows)
    payload = {
        "schema": "qingshan.dialogue_audio_reference_manifest.v2",
        "episode": "E33",
        "status": "PASS" if all(row.get("status") == "PASS" for row in rows) and unknown == 0 else "FAIL",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_inventory": rel(INVENTORY),
        "line_count": len(rows),
        "exact_generated_line_count": len(generated_lines),
        "canonical_native_style_line_count": len(rows) - len(generated_lines),
        "known_credit_total": int(known),
        "unknown_credit_success_count": unknown,
        "rows": rows,
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: payload[key] for key in ("status", "line_count", "exact_generated_line_count", "canonical_native_style_line_count", "known_credit_total", "unknown_credit_success_count")}, ensure_ascii=False))
    return 0 if payload["status"] == "PASS" else 2


def normalize_existing_manifest() -> int:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    normalized = []
    for row in payload["rows"]:
        if row.get("audio_mode") != "EXACT_DIALOGUE_AUDIO_REFERENCE":
            continue
        path = ROOT / row["path"]
        evidence = normalize_seedance_audio_duration(path)
        row["duration_seconds"] = evidence["final_duration_seconds"]
        row["sha256"] = sha(path)
        row["provider_duration_normalization"] = evidence
        qa_path = QA_DIR / f"{row['dia_id']}_qa.json"
        if qa_path.is_file():
            qa = json.loads(qa_path.read_text(encoding="utf-8"))
            qa["duration_seconds"] = row["duration_seconds"]
            qa["wav_sha256"] = row["sha256"]
            qa["provider_duration_normalization"] = evidence
            qa_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if evidence["applied"]:
            normalized.append(row["dia_id"])
    payload["seedance_audio_duration_gate"] = {
        "status": "PASS",
        "range_seconds": [SEEDANCE_AUDIO_MIN_SECONDS, SEEDANCE_AUDIO_MAX_SECONDS],
        "short_clip_policy": "TAIL_SILENCE_ONLY_TO_2_2_SECONDS",
        "normalized_dialogue_ids": normalized,
    }
    payload["recorded_at_utc"] = datetime.now(timezone.utc).isoformat()
    MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "normalized_dialogue_ids": normalized, "manifest": rel(MANIFEST)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(normalize_existing_manifest() if "--normalize-existing" in sys.argv else main())
