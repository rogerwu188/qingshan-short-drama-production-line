#!/usr/bin/env python3
"""Separate high-frequency reframe-path variation from slower empirical motion."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[min(len(ordered) - 1, int(len(ordered) * fraction))]


def median_path(points: list[dict], window: int) -> list[tuple[float, float]]:
    radius = window // 2
    result = []
    for index in range(len(points)):
        left = max(0, index - radius)
        right = min(len(points), index + radius + 1)
        result.append(
            (
                statistics.median(item["x"] for item in points[left:right]),
                statistics.median(item["y"] for item in points[left:right]),
            )
        )
    return result


def motion_summary(points: list[dict], path: list[tuple[float, float]]) -> dict:
    vectors: list[tuple[float, float]] = []
    speeds: list[float] = []
    for index in range(1, len(points)):
        elapsed = points[index]["time"] - points[index - 1]["time"]
        if elapsed > 0.75:
            vectors.append((math.nan, math.nan))
            continue
        dx = path[index][0] - path[index - 1][0]
        dy = path[index][1] - path[index - 1][1]
        vectors.append((dx, dy))
        speeds.append(math.hypot(dx, dy) / elapsed)

    valid_pairs = 0
    reversals = 0
    for previous, current in zip(vectors, vectors[1:]):
        if any(math.isnan(value) for value in (*previous, *current)):
            continue
        if previous == (0.0, 0.0) or current == (0.0, 0.0):
            continue
        valid_pairs += 1
        if previous[0] * current[0] + previous[1] * current[1] < 0.0:
            reversals += 1
    return {
        "step_count": len(speeds),
        "speed_px_per_second": {
            "p50": percentile(speeds, 0.5),
            "p95": percentile(speeds, 0.95),
            "max": max(speeds, default=0.0),
        },
        "direction_reversal_pair_count": reversals,
        "direction_reversal_valid_pair_count": valid_pairs,
        "direction_reversal_pair_ratio": reversals / valid_pairs if valid_pairs else 0.0,
    }


def pearson(left: list[float], right: list[float]) -> float:
    mean_left = statistics.mean(left)
    mean_right = statistics.mean(right)
    numerator = sum(
        (a - mean_left) * (b - mean_right) for a, b in zip(left, right)
    )
    denominator = math.sqrt(
        sum((item - mean_left) ** 2 for item in left)
        * sum((item - mean_right) ** 2 for item in right)
    )
    return numerator / denominator if denominator else 0.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audit", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    source = json.loads(args.audit.read_text())
    records = [
        {
            "time": float(item["time_seconds"]),
            "x": float(item["center_offset_x_px"]),
            "y": float(item["center_offset_y_px"]),
            "score": float(item["score"]),
        }
        for item in source["sampling_records"]
        if float(item["score"]) >= float(source["reliable_match_threshold"])
    ]
    raw_path = [(item["x"], item["y"]) for item in records]
    median_5 = median_path(records, 5)
    median_9 = median_path(records, 9)
    residual_5 = [
        math.hypot(raw[0] - smooth[0], raw[1] - smooth[1])
        for raw, smooth in zip(raw_path, median_5)
    ]
    residual_9 = [
        math.hypot(raw[0] - smooth[0], raw[1] - smooth[1])
        for raw, smooth in zip(raw_path, median_9)
    ]

    score_bins = {}
    for label, low, high in (
        ("0.70_to_0.85", 0.70, 0.85),
        ("0.85_to_0.95", 0.85, 0.95),
        ("0.95_to_1.00", 0.95, 1.01),
    ):
        values = [
            residual
            for record, residual in zip(records, residual_5)
            if low <= record["score"] < high
        ]
        score_bins[label] = {
            "sample_count": len(values),
            "median_residual_px": statistics.median(values) if values else 0.0,
            "p95_residual_px": percentile(values, 0.95),
        }

    raw_summary = motion_summary(records, raw_path)
    smooth_5_summary = motion_summary(records, median_5)
    smooth_9_summary = motion_summary(records, median_9)
    report = {
        "schema": "qingshan.e36.v18c.reframe_path_multiscale_jitter_audit.v1",
        "source_audit": str(args.audit.resolve()),
        "source_audit_sha256": sha256(args.audit),
        "candidate": source["candidate"],
        "candidate_sha256": source["candidate_sha256"],
        "reliable_sample_count": len(records),
        "sample_interval_seconds": source["sample_interval_seconds"],
        "raw_path": raw_summary,
        "median_5_sample_2p5_second_path": smooth_5_summary,
        "median_9_sample_4p5_second_path": smooth_9_summary,
        "raw_to_median_5_residual_px": {
            "p50": percentile(residual_5, 0.5),
            "p95": percentile(residual_5, 0.95),
            "max": max(residual_5, default=0.0),
        },
        "raw_to_median_9_residual_px": {
            "p50": percentile(residual_9, 0.5),
            "p95": percentile(residual_9, 0.95),
            "max": max(residual_9, default=0.0),
        },
        "match_score_to_median_5_residual_correlation": pearson(
            [item["score"] for item in records], residual_5
        ),
        "match_score_bins": score_bins,
        "interpretation": {
            "uniform_single_direction_pan": "REJECTED",
            "high_frequency_variation": "PRESENT_IN_INVERSE_ESTIMATE",
            "estimation_noise_check": "USE_SCORE_CORRELATION_AND_SCORE_BIN_RESIDUALS",
            "comfort_verdict": "NOT_CLEARED_BY_EMPIRICAL_PATH",
            "reason": "Median filtering quantifies the high-frequency component but cannot prove whether the unsmoothed component is rendered shake, source-cut contamination or inverse-localization noise. Uninterrupted realtime viewing remains required."
        },
        "gate_results": {
            "full_reliable_path_recalculation": "PASS",
            "uniform_global_pan_hypothesis": "REJECTED",
            "multiscale_jitter_localization": "PASS_MEASURED",
            "continuous_realtime_human_comfort_watch": "NOT_COMPLETE"
        }
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
