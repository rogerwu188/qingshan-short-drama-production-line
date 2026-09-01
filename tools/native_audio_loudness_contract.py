#!/usr/bin/env python3
"""Measure and gate native multimodal audio without replacing its content.

The contract applies bounded static gain per source unit before the final mix.
It preserves the source task's dialogue, ambience, foley, action sound, timing,
and channel layout; only playback level and peak safety may change.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any


ROLE_TARGETS_LUFS = {
    # These are premaster staging targets.  The release master is normalized
    # separately to -16 LUFS; targeting -16 here would make dialogue too loud
    # after that final, program-wide gain stage.
    "DIALOGUE": -18.0,
    "ACTION": -20.0,
    "AMBIENCE": -22.0,
    "MUSIC": -23.0,
}
ROLE_ACCEPTANCE_RANGES_LUFS = {
    "DIALOGUE": (-20.0, -13.0),
    "ACTION": (-23.0, -14.0),
    "AMBIENCE": (-27.0, -16.0),
    "MUSIC": (-28.0, -17.0),
}
DEFAULT_MAX_GAIN_DB = 12.0
DEFAULT_MAX_ATTENUATION_DB = 8.0
DEFAULT_TRUE_PEAK_CEILING_DBTP = -1.5
DEFAULT_MAX_ADJACENT_DELTA_LU = 8.0
DEFAULT_RELEASE_RANGE_LUFS = (-17.0, -15.0)
DEFAULT_RELEASE_MAX_LRA_LU = 12.0
DEFAULT_RELEASE_TRUE_PEAK_MAX_DBTP = -1.0


def infer_loudness_role(metadata: dict[str, Any] | None, *, track_id: str = "") -> str:
    metadata = metadata or {}
    explicit = str(
        metadata.get("loudness_role")
        or metadata.get("native_audio_loudness_role")
        or ""
    ).upper()
    if explicit in ROLE_TARGETS_LUFS:
        return explicit
    if track_id == "Audio.BGM":
        return "MUSIC"
    if str(metadata.get("dialogue_classification") or "").upper() == "SPEAKING":
        return "DIALOGUE"
    if str(metadata.get("action_classification") or "").upper() in {
        "COMBAT",
        "CHASE",
        "COMBAT_IMPULSE",
    }:
        return "ACTION"
    return "AMBIENCE"


def plan_static_gain(
    integrated_lufs: float,
    true_peak_dbtp: float,
    role: str,
    *,
    target_lufs: float | None = None,
    max_gain_db: float = DEFAULT_MAX_GAIN_DB,
    max_attenuation_db: float = DEFAULT_MAX_ATTENUATION_DB,
    true_peak_ceiling_dbtp: float = DEFAULT_TRUE_PEAK_CEILING_DBTP,
) -> dict[str, float | str]:
    role = role.upper()
    if role not in ROLE_TARGETS_LUFS:
        raise ValueError(f"unknown loudness role: {role}")
    target = ROLE_TARGETS_LUFS[role] if target_lufs is None else float(target_lufs)
    desired = target - float(integrated_lufs)
    peak_headroom = true_peak_ceiling_dbtp - float(true_peak_dbtp)
    gain = min(desired, max_gain_db, peak_headroom)
    gain = max(gain, -abs(max_attenuation_db))
    return {
        "role": role,
        "input_integrated_lufs": round(float(integrated_lufs), 3),
        "input_true_peak_dbtp": round(float(true_peak_dbtp), 3),
        "target_lufs": round(target, 3),
        "gain_db": round(gain, 3),
        "predicted_integrated_lufs": round(float(integrated_lufs) + gain, 3),
        "predicted_true_peak_dbtp": round(float(true_peak_dbtp) + gain, 3),
    }


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False)


def measure_loudness(
    path: Path,
    *,
    start_seconds: float = 0.0,
    duration_seconds: float | None = None,
    ffmpeg: str = "ffmpeg",
) -> dict[str, float]:
    command = [ffmpeg, "-hide_banner", "-nostats"]
    if start_seconds > 0:
        command += ["-ss", f"{start_seconds:.6f}"]
    if duration_seconds is not None:
        command += ["-t", f"{duration_seconds:.6f}"]
    command += ["-i", str(path), "-map", "0:a:0", "-af", "ebur128=peak=true", "-f", "null", "-"]
    result = _run(command)
    if result.returncode:
        raise RuntimeError(result.stderr[-4000:])
    integrated = re.findall(r"Integrated loudness:\s*\n\s*I:\s*(-?[0-9.]+) LUFS", result.stderr)
    lra = re.findall(r"Loudness range:\s*\n\s*LRA:\s*([0-9.]+) LU", result.stderr)
    peak = re.findall(r"True peak:\s*\n\s*Peak:\s*(-?[0-9.]+) dBFS", result.stderr)
    if not integrated or not lra or not peak:
        raise RuntimeError(f"could not parse EBU R128 metrics for {path}")
    return {
        "integrated_loudness_lufs": float(integrated[-1]),
        "loudness_range_lu": float(lra[-1]),
        "true_peak_dbtp": float(peak[-1]),
    }


def evaluate_unit_loudness(
    rows: list[dict[str, Any]],
    *,
    max_adjacent_delta_lu: float = DEFAULT_MAX_ADJACENT_DELTA_LU,
) -> list[str]:
    failures: list[str] = []
    previous: dict[str, Any] | None = None
    for row in rows:
        unit_id = str(row.get("unit_id") or row.get("clip_id") or "UNKNOWN")
        role = str(row.get("role") or "").upper()
        value = float(row["integrated_loudness_lufs"])
        lower, upper = ROLE_ACCEPTANCE_RANGES_LUFS.get(role, (-27.0, -13.0))
        if not lower <= value <= upper:
            failures.append(f"UNIT_LOUDNESS_OUT_OF_ROLE_RANGE:{unit_id}:{value:.1f}:{role}")
        if previous is not None:
            delta = abs(value - float(previous["integrated_loudness_lufs"]))
            if delta > max_adjacent_delta_lu:
                failures.append(
                    f"ADJACENT_UNIT_LOUDNESS_DELTA_EXCEEDED:"
                    f"{previous.get('unit_id')}->{unit_id}:{delta:.1f}LU"
                )
        previous = row
    return failures


def evaluate_release_loudness(metrics: dict[str, float]) -> list[str]:
    failures: list[str] = []
    integrated = float(metrics["integrated_loudness_lufs"])
    lra = float(metrics["loudness_range_lu"])
    peak = float(metrics["true_peak_dbtp"])
    if not DEFAULT_RELEASE_RANGE_LUFS[0] <= integrated <= DEFAULT_RELEASE_RANGE_LUFS[1]:
        failures.append(f"RELEASE_INTEGRATED_LOUDNESS_OUT_OF_RANGE:{integrated:.1f}")
    if lra > DEFAULT_RELEASE_MAX_LRA_LU:
        failures.append(f"RELEASE_LOUDNESS_RANGE_TOO_WIDE:{lra:.1f}")
    if peak > DEFAULT_RELEASE_TRUE_PEAK_MAX_DBTP:
        failures.append(f"RELEASE_TRUE_PEAK_EXCEEDS_CEILING:{peak:.1f}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("media", type=Path)
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--duration", type=float)
    parser.add_argument("--role", choices=sorted(ROLE_TARGETS_LUFS), default="AMBIENCE")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args()
    measured = measure_loudness(
        args.media,
        start_seconds=args.start,
        duration_seconds=args.duration,
        ffmpeg=args.ffmpeg,
    )
    planned = plan_static_gain(
        measured["integrated_loudness_lufs"], measured["true_peak_dbtp"], args.role
    )
    print(json.dumps({"measured": measured, "plan": planned}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
