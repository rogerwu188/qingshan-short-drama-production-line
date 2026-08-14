#!/usr/bin/env python3
"""Build direct-review burst sheets for V18C's fastest measured reframe windows."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_at(capture: cv2.VideoCapture, seconds: float) -> np.ndarray:
    capture.set(cv2.CAP_PROP_POS_MSEC, seconds * 1000.0)
    ok, frame = capture.read()
    if not ok:
        raise RuntimeError(f"Could not read {seconds:.3f}s")
    return frame


def choose_windows(records: list[dict], count: int, spacing: float) -> list[dict]:
    candidates = []
    for previous, current in zip(records, records[1:]):
        elapsed = current["time_seconds"] - previous["time_seconds"]
        if (
            elapsed <= 0
            or elapsed > 0.75
            or previous["score"] < 0.85
            or current["score"] < 0.85
            or previous["scale"] != current["scale"]
        ):
            continue
        dx = current["center_offset_x_px"] - previous["center_offset_x_px"]
        dy = current["center_offset_y_px"] - previous["center_offset_y_px"]
        candidates.append(
            {
                "time_seconds": current["time_seconds"],
                "estimated_speed_px_per_second": math.hypot(dx, dy) / elapsed,
            }
        )
    selected = []
    for candidate in sorted(
        candidates, key=lambda item: item["estimated_speed_px_per_second"], reverse=True
    ):
        if all(abs(candidate["time_seconds"] - item["time_seconds"]) >= spacing for item in selected):
            selected.append(candidate)
        if len(selected) == count:
            break
    return sorted(selected, key=lambda item: item["time_seconds"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--audit", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--index", required=True)
    parser.add_argument("--count", type=int, default=8)
    args = parser.parse_args()

    video = Path(args.video).resolve()
    audit = Path(args.audit).resolve()
    out_dir = Path(args.out_dir).resolve()
    index_path = Path(args.index).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    records = json.loads(audit.read_text(encoding="utf-8"))["sampling_records"]
    windows = choose_windows(records, args.count, 10.0)
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise SystemExit("Could not open candidate")

    sheets = []
    for number, window in enumerate(windows, start=1):
        center = float(window["time_seconds"])
        start = max(0.0, center - 2.0)
        tiles = []
        timestamps = []
        for offset in range(16):
            timestamp = start + offset * 0.25
            timestamps.append(round(timestamp, 3))
            frame = read_at(capture, timestamp)
            tile = cv2.resize(frame, (270, 480), interpolation=cv2.INTER_AREA)
            cv2.rectangle(tile, (0, 0), (270, 38), (0, 0, 0), -1)
            cv2.putText(
                tile,
                f"{timestamp:06.2f}s",
                (10, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )
            tiles.append(tile)
        sheet = np.vstack([np.hstack(tiles[index : index + 4]) for index in range(0, 16, 4)])
        path = out_dir / f"E36_V18C_HIGH_MOTION_BURST_{number:02d}_{center:06.1f}s.jpg"
        cv2.imwrite(str(path), sheet, [cv2.IMWRITE_JPEG_QUALITY, 94])
        sheets.append(
            {
                "path": str(path),
                "sha256": sha256(path),
                "center_seconds": center,
                "estimated_speed_px_per_second": window["estimated_speed_px_per_second"],
                "timestamps": timestamps,
                "direct_visual_review": "PENDING",
            }
        )
    capture.release()
    payload = {
        "schema": "qingshan.e36.v18c.high_motion_burst_review.v1",
        "candidate": str(video),
        "candidate_sha256": sha256(video),
        "source_reframe_audit": str(audit),
        "source_reframe_audit_sha256": sha256(audit),
        "window_selection": "top same-scale reliable estimated-speed windows with >=10s spacing",
        "burst_sampling": "16 frames at 0.25-second intervals over 3.75 seconds",
        "sheets": sheets,
        "gate_results": {
            "high_motion_review_package": "PASS",
            "direct_visual_motion_review": "PENDING",
            "continuous_realtime_audiovisual_watch": "NOT_COMPLETE",
        },
    }
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"index": str(index_path), "sheets": len(sheets)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
