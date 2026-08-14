#!/usr/bin/env python3
"""Measure per-edit mean luma from the final MP4 in strict timeline order."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path


def default_ffmpeg() -> str | None:
    bundled = Path(".video_deps/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1")
    if bundled.exists():
        return str(bundled.resolve())
    return shutil.which("ffmpeg")


def mean_luma(ffmpeg: str, video: Path, midpoint: float) -> float:
    proc = subprocess.run([
        ffmpeg,
        "-hide_banner",
        "-loglevel", "info",
        "-ss", f"{midpoint:.3f}",
        "-i", str(video),
        "-frames:v", "1",
        "-vf", "signalstats,metadata=print:file=-",
        "-an",
        "-f", "null",
        "-",
    ], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    text = proc.stdout + proc.stderr
    match = re.search(r"lavfi\.signalstats\.YAVG=([0-9.]+)", text)
    if not match:
        raise SystemExit(f"Could not measure luma at {midpoint:.3f}s")
    return float(match.group(1))


def validate_timeline(rows: list[dict], expected_scene_ids: list[str]) -> set[str]:
    if not rows:
        raise ValueError("Timeline contains no shots.")
    starts = [float(row["start"]) for row in rows]
    if starts != sorted(starts):
        raise ValueError("Timeline rows must be sorted by final start time.")
    scene_ids = {str(row.get("scene_id", "")).strip() for row in rows}
    if "" in scene_ids:
        raise ValueError("Every final-timeline row must carry a real scene_id.")
    expected = {item.strip() for item in expected_scene_ids if item.strip()}
    if expected and scene_ids != expected:
        raise ValueError(
            f"Final timeline scene IDs {sorted(scene_ids)} do not match expected {sorted(expected)}."
        )
    return scene_ids


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate final-timeline scene brightness audit JSON.")
    parser.add_argument("--video", required=True)
    parser.add_argument("--timeline", required=True, help="JSON with a timeline-ordered shots list.")
    parser.add_argument("--out", required=True)
    parser.add_argument("--ffmpeg", default=default_ffmpeg())
    parser.add_argument("--expected-scene-id", action="append", default=[])
    args = parser.parse_args()

    video = Path(args.video).expanduser().resolve()
    timeline_path = Path(args.timeline).expanduser().resolve()
    out = Path(args.out).expanduser().resolve()
    if not video.exists() or not timeline_path.exists():
        raise SystemExit("Missing final video or timeline JSON.")
    if not args.ffmpeg:
        raise SystemExit("Missing ffmpeg.")

    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    rows = timeline.get("shots", timeline if isinstance(timeline, list) else [])
    try:
        scene_ids = validate_timeline(rows, args.expected_scene_id)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    measured = []
    for row in rows:
        start = float(row["start"])
        end = float(row["end"])
        midpoint = start + max(0.05, end - start) / 2
        edge_offset = min(0.10, max(0.02, (end - start) / 4))
        measured.append({
            "shot_id": str(row["shot_id"]),
            "scene_id": str(row["scene_id"]),
            "start": start,
            "end": end,
            "midpoint": midpoint,
            "mean_luma": mean_luma(str(Path(args.ffmpeg).resolve()), video, midpoint),
            "start_luma": mean_luma(str(Path(args.ffmpeg).resolve()), video, start + edge_offset),
            "end_luma": mean_luma(str(Path(args.ffmpeg).resolve()), video, max(start + edge_offset, end - edge_offset)),
        })

    payload = {
        "schema": "qingshan.scene_brightness_audit.v1",
        "source_final_mp4": str(video),
        "source_timeline": str(timeline_path),
        "timeline_order_verified": True,
        "scene_ids_verified": sorted(scene_ids),
        "expected_scene_ids": sorted(args.expected_scene_id),
        "measurement": "final MP4 start/midpoint/end frames signalstats YAVG; boundary QA uses left end versus right start",
        "shots": measured,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(out), "shot_count": len(measured)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
