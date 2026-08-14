#!/usr/bin/env python3
"""Bind repair assembly audio inputs to the approved published mix."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audio_fingerprint(path: Path, ffmpeg: Path) -> str:
    proc = subprocess.run(
        [
            str(ffmpeg),
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-c:a",
            "pcm_s16le",
            "-f",
            "hash",
            "-hash",
            "sha256",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-2000:])
    match = re.search(r"SHA256=([0-9a-fA-F]{64})", proc.stdout)
    if not match:
        raise RuntimeError("audio fingerprint missing")
    return match.group(1).lower()


def evaluate(plan: dict, actual_file_sha: str, actual_audio_fingerprint: str) -> dict:
    failures: list[str] = []
    binding = plan.get("audio_binding", {})
    expected_file_sha = str(binding.get("published_mix_file_sha256", "")).lower()
    expected_audio = str(binding.get("published_mix_audio_fingerprint", "")).lower()
    if expected_file_sha != actual_file_sha.lower():
        failures.append("published_mix_file_sha_mismatch")
    if expected_audio != actual_audio_fingerprint.lower():
        failures.append("published_mix_audio_fingerprint_mismatch")
    tracks = plan.get("audio_tracks", [])
    if not tracks:
        failures.append("audio_tracks_missing")
    for track in tracks:
        track_id = track.get("track_id", "UNKNOWN")
        if track.get("source_type") != "published_mix":
            failures.append(f"audio_track_not_published_mix:{track_id}")
        if str(track.get("source_file_sha256", "")).lower() != actual_file_sha.lower():
            failures.append(f"audio_track_file_sha_mismatch:{track_id}")
        if (
            str(track.get("source_audio_fingerprint", "")).lower()
            != actual_audio_fingerprint.lower()
        ):
            failures.append(f"audio_track_fingerprint_mismatch:{track_id}")
    for segment in plan.get("repair_segments", []):
        segment_id = segment.get("segment_id", "UNKNOWN")
        if not segment.get("candidate_audio_discarded", False):
            failures.append(f"candidate_audio_not_discarded:{segment_id}")
    return {
        "schema": "qingshan.audio_source_binding_gate.v1",
        "status": "PASS" if not failures else "FAIL",
        "audio_track_count": len(tracks),
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--published-mix", required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    mix = Path(args.published_mix).resolve()
    report = evaluate(
        json.loads(Path(args.plan).read_text(encoding="utf-8")),
        file_sha256(mix),
        audio_fingerprint(mix, Path(args.ffmpeg).resolve()),
    )
    Path(args.out).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": report["status"], "failures": report["failures"]}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
