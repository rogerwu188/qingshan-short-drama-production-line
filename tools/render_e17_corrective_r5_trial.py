#!/usr/bin/env python3
"""Render the E17 R5 picture plan without retime, freeze, loops or digital punch-ins."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from run_regression_ci import default_ffmpeg


BASE = Path("/Users/rogerwu/qingshan_short_drama")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--ffmpeg", default=default_ffmpeg())
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    segments = plan["segments"]
    base = BASE / segments[0]["path"]
    inserts = segments[1:]
    command = [args.ffmpeg, "-y", "-i", str(base)]
    for item in inserts:
        command.extend([
            "-ss", str(item["in_sec"]),
            "-t", str(item["duration_sec"]),
            "-i", str(BASE / item["path"]),
        ])
    filters = ["[0:v]setpts=PTS-STARTPTS[v0]"]
    previous = "v0"
    for index, item in enumerate(inserts, 1):
        prepared = f"cut{index}"
        output = f"v{index}"
        start = float(item["timeline_in_sec"])
        end = start + float(item["duration_sec"])
        filters.append(
            f"[{index}:v]setpts=PTS-STARTPTS+{start:.6f}/TB,"
            f"scale=720:1280:force_original_aspect_ratio=increase,"
            f"crop=720:1280,setsar=1[{prepared}]"
        )
        filters.append(
            f"[{previous}][{prepared}]overlay=eof_action=pass:enable='between(t,{start:.6f},{end:.6f})'[{output}]"
        )
        previous = output
    boundaries = [float(value) for value in plan["audio_boundary_repairs"]["boundaries_seconds"]]
    overlap = 0.06
    audio_ranges = []
    for index in range(len(boundaries) + 1):
        start = 0.0 if index == 0 else boundaries[index - 1] - overlap
        end = (
            float(plan["target_runtime_seconds"])
            if index == len(boundaries)
            else boundaries[index] + overlap
        )
        audio_ranges.append((max(0.0, start), end))
    for index, (start, end) in enumerate(audio_ranges):
        filters.append(
            f"[0:a]atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS[a{index}]"
        )
    audio_previous = "a0"
    for index in range(1, len(audio_ranges)):
        audio_output = f"ax{index}"
        filters.append(
            f"[{audio_previous}][a{index}]acrossfade=d=0.12:c1=qsin:c2=qsin[{audio_output}]"
        )
        audio_previous = audio_output
    args.out.parent.mkdir(parents=True, exist_ok=True)
    command.extend([
        "-filter_complex", ";".join(filters),
        "-map", f"[{previous}]", "-map", f"[{audio_previous}]",
        "-r", "24", "-c:v", "libx264", "-crf", "18", "-preset", "slow",
        "-c:a", "aac", "-b:a", "192k", "-t", str(plan["target_runtime_seconds"]),
        str(args.out),
    ])
    subprocess.run(command, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
