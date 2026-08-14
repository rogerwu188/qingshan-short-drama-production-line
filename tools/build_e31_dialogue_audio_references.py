#!/usr/bin/env python3
"""Generate exact role-bound E31 dialogue references for Seedance lip sync."""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import edge_tts


ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "workflow/claude_writer_agent/production/e31_claude_writer_v1_20260722/E31_SCRIPT_BEAT_DIALOGUE_INVENTORY_V1.json"
PLAN = ROOT / "workflow/claude_writer_agent/production/e31_claude_writer_v1_20260722/E31_VIDEO_UNIT_PERFORMANCE_PLAN_V1.json"
WORK = ROOT / "working_assets/e31_dialogue_audio_refs_20260722"
MANIFEST = WORK / "E31_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V1.json"
FFMPEG = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffmpeg"
FFPROBE = FFMPEG.with_name("ffprobe")


VOICE = {
    "陈迹": ("zh-CN-YunxiNeural", "+8%", "-4Hz"),
    "皎兔": ("zh-CN-XiaoyiNeural", "+6%", "+4Hz"),
    "云羊": ("zh-CN-YunxiaNeural", "+8%", "+2Hz"),
    "云妃侍从": ("zh-CN-YunjianNeural", "+12%", "-8Hz"),
    "静妃侍从": ("zh-CN-YunyangNeural", "+10%", "-4Hz"),
    "内院家丁甲": ("zh-CN-YunyangNeural", "-2%", "-12Hz"),
    "灰衣门客": ("zh-CN-YunyangNeural", "-4%", "-8Hz"),
}


UNIT_DIALOGUE = {
    "E31-CW-U02": ["E31-DIA-001", "E31-DIA-002"],
    "E31-CW-U03": ["E31-DIA-003"],
    "E31-CW-U04": ["E31-DIA-004", "E31-DIA-005"],
    "E31-CW-U09": ["E31-DIA-006", "E31-DIA-007"],
    "E31-CW-U14": ["E31-DIA-008", "E31-DIA-009", "E31-DIA-010"],
    "E31-CW-U15": ["E31-DIA-011", "E31-DIA-012"],
    "E31-CW-U16": ["E31-DIA-013", "E31-DIA-014"],
    "E31-CW-U17": ["E31-DIA-015"],
    "E31-CW-U18": ["E31-DIA-016", "E31-DIA-017", "E31-DIA-018"],
    "E31-CW-U19": ["E31-DIA-019", "E31-DIA-020"],
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def probe_duration(path: Path) -> float:
    proc = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "format=duration", "-of", "default=nk=1:nw=1", str(path)],
        check=True,
        text=True,
        capture_output=True,
    )
    return float(proc.stdout.strip())


def collect_dialogue() -> dict[str, dict[str, str]]:
    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    result: dict[str, dict[str, str]] = {}
    for scene in inventory["scenes"]:
        for beat in scene["beats"]:
            for row in beat["dialogue"]:
                if row["speaker"] not in VOICE:
                    raise SystemExit(f"No role voice for {row['speaker']}")
                result[row["dia_id"]] = row
    if set(result) != {f"E31-DIA-{number:03d}" for number in range(1, 21)}:
        raise SystemExit("E31 dialogue inventory is not exactly 20/20")
    bound = [dia_id for values in UNIT_DIALOGUE.values() for dia_id in values]
    if len(bound) != 20 or set(bound) != set(result):
        raise SystemExit("E31 video-unit dialogue binding is not exactly 20/20")
    return result


async def generate(rows: dict[str, dict[str, str]]) -> list[dict[str, object]]:
    raw_dir = WORK / "raw"
    wav_dir = WORK / "wav"
    raw_dir.mkdir(parents=True, exist_ok=True)
    wav_dir.mkdir(parents=True, exist_ok=True)
    calls = []
    for dia_id, row in rows.items():
        voice, rate, pitch = VOICE[row["speaker"]]
        raw = raw_dir / f"{dia_id}.mp3"
        if not raw.is_file():
            calls.append(
                edge_tts.Communicate(text=row["spoken_text"], voice=voice, rate=rate, pitch=pitch).save(str(raw))
            )
    if calls:
        await asyncio.gather(*calls)
    manifest_rows = []
    by_unit = {dia_id: unit for unit, ids in UNIT_DIALOGUE.items() for dia_id in ids}
    for dia_id in sorted(rows):
        row = rows[dia_id]
        voice, rate, pitch = VOICE[row["speaker"]]
        raw = raw_dir / f"{dia_id}.mp3"
        wav = wav_dir / f"{dia_id}.wav"
        subprocess.run(
            [str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw),
             "-af", "highpass=f=75,lowpass=f=12500,loudnorm=I=-18:LRA=7:TP=-2",
             "-ac", "1", "-ar", "48000", str(wav)],
            check=True,
        )
        manifest_rows.append({
            "dia_id": dia_id,
            "video_unit_id": by_unit[dia_id],
            "speaker": row["speaker"],
            "spoken_text": row["spoken_text"],
            "performance": row["performance"],
            "voice": voice,
            "rate": rate,
            "pitch": pitch,
            "path": str(wav.relative_to(ROOT)),
            "sha256": sha256(wav),
            "duration_seconds": round(probe_duration(wav), 6),
            "purpose": "EXACT_TARGET_DIALOGUE_REFERENCE",
            "generation_policy": "REFERENCE_AUDIO_FOR_VIDEO_MODEL_NATIVE_MANDARIN_LIP_SYNC",
            "remote_call_credit": "UNKNOWN",
            "remote_call_credit_reason": "EDGE_TTS_SUCCESS_RESPONSE_HAS_NO_CREDIT_FIELD",
            "status": "PASS",
        })
    return manifest_rows


def main() -> int:
    rows = collect_dialogue()
    manifest_rows = asyncio.run(generate(rows))
    manifest = {
        "schema": "qingshan.dialogue_audio_reference_manifest.v1",
        "episode": "E31",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS",
        "dialogue_line_count": 20,
        "remote_call_count": 20,
        "remote_call_credit_known_total": 0,
        "remote_call_credit_unknown_count": 20,
        "credit_policy": "UNKNOWN_RECORDED_NOT_ESTIMATED",
        "rows": manifest_rows,
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    by_dia = {row["dia_id"]: row for row in manifest_rows}
    for unit in plan["units"]:
        ids = UNIT_DIALOGUE.get(unit["unit_id"], [])
        assets = [{
            "dia_id": dia_id,
            "path": by_dia[dia_id]["path"],
            "sha256": by_dia[dia_id]["sha256"],
            "purpose": "EXACT_TARGET_DIALOGUE_REFERENCE",
            "speaker": by_dia[dia_id]["speaker"],
            "spoken_text": by_dia[dia_id]["spoken_text"],
        } for dia_id in ids]
        unit["dialogue_ids"] = ids
        unit["native_dialogue_required"] = bool(ids)
        unit["dialogue_audio_assets"] = assets
        unit["reference_audios"] = [row["path"] for row in assets]
        unit["dialogue_audio_coverage"] = {
            "required": len(ids),
            "bound": len(assets),
            "status": "PASS" if ids else "NOT_APPLICABLE_NO_DIALOGUE",
        }
        unit["status"] = "WAITING_FOR_ANCHOR" if ids else unit["status"].replace("AND_DIALOGUE_AUDIO", "")
    PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PASS",
        "dialogue_lines": 20,
        "bound_units": len(UNIT_DIALOGUE),
        "manifest": str(MANIFEST.relative_to(ROOT)),
        "remote_credit": "UNKNOWN_NOT_ESTIMATED",
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
