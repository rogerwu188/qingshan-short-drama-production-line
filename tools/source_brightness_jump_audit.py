#!/usr/bin/env python3
"""Detect abrupt per-second source brightness jumps such as day/night stitching."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


FRAME_SIZE = 64 * 64
FROZEN_MAX_THRESHOLD = 25.0


def validate_threshold(threshold: float) -> list[str]:
    if threshold > FROZEN_MAX_THRESHOLD:
        return [
            f"threshold_relaxation_forbidden:{threshold:.3f}>{FROZEN_MAX_THRESHOLD:.3f}"
        ]
    return []


def audit(video: Path, ffmpeg: Path, threshold: float) -> dict:
    proc = subprocess.run(
        [
            str(ffmpeg),
            "-v",
            "error",
            "-i",
            str(video),
            "-vf",
            "fps=1,scale=64:64,format=gray",
            "-f",
            "rawvideo",
            "pipe:1",
        ],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", errors="replace")[-2000:])
    frames = [
        proc.stdout[index : index + FRAME_SIZE]
        for index in range(0, len(proc.stdout), FRAME_SIZE)
        if len(proc.stdout[index : index + FRAME_SIZE]) == FRAME_SIZE
    ]
    yavg = [sum(frame) / FRAME_SIZE for frame in frames]
    jumps = [
        {
            "from_second": index,
            "to_second": index + 1,
            "absolute_yavg_jump": abs(yavg[index + 1] - yavg[index]),
        }
        for index in range(len(yavg) - 1)
    ]
    max_jump = max((row["absolute_yavg_jump"] for row in jumps), default=0.0)
    return {
        "schema": "qingshan.source_brightness_jump_audit.v1",
        "video": str(video.resolve()),
        "sample_fps": 1,
        "yavg_per_second": yavg,
        "adjacent_jumps": jumps,
        "max_adjacent_jump": max_jump,
        "fail_threshold": threshold,
        "status": "PASS" if max_jump <= threshold else "FAIL_BRIGHTNESS_JUMP",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--threshold", type=float, default=25.0)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    threshold_failures = validate_threshold(args.threshold)
    if threshold_failures:
        report = {
            "schema": "qingshan.source_brightness_jump_audit.v1",
            "video": str(Path(args.video).resolve()),
            "fail_threshold": args.threshold,
            "frozen_max_threshold": FROZEN_MAX_THRESHOLD,
            "status": "FAIL_THRESHOLD_RELAXATION",
            "failures": threshold_failures,
        }
        Path(args.out).resolve().write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps({"status": report["status"], "failures": threshold_failures}))
        return 2
    report = audit(Path(args.video), Path(args.ffmpeg), args.threshold)
    Path(args.out).resolve().write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": report["status"], "max_jump": report["max_adjacent_jump"]}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
