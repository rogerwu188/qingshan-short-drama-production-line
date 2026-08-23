#!/usr/bin/env python3
"""Fill V19 digital-zero gaps with episode-native, speech-free hall room tone."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "working_assets/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V19_REPETITION_SAFE_RECUT.mp4"
ROOMTONE = ROOT / "working_assets/e40_remake_20260822/final_audio_v20/E40_V20_EPISODE_NATIVE_HALL_ROOMTONE.wav"
OUT = ROOT / "working_assets/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V20_ROOMTONE_CONTINUITY.mp4"
QA = ROOT / "qa/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V20_ROOMTONE_CONTINUITY_QA.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ROOMTONE.parent.mkdir(parents=True, exist_ok=True)
    # R08's admitted native source interval contains hall ambience/action sound
    # and whole-track ASR found no speech. It is additive only: source audio is
    # never deleted, replaced, or post-dubbed.
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-ss", "110.125", "-t", "4.0", "-i", str(SOURCE),
        "-vn", "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", str(ROOMTONE),
    ], check=True)
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-i", str(SOURCE), "-stream_loop", "-1", "-i", str(ROOMTONE),
        "-filter_complex", "[1:a]volume=12dB,highpass=f=60,lowpass=f=8000[bed];[0:a][bed]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]",
        "-map", "0:v:0", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-shortest", "-movflags", "+faststart", str(OUT),
    ], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(OUT), "-f", "null", "-"], check=True)
    payload = {
        "schema": "qingshan.e40.v20.native_roomtone_continuity.v1",
        "episode": "E40",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "TECHNICAL_PASS_REGISTERED_AUDIO_QA_REQUIRED",
        "source_path": str(SOURCE.relative_to(ROOT)),
        "source_sha256": sha(SOURCE),
        "roomtone_source_interval_seconds": [110.125, 114.125],
        "roomtone_path": str(ROOMTONE.relative_to(ROOT)),
        "roomtone_sha256": sha(ROOMTONE),
        "audio_operation": "ADDITIVE_EPISODE_NATIVE_AMBIENCE_ONLY; ORIGINAL_AUDIO_PRESERVED; NO_DIALOGUE; NO_TTS; NO_BGM",
        "asset_path": str(OUT.relative_to(ROOT)),
        "asset_sha256": sha(OUT),
        "release_allowed": False,
        "next_successor_task_id": "E40-V20-REGISTERED-FINAL-QA-V1",
    }
    QA.parent.mkdir(parents=True, exist_ok=True)
    QA.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"asset": payload["asset_path"], "sha256": payload["asset_sha256"], "roomtone_sha256": payload["roomtone_sha256"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
