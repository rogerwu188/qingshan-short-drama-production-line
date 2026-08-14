#!/usr/bin/env python3
"""Render a cut-aware reframe probe with smooth zero-velocity shot cycles."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from pathlib import Path

import imageio_ffmpeg


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def local_cycle(start: float, end: float, amplitude: int, cycles: int) -> str:
    duration = max(0.001, end - start)
    u = f"clip((t-{start:.6f})/{duration:.6f},0,1)"
    return f"{amplitude}*(1-cos(2*PI*{cycles}*({u})))/2"


def piecewise(axis: int, sources: list[dict], final_end: float) -> str:
    center = "(in_w-out_w)/2" if axis == 0 else "(in_h-out_h)/2"
    expression = center
    for index in reversed(range(len(sources))):
        start, end = sources[index]["accepted_only_timeline_seconds"]
        if index == len(sources) - 1:
            end = final_end
        duration = max(0.001, end - start)
        cycles = max(1, round(duration / (4.75 + (index % 3) * 0.4)))
        if axis == 0:
            amplitude = (34 if index % 3 else 28) * (-1 if index % 2 else 1)
        else:
            amplitude = (52 if index % 4 else 42) * (-1 if (index // 2) % 2 else 1)
            cycles = max(1, cycles + (1 if index % 5 == 0 and duration > 5 else 0))
        local = local_cycle(start, end, amplitude, cycles)
        expression = f"if(between(t,{start:.6f},{end:.6f}),{center}+({local}),{expression})"
    return expression


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("source_map", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--duration", type=float, default=282.828)
    args = parser.parse_args()

    source_map = json.loads(args.source_map.read_text())
    sources = source_map["sources"]
    video_filter = (
        "scale=800:1422:flags=lanczos,"
        f"crop=720:1280:x='{piecewise(0, sources, args.duration)}':"
        f"y='{piecewise(1, sources, args.duration)}',"
        "setsar=1,format=yuv420p"
    )
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(args.source),
        "-filter:v", video_filter, "-map", "0:v:0", "-map", "0:a:0",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "copy",
        "-movflags", "+faststart", str(args.output),
    ], check=True)
    manifest = {
        "schema": "qingshan.e36.v18e.cut_aware_zero_velocity_cycle_probe.v1",
        "source": str(args.source.resolve()), "source_sha256": sha256(args.source),
        "source_map": str(args.source_map.resolve()), "source_map_sha256": sha256(args.source_map),
        "output": str(args.output.resolve()), "output_sha256": sha256(args.output),
        "segment_count": len(sources), "duration_target_seconds": args.duration,
        "geometry": {
            "scaled_dimensions": "800x1422", "output_dimensions": "720x1280",
            "x_one_sided_amplitude_px": "28_or_34_by_segment",
            "y_one_sided_amplitude_px": "42_or_52_by_segment",
            "path": "per-accepted-source raised-cosine cycles with zero velocity and zero offset at both boundaries",
            "period_target_seconds": "4.75_to_5.55_varied_by_segment",
            "boundary_policy": "every path returns to center at accepted-source boundaries",
        },
        "audio": "stream_copy_from_v15",
        "credits": {"pay": 0, "refund": 0, "net": 0},
        "disposition": "REVERSIBLE_PROBE_NOT_PROMOTED",
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
