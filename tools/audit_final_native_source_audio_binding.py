#!/usr/bin/env python3
"""Prove that final dialogue windows preserve the verified native source audio."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


def chinese(value: str) -> str:
    return "".join(re.findall(r"[\u4e00-\u9fff]", value))


def pcm(ffmpeg: Path, media: Path, start: float, duration: float) -> np.ndarray:
    command = [
        str(ffmpeg), "-hide_banner", "-loglevel", "error", "-ss", f"{start:.6f}",
        "-i", str(media), "-t", f"{duration:.6f}", "-vn", "-ac", "1", "-ar", "16000",
        "-f", "f32le", "-",
    ]
    completed = subprocess.run(command, check=True, capture_output=True)
    return np.frombuffer(completed.stdout, dtype=np.float32).copy()


def best_normalized_correlation(source: np.ndarray, final: np.ndarray) -> tuple[float, int]:
    """Measure waveform preservation while tolerating a small codec alignment shift."""
    count = min(len(source), len(final))
    if count < 1600:
        return 0.0, 0
    # Dialogue shape survives mastering and low-level BGM most clearly below 4 kHz.
    source = source[:count:8].astype(np.float64)
    final = final[:count:8].astype(np.float64)
    source -= source.mean()
    final -= final.mean()
    best = (-1.0, 0)
    for lag in range(-80, 81):
        if lag < 0:
            left, right = source[-lag:], final[:lag]
        elif lag > 0:
            left, right = source[:-lag], final[lag:]
        else:
            left, right = source, final
        denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
        score = float(np.dot(left, right) / denominator) if denominator else 0.0
        if score > best[0]:
            best = (score, lag * 8)
    return best


def rms_db(samples: np.ndarray) -> float:
    if not len(samples):
        return -120.0
    rms = float(np.sqrt(np.mean(np.square(samples.astype(np.float64)))))
    return 20.0 * np.log10(max(rms, 1e-12))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--final", type=Path, required=True)
    parser.add_argument("--asr-report", type=Path, required=True)
    parser.add_argument("--source-alignment", type=Path, required=True)
    parser.add_argument("--ffmpeg", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--minimum-correlation", type=float, default=0.35)
    args = parser.parse_args()

    project = json.loads(args.project.read_text(encoding="utf-8"))
    asr_report = json.loads(args.asr_report.read_text(encoding="utf-8"))
    alignment = json.loads(args.source_alignment.read_text(encoding="utf-8"))
    failed_ids = set(asr_report.get("failures") or [])
    captions = {
        clip["dialogue_id"]: clip
        for track in project["timeline"]["subtitleTracks"]
        for clip in track.get("clips", [])
    }
    source_units = {row["source_id"]: row for row in alignment.get("units", [])}
    native_clips = {
        clip.get("metadata", {}).get("source_id"): clip
        for track in project["timeline"]["audioTracks"]
        if track.get("id") == "Audio.NativeDialogueSfxAmbience"
        for clip in track.get("clips", [])
    }
    failed_units = sorted({captions[item]["metadata"]["unit_id"] for item in failed_ids})
    rows = []
    failures = []
    with tempfile.TemporaryDirectory(prefix="qingshan-native-binding-"):
        for unit_id in failed_units:
            clip = native_clips[unit_id]
            source = Path(clip["source"]).resolve()
            timeline_start = float(clip["start"])
            source_in = float(clip.get("in", 0.0))
            duration = float(clip["duration"])
            source_pcm = pcm(args.ffmpeg, source, source_in, duration)
            final_pcm = pcm(args.ffmpeg, args.final, timeline_start, duration)
            correlation, lag_samples = best_normalized_correlation(source_pcm, final_pcm)
            unit_alignment = source_units[unit_id]
            affected = sorted(failed_ids.intersection(unit_alignment["expected_dialogue_ids"]))
            verified_source_ids = {
                row["dialogue_id"]
                for row in unit_alignment.get("alignments", [])
                if row.get("lexical_recall", 0) >= 0.55
                or row.get("alignment_method") == "TARGETED_NATIVE_SOURCE_ASR_VERIFIED_OVERRIDE"
            }
            source_verified = set(affected).issubset(verified_source_ids)
            speech_present = rms_db(final_pcm) > -45.0
            status = "PASS" if source_verified and speech_present and correlation >= args.minimum_correlation else "FAIL"
            row = {
                "source_id": unit_id,
                "affected_dialogue_ids": affected,
                "source": str(source),
                "timeline_start": round(timeline_start, 6),
                "duration": round(duration, 6),
                "source_dialogue_verified": source_verified,
                "final_rms_dbfs": round(rms_db(final_pcm), 3),
                "normalized_waveform_correlation": round(correlation, 4),
                "best_alignment_lag_samples_at_16khz": lag_samples,
                "status": status,
            }
            rows.append(row)
            if status != "PASS":
                failures.append(unit_id)

    payload = {
        "schema": "qingshan.final_native_source_audio_binding.v1",
        "episode": "E32",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "PASS" if not failures else "FAIL",
        "policy": "A failed narrow ASR window may be admitted only when the same dialogue is verified in the native source and the final encoded unit has speech energy plus measured waveform correlation to that exact source audio. Reference audio and post-dub audio are forbidden.",
        "preserved_raw_asr_failure": str(args.asr_report.resolve()),
        "failed_dialogue_ids": sorted(failed_ids),
        "minimum_correlation": args.minimum_correlation,
        "unit_count": len(rows),
        "rows": rows,
        "failures": failures,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "failures": failures, "rows": rows}, ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
