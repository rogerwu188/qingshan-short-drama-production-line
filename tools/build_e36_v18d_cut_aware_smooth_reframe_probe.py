#!/usr/bin/env python3
"""Render a cut-aware, zero-velocity reframe probe from retained V15."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

import imageio_ffmpeg


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def choose_offsets(index: int) -> tuple[tuple[int, int], tuple[int, int]]:
    points = [
        (-30, -48), (30, 48), (-30, 48), (30, -48),
        (0, -56), (0, 56), (-36, 0), (36, 0),
    ]
    start = points[index % len(points)]
    end = points[(index * 3 + 5) % len(points)]
    if start == end:
        end = points[(index + 3) % len(points)]
    return start, end


def smooth_expression(start: float, end: float, initial: int, final: int) -> str:
    duration = max(0.001, end - start)
    u = f"clip((t-{start:.6f})/{duration:.6f},0,1)"
    eased = f"({u})*({u})*(3-2*({u}))"
    return f"{initial}+({final-initial})*({eased})"


def piecewise(axis: int, sources: list[dict], final_end: float) -> str:
    fallback = "(in_w-out_w)/2" if axis == 0 else "(in_h-out_h)/2"
    expression = fallback
    for index in reversed(range(len(sources))):
        start, end = sources[index]["accepted_only_timeline_seconds"]
        if index == len(sources) - 1:
            end = final_end
        initial, final = choose_offsets(index)
        center = "(in_w-out_w)/2" if axis == 0 else "(in_h-out_h)/2"
        local = smooth_expression(start, end, initial[axis], final[axis])
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
    x_expression = piecewise(0, sources, args.duration)
    y_expression = piecewise(1, sources, args.duration)
    video_filter = (
        "scale=800:1422:flags=lanczos,"
        f"crop=720:1280:x='{x_expression}':y='{y_expression}',"
        "setsar=1,format=yuv420p"
    )
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(args.source), "-filter:v", video_filter,
        "-map", "0:v:0", "-map", "0:a:0", "-c:v", "libx264",
        "-preset", "veryfast", "-crf", "18", "-c:a", "copy",
        "-movflags", "+faststart", str(args.output),
    ]
    subprocess.run(command, check=True)
    manifest = {
        "schema": "qingshan.e36.v18d.cut_aware_smooth_reframe_probe.v1",
        "source": str(args.source.resolve()),
        "source_sha256": sha256(args.source),
        "source_map": str(args.source_map.resolve()),
        "source_map_sha256": sha256(args.source_map),
        "output": str(args.output.resolve()),
        "output_sha256": sha256(args.output),
        "segment_count": len(sources),
        "duration_target_seconds": args.duration,
        "geometry": {
            "scaled_dimensions": "800x1422",
            "output_dimensions": "720x1280",
            "x_offset_range_from_center_px": [-36, 36],
            "y_offset_range_from_center_px": [-56, 56],
            "path": "per-accepted-source cubic smoothstep with zero velocity at both ends",
            "boundary_policy": "motion path changes only at accepted-source timeline boundaries",
        },
        "audio": "stream_copy_from_v15",
        "credits": {"pay": 0, "refund": 0, "net": 0},
        "disposition": "REVERSIBLE_PROBE_NOT_PROMOTED",
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
