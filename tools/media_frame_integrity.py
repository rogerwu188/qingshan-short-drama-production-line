#!/usr/bin/env python3
"""Frame-by-frame black/solid/freeze scan and objective edit-window telemetry."""

from __future__ import annotations

import json
import statistics
import subprocess
from pathlib import Path
from typing import Any


ANALYSIS_WIDTH = 96
ANALYSIS_HEIGHT = 160


def _probe(path: Path, ffprobe: str = "ffprobe") -> tuple[float, float]:
    command = [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=avg_frame_rate,duration", "-of", "json", str(path)]
    payload = json.loads(subprocess.check_output(command, text=True))
    stream = payload["streams"][0]
    num, den = str(stream.get("avg_frame_rate") or "0/1").split("/", 1)
    fps = float(num) / float(den)
    return fps, float(stream.get("duration") or 0.0)


def _ranges(flags: list[bool], fps: float, minimum_seconds: float = 0.0) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    start: int | None = None
    for index, flag in enumerate(flags + [False]):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            duration = (index - start) / fps
            if duration + 1e-9 >= minimum_seconds:
                rows.append({"start_seconds": round(start / fps, 4), "end_seconds": round(index / fps, 4), "duration_seconds": round(duration, 4)})
            start = None
    return rows


def analyze(path: Path, *, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe") -> dict[str, Any]:
    path = path.expanduser().resolve()
    fps, duration = _probe(path, ffprobe)
    frame_bytes = ANALYSIS_WIDTH * ANALYSIS_HEIGHT
    command = [
        ffmpeg, "-v", "error", "-i", str(path), "-map", "0:v:0",
        "-vf", f"scale={ANALYSIS_WIDTH}:{ANALYSIS_HEIGHT},format=gray",
        "-f", "rawvideo", "-pix_fmt", "gray", "-",
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE)
    assert process.stdout is not None
    means: list[float] = []
    ranges: list[int] = []
    diffs: list[float] = []
    previous: bytes | None = None
    while True:
        frame = process.stdout.read(frame_bytes)
        if not frame:
            break
        if len(frame) != frame_bytes:
            process.kill()
            raise RuntimeError(f"INCOMPLETE_RAW_FRAME:{path}")
        means.append(sum(frame) / frame_bytes)
        ranges.append(max(frame) - min(frame))
        diffs.append(0.0 if previous is None else sum(abs(a - b) for a, b in zip(frame, previous)) / frame_bytes)
        previous = frame
    if process.wait() != 0 or not means:
        raise RuntimeError(f"FRAME_SCAN_FAILED:{path}")
    median_luma = statistics.median(means)
    positive_diffs = [value for value in diffs[1:] if value > 0]
    median_diff = statistics.median(positive_diffs) if positive_diffs else 0.0
    black_flags = [value < 8.0 for value in means]
    solid_flags = [value < 4 for value in ranges]
    freeze_limit = max(0.15, median_diff * 0.30)
    freeze_flags = [index > 0 and value < freeze_limit for index, value in enumerate(diffs)]
    return {
        "schema": "qingshan.media_frame_integrity.v1",
        "path": str(path),
        "fps": fps,
        "duration_seconds": duration,
        "frames_scanned": len(means),
        "median_luma": median_luma,
        "median_frame_difference": median_diff,
        "freeze_difference_threshold": freeze_limit,
        "luma": means,
        "frame_difference": diffs,
        "black_ranges": _ranges(black_flags, fps),
        "solid_color_ranges": _ranges(solid_flags, fps),
        "freeze_ranges": _ranges(freeze_flags, fps, minimum_seconds=0.20),
    }


def recommend_window(scan: dict[str, Any], *, safety_handle_seconds: float = 0.25) -> dict[str, float]:
    fps = float(scan["fps"])
    luma = list(scan["luma"])
    diffs = list(scan["frame_difference"])
    median_luma = float(scan["median_luma"])
    median_diff = float(scan["median_frame_difference"])
    motion_floor = max(0.15, median_diff * 0.30)
    head_limit = min(len(luma) - 1, round(0.8 * fps))
    first_active = head_limit
    for index in range(1, head_limit + 1):
        if luma[index] >= median_luma * 0.40 and diffs[index] >= motion_floor:
            first_active = index
            break
    last_active = len(luma) - 1
    # Retreat through an arbitrarily long inactive tail, but never erase the
    # whole authored event.  A fixed two-second ceiling left long pose-holds in
    # provider media and made the edit look artificially slow.
    tail_floor = min(len(luma) - 1, max(0, round(1.5 * fps)))
    while last_active > tail_floor:
        if luma[last_active] < median_luma * 0.40 or diffs[last_active] < motion_floor:
            last_active -= 1
            continue
        break
    selected_in = first_active / fps
    selected_out = min(float(scan["duration_seconds"]), (last_active + 1) / fps + safety_handle_seconds)
    # A safety handle may preserve genuine motion around a cut, but it must not
    # re-admit a detected defect that reaches the physical end of the file.
    # This matters for tails shorter than the handle itself (for example the
    # 0.125-second black tail observed in E51-VU-008).
    endpoint_epsilon = 1.0 / fps
    terminal_defect_ranges = (
        list(scan.get("black_ranges") or [])
        + list(scan.get("solid_color_ranges") or [])
        + list(scan.get("freeze_ranges") or [])
    )
    for defect_range in terminal_defect_ranges:
        if float(defect_range["end_seconds"]) >= float(scan["duration_seconds"]) - endpoint_epsilon:
            selected_out = min(selected_out, float(defect_range["start_seconds"]))
    if selected_out <= selected_in:
        selected_in, selected_out = 0.0, float(scan["duration_seconds"])
    return {
        "selected_in_seconds": round(selected_in, 4),
        "selected_out_seconds": round(selected_out, 4),
        "safety_handle_seconds": safety_handle_seconds,
        "head_trim_seconds": round(selected_in, 4),
        "tail_trim_seconds": round(max(0.0, float(scan["duration_seconds"]) - selected_out), 4),
    }
