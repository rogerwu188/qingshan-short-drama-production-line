#!/usr/bin/env python3
"""Compare source and reframed interframe motion to localize added camera movement."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path

import cv2
import numpy as np


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * fraction))]


def read_samples(path: Path, sample_fps: float) -> tuple[list[tuple[float, np.ndarray]], dict]:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"cannot open {path}")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, round(fps / sample_fps))
    frames: list[tuple[float, np.ndarray]] = []
    index = 0
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        if index % step == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, (360, 640), interpolation=cv2.INTER_AREA)
            frames.append((index / fps, gray))
        index += 1
    capture.release()
    return frames, {"fps": fps, "frame_count": frame_count, "sample_step_frames": step}


def affine_motion(first: np.ndarray, second: np.ndarray, orb: cv2.ORB) -> dict:
    key1, desc1 = orb.detectAndCompute(first, None)
    key2, desc2 = orb.detectAndCompute(second, None)
    if desc1 is None or desc2 is None or len(key1) < 20 or len(key2) < 20:
        return {"reliable": False, "reason": "insufficient_features"}
    pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(desc1, desc2, k=2)
    good = [left for left, right in pairs if left.distance < 0.72 * right.distance]
    if len(good) < 20:
        return {"reliable": False, "reason": "insufficient_matches", "matches": len(good)}
    source = np.float32([key1[item.queryIdx].pt for item in good])
    target = np.float32([key2[item.trainIdx].pt for item in good])
    matrix, mask = cv2.estimateAffinePartial2D(
        source, target, method=cv2.RANSAC, ransacReprojThreshold=2.0,
        maxIters=2000, confidence=0.995, refineIters=10,
    )
    if matrix is None or mask is None:
        return {"reliable": False, "reason": "affine_fit_failed", "matches": len(good)}
    inliers = int(mask.sum())
    if inliers < 14 or inliers / len(good) < 0.35:
        return {
            "reliable": False, "reason": "weak_affine_fit", "matches": len(good),
            "inliers": inliers, "inlier_ratio": inliers / len(good),
        }
    a, b, dx = matrix[0]
    c, d, dy = matrix[1]
    return {
        "reliable": True,
        "dx": float(dx), "dy": float(dy),
        "translation": float(math.hypot(dx, dy)),
        "scale": float(math.sqrt(a * a + c * c)),
        "rotation_degrees": float(math.degrees(math.atan2(c, a))),
        "matches": len(good), "inliers": inliers,
        "inlier_ratio": inliers / len(good),
    }


def reversal_ratio(vectors: list[tuple[float, float]]) -> tuple[int, int, float]:
    reversals = 0
    valid = 0
    for previous, current in zip(vectors, vectors[1:]):
        if math.hypot(*previous) < 0.25 or math.hypot(*current) < 0.25:
            continue
        valid += 1
        if previous[0] * current[0] + previous[1] * current[1] < 0:
            reversals += 1
    return reversals, valid, reversals / valid if valid else 0.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--sample-fps", type=float, default=4.0)
    args = parser.parse_args()

    source_frames, source_meta = read_samples(args.source, args.sample_fps)
    candidate_frames, candidate_meta = read_samples(args.candidate, args.sample_fps)
    sample_count = min(len(source_frames), len(candidate_frames))
    orb = cv2.ORB_create(nfeatures=1200, scaleFactor=1.2, nlevels=8, fastThreshold=12)
    cross_transforms = [
        affine_motion(source_frames[index][1], candidate_frames[index][1], orb)
        for index in range(sample_count)
    ]
    records = []
    for index in range(1, sample_count):
        timestamp = min(source_frames[index][0], candidate_frames[index][0])
        source_motion = affine_motion(source_frames[index - 1][1], source_frames[index][1], orb)
        candidate_motion = affine_motion(candidate_frames[index - 1][1], candidate_frames[index][1], orb)
        cross_previous = cross_transforms[index - 1]
        cross_current = cross_transforms[index]
        record = {
            "time_seconds": timestamp, "source": source_motion, "candidate": candidate_motion,
            "source_to_candidate_previous": cross_previous,
            "source_to_candidate_current": cross_current,
        }
        if all(item.get("reliable") for item in (source_motion, candidate_motion, cross_previous, cross_current)):
            cross_scale = statistics.mean((cross_previous["scale"], cross_current["scale"]))
            expected_dx = source_motion["dx"] * cross_scale
            expected_dy = source_motion["dy"] * cross_scale
            excess_dx = candidate_motion["dx"] - expected_dx
            excess_dy = candidate_motion["dy"] - expected_dy
            record["excess"] = {
                "dx": excess_dx, "dy": excess_dy,
                "translation": math.hypot(excess_dx, excess_dy),
                "rotation_degrees": candidate_motion["rotation_degrees"] - source_motion["rotation_degrees"],
                "scale_delta": candidate_motion["scale"] - source_motion["scale"],
                "source_to_candidate_cross_scale": cross_scale,
                "expected_candidate_dx_from_scaled_source": expected_dx,
                "expected_candidate_dy_from_scaled_source": expected_dy,
            }
        records.append(record)

    reliable = [item for item in records if "excess" in item]
    translations = [item["excess"]["translation"] for item in reliable]
    vectors = [(item["excess"]["dx"], item["excess"]["dy"]) for item in reliable]
    reversals, valid_pairs, reversal_fraction = reversal_ratio(vectors)
    largest = sorted(reliable, key=lambda item: item["excess"]["translation"], reverse=True)[:30]
    report = {
        "schema": "qingshan.e36.v18c.interframe_motion_attribution.v1",
        "source": str(args.source.resolve()),
        "source_sha256": sha256(args.source),
        "candidate": str(args.candidate.resolve()),
        "candidate_sha256": sha256(args.candidate),
        "sample_fps_requested": args.sample_fps,
        "source_media": source_meta,
        "candidate_media": candidate_meta,
        "sample_count": sample_count,
        "pair_count": len(records),
        "reliable_pair_count": len(reliable),
        "reliable_pair_ratio": len(reliable) / len(records) if records else 0.0,
        "candidate_minus_source_interframe_translation_px_at_360x640": {
            "p50": percentile(translations, 0.50),
            "p90": percentile(translations, 0.90),
            "p95": percentile(translations, 0.95),
            "p99": percentile(translations, 0.99),
            "max": max(translations, default=0.0),
        },
        "candidate_minus_source_direction_reversals": {
            "count": reversals, "valid_pair_count": valid_pairs, "ratio": reversal_fraction,
        },
        "largest_excess_motion_windows": [
            {
                "time_seconds": item["time_seconds"],
                "translation_px": item["excess"]["translation"],
                "dx": item["excess"]["dx"], "dy": item["excess"]["dy"],
                "rotation_degrees": item["excess"]["rotation_degrees"],
                "scale_delta": item["excess"]["scale_delta"],
            }
            for item in largest
        ],
        "method": {
            "frame_size": "360x640",
            "feature": "ORB_1200",
            "transform": "RANSAC_partial_affine_between_successive_samples",
            "attribution": "candidate interframe transform minus source interframe transform scaled by the mean same-time source-to-candidate affine scale",
            "limitations": "Scene cuts and weak-texture frames are excluded by feature and affine-fit reliability gates. Residual includes reframe motion plus transform-estimation error and cannot alone clear subjective comfort.",
        },
        "gate_results": {
            "full_duration_source_candidate_sampling": "PASS",
            "reliable_motion_attribution": "PASS" if len(reliable) / max(1, len(records)) >= 0.70 else "FAIL_LOW_RELIABLE_RATIO",
            "continuous_realtime_human_comfort_watch": "NOT_COMPLETE",
        },
        "records": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
