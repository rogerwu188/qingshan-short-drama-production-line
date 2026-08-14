#!/usr/bin/env python3
"""Audit V18C's full-film dynamic reframe without changing source media."""

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
        raise RuntimeError(f"Could not read frame at {seconds:.3f}s")
    return frame


def estimate_crop(source: np.ndarray, candidate: np.ndarray) -> dict:
    target_width = 180
    target_height = 320
    target = cv2.resize(candidate, (target_width, target_height))
    target = cv2.cvtColor(target, cv2.COLOR_BGR2GRAY)
    best = None
    for scale in (1.06, 1.08, 1.10, 1.12):
        width = int(round(target_width * scale))
        height = int(round(target_height * scale))
        search = cv2.resize(source, (width, height))
        search = cv2.cvtColor(search, cv2.COLOR_BGR2GRAY)
        result = cv2.matchTemplate(search, target, cv2.TM_CCOEFF_NORMED)
        _, score, _, location = cv2.minMaxLoc(result)
        x, y = location
        center_x = (width - target_width) / 2.0
        center_y = (height - target_height) / 2.0
        record = {
            "scale": scale,
            "score": float(score),
            "crop_x_px": float(x * 4),
            "crop_y_px": float(y * 4),
            "center_offset_x_px": float((x - center_x) * 4),
            "center_offset_y_px": float((y - center_y) * 4),
        }
        if best is None or record["score"] > best["score"]:
            best = record
    assert best is not None
    return best


def tile(frame: np.ndarray, label: str, width: int = 432, height: int = 768) -> np.ndarray:
    resized = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
    cv2.rectangle(resized, (0, 0), (width, 48), (0, 0, 0), -1)
    cv2.putText(
        resized,
        label,
        (12, 34),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.78,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    return resized


def make_contact_sheets(
    source_capture: cv2.VideoCapture,
    candidate_capture: cv2.VideoCapture,
    output_dir: Path,
    duration: float,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamps = [float(value) for value in range(0, int(duration), 5)]
    sheets = []
    for sheet_index, start in enumerate(range(0, len(timestamps), 10), start=1):
        rows = []
        for timestamp in timestamps[start : start + 10]:
            source = read_at(source_capture, timestamp)
            candidate = read_at(candidate_capture, timestamp)
            pair = np.hstack(
                [
                    tile(source, f"V15 source {timestamp:06.1f}s"),
                    tile(candidate, f"V18C candidate {timestamp:06.1f}s"),
                ]
            )
            rows.append(pair)
        while len(rows) < 10:
            rows.append(np.zeros_like(rows[0]))
        sheet = np.vstack([np.hstack(rows[i : i + 2]) for i in range(0, 10, 2)])
        path = output_dir / f"E36_V18C_FULL_COVERAGE_SOURCE_VS_CANDIDATE_{sheet_index:02d}.jpg"
        cv2.imwrite(str(path), sheet, [cv2.IMWRITE_JPEG_QUALITY, 92])
        sheets.append(path)
    return sheets


def percentile(values: list[float], quantile: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=np.float64), quantile))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--contact-dir", required=True)
    parser.add_argument("--duration", type=float, default=282.828)
    parser.add_argument("--interval", type=float, default=0.5)
    args = parser.parse_args()

    source_path = Path(args.source).resolve()
    candidate_path = Path(args.candidate).resolve()
    out_path = Path(args.out).resolve()
    contact_dir = Path(args.contact_dir).resolve()
    source_capture = cv2.VideoCapture(str(source_path))
    candidate_capture = cv2.VideoCapture(str(candidate_path))
    if not source_capture.isOpened() or not candidate_capture.isOpened():
        raise SystemExit("Could not open source or candidate")

    records = []
    timestamp = 0.0
    while timestamp < args.duration:
        source = read_at(source_capture, timestamp)
        candidate = read_at(candidate_capture, timestamp)
        crop = estimate_crop(source, candidate)
        crop["time_seconds"] = round(timestamp, 3)
        records.append(crop)
        timestamp += args.interval

    valid = [record for record in records if record["score"] >= 0.70]
    speeds = []
    for previous, current in zip(valid, valid[1:]):
        elapsed = current["time_seconds"] - previous["time_seconds"]
        if elapsed <= 0 or elapsed > args.interval * 1.5:
            continue
        dx = current["center_offset_x_px"] - previous["center_offset_x_px"]
        dy = current["center_offset_y_px"] - previous["center_offset_y_px"]
        speed = math.hypot(dx, dy) / elapsed
        speeds.append(speed)

    sheets = make_contact_sheets(
        source_capture, candidate_capture, contact_dir, args.duration
    )
    source_capture.release()
    candidate_capture.release()

    scale_counts = {}
    for record in valid:
        key = f'{record["scale"]:.2f}'
        scale_counts[key] = scale_counts.get(key, 0) + 1
    offsets_x = [abs(record["center_offset_x_px"]) for record in valid]
    offsets_y = [abs(record["center_offset_y_px"]) for record in valid]
    payload = {
        "schema": "qingshan.e36.v18c.reframe_comfort_audit.v1",
        "source": str(source_path),
        "source_sha256": sha256(source_path),
        "candidate": str(candidate_path),
        "candidate_sha256": sha256(candidate_path),
        "duration_seconds": args.duration,
        "sample_interval_seconds": args.interval,
        "sample_count": len(records),
        "reliable_match_threshold": 0.70,
        "reliable_match_count": len(valid),
        "reliable_match_ratio": len(valid) / len(records),
        "match_score_mean": float(np.mean([record["score"] for record in records])),
        "scale_counts_reliable_samples": scale_counts,
        "center_offset_abs_x_px_p95": percentile(offsets_x, 95),
        "center_offset_abs_y_px_p95": percentile(offsets_y, 95),
        "estimated_reframe_speed_px_per_second": {
            "p50": percentile(speeds, 50),
            "p95": percentile(speeds, 95),
            "max": max(speeds),
        },
        "contact_sheets": [
            {"path": str(path), "sha256": sha256(path)} for path in sheets
        ],
        "sampling_records": records,
        "gate_results": {
            "full_duration_reframe_match": (
                "PASS" if len(valid) / len(records) >= 0.95 else "REVIEW"
            ),
            "full_coverage_contact_sheet_generation": "PASS",
            "direct_visual_review": "PENDING",
            "continuous_motion_and_audiovisual_watch": "NOT_COMPLETE",
        },
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "out": str(out_path),
                "reliable_match_ratio": payload["reliable_match_ratio"],
                "speed": payload["estimated_reframe_speed_px_per_second"],
                "contact_sheets": len(sheets),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
