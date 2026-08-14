#!/usr/bin/env python3
"""Measure trajectory shape in the six strongest low-frequency V18C windows."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "working_assets/e36_agentcut_20260731/accepted_only_v15/E36_ACCEPTED_ONLY_AGENTCUT_V15_PACED_ROOMTONE_REPAIR_FINAL.mp4"
CANDIDATE = ROOT / "working_assets/e36_agentcut_20260731/accepted_only_v18_zero_credit_dynamic_reframe_probe/E36_ACCEPTED_ONLY_AGENTCUT_V18C_TWO_PART_DYNAMIC_REFRAME_EXACT_V15_AUDIO_PROBE.mp4"
PATH_AUDIT = ROOT / "qa/e36_agentcut_20260730/E36_V18C_FULL_REFRAME_COMFORT_AUDIT_V1.json"
AUTHORITY = ROOT / "qa/e36_agentcut_20260730/E36_V18C_NATIVE24_LOW_FREQUENCY_DRIFT_LOCALIZATION_V1.json"
OUTPUT = ROOT / "qa/e36_agentcut_20260730/E36_V18C_LOW_FREQUENCY_TRAJECTORY_SHAPE_QA_V1.json"
WIDTH, HEIGHT, FPS = 180, 320, 24


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def robust_turns(signal: np.ndarray, prominence: float) -> list[dict[str, float]]:
    turns: list[dict[str, float]] = []
    last_value = float(signal[0])
    direction = 0
    extreme_index = 0
    extreme_value = last_value
    for index, value_raw in enumerate(signal[1:], start=1):
        value = float(value_raw)
        delta = value - last_value
        new_direction = 1 if delta > 0 else -1 if delta < 0 else direction
        if direction == 0:
            direction = new_direction
        if new_direction == direction:
            if (direction > 0 and value >= extreme_value) or (direction < 0 and value <= extreme_value):
                extreme_index, extreme_value = index, value
        elif abs(extreme_value - value) >= prominence:
            turns.append({"seconds": extreme_index / FPS, "value_px": extreme_value})
            direction = new_direction
            extreme_index, extreme_value = index, value
        last_value = value
    return turns


def main() -> None:
    scale_records = json.loads(PATH_AUDIT.read_text(encoding="utf-8"))["sampling_records"]
    authority = json.loads(AUTHORITY.read_text(encoding="utf-8"))
    windows = authority["strongest_non_overlapping_windows"]
    source = cv2.VideoCapture(str(SOURCE))
    candidate = cv2.VideoCapture(str(CANDIDATE))
    hanning2d = cv2.createHanningWindow((WIDTH, HEIGHT), cv2.CV_32F)
    rows = []
    for row in windows:
        start, end = float(row["start_seconds"]), float(row["end_seconds"])
        start_frame, end_frame = round(start * FPS), round(end * FPS)
        source.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        candidate.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

        def read_gray(cap: cv2.VideoCapture) -> np.ndarray:
            ok, frame = cap.read()
            if not ok:
                raise EOFError
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            return cv2.resize(gray, (WIDTH, HEIGHT), interpolation=cv2.INTER_AREA).astype(np.float32)

        prev_source, prev_candidate = read_gray(source), read_gray(candidate)
        vectors = np.full((end_frame - start_frame - 1, 2), np.nan, dtype=np.float64)
        responses = []
        for local_index, frame_index in enumerate(range(start_frame + 1, end_frame)):
            current_source, current_candidate = read_gray(source), read_gray(candidate)
            source_shift, source_response = cv2.phaseCorrelate(prev_source, current_source, hanning2d)
            candidate_shift, candidate_response = cv2.phaseCorrelate(prev_candidate, current_candidate, hanning2d)
            scale = float(scale_records[min(len(scale_records) - 1, round((frame_index / FPS) / 0.5))]["scale"])
            reliable = (
                source_response >= 0.12 and candidate_response >= 0.12
                and math.hypot(*source_shift) <= 30 and math.hypot(*candidate_shift) <= 30
            )
            if reliable:
                vectors[local_index] = (
                    candidate_shift[0] - source_shift[0] * scale,
                    candidate_shift[1] - source_shift[1] * scale,
                )
                responses.append(min(source_response, candidate_response))
            prev_source, prev_candidate = current_source, current_candidate
        valid = np.isfinite(vectors[:, 0])
        indices = np.arange(len(vectors))
        for axis in range(2):
            vectors[:, axis] = np.interp(indices, indices[valid], vectors[valid, axis])
        trajectory = np.vstack([np.zeros(2), np.cumsum(vectors, axis=0)])
        time = np.arange(len(trajectory))
        design = np.column_stack([np.ones(len(trajectory)), time])
        detrended = trajectory - design @ np.linalg.lstsq(design, trajectory, rcond=None)[0]
        covariance = np.cov(detrended.T)
        eigenvalues, eigenvectors = np.linalg.eigh(covariance)
        axis = eigenvectors[:, int(np.argmax(eigenvalues))]
        projection = detrended @ axis
        kernel = np.ones(7) / 7
        smooth = np.convolve(np.pad(projection, (3, 3), mode="edge"), kernel, mode="valid")
        excursion = float(np.ptp(smooth))
        prominence = max(0.15, excursion * 0.12)
        turns = robust_turns(smooth, prominence)
        velocity = np.linalg.norm(vectors, axis=1)
        path_length = float(velocity.sum())
        net_displacement = float(np.linalg.norm(trajectory[-1] - trajectory[0]))
        rows.append({
            "base_seconds": [start, end],
            "v19_seconds": [start + 6.082993, end + 6.082993],
            "frame_pairs": len(vectors),
            "reliable_pairs": int(valid.sum()),
            "minimum_phase_response": float(min(responses)) if responses else None,
            "dominant_axis_excursion_px_at_180x320": excursion,
            "turning_point_prominence_px": prominence,
            "robust_turning_points": turns,
            "robust_turn_count": len(turns),
            "net_displacement_px": net_displacement,
            "path_length_px": path_length,
            "path_efficiency": net_displacement / path_length if path_length else 0.0,
            "velocity_px_per_frame": {
                "p50": float(np.percentile(velocity, 50)),
                "p95": float(np.percentile(velocity, 95)),
                "max": float(np.max(velocity)),
            },
            "authority_low_band_fraction": row["low_band_fraction_0p5_to_10hz"],
            "authority_dominant_frequency_hz": row["dominant_frequency_hz"],
        })
    source.release()
    candidate.release()
    report = {
        "schema": "e36_v18c_low_frequency_trajectory_shape_qa_v1",
        "source_cl2x": "CL2X-915",
        "source_mailbox_sha256": "e62dade34f0da40e44d35d0cf3d58099af66454180f169b6dc020f91a583d620",
        "source": {"path": str(SOURCE.relative_to(ROOT)), "sha256": sha256(SOURCE)},
        "candidate": {"path": str(CANDIDATE.relative_to(ROOT)), "sha256": sha256(CANDIDATE), "status": "REVERSIBLE_NOT_PROMOTED"},
        "authority": {"path": str(AUTHORITY.relative_to(ROOT)), "sha256": sha256(AUTHORITY)},
        "sampling": {"fps": FPS, "resolution": [WIDTH, HEIGHT], "window_count": len(rows), "window_seconds": 4.0, "smoothing": "7_FRAME_CENTERED_MOVING_AVERAGE", "trajectory": "INTEGRATED_CANDIDATE_MINUS_SCALE_ADJUSTED_SOURCE_PHASE_TRANSLATION"},
        "windows": rows,
        "aggregate": {
            "reliable_pairs": sum(row["reliable_pairs"] for row in rows),
            "frame_pairs": sum(row["frame_pairs"] for row in rows),
            "robust_turn_count": sum(row["robust_turn_count"] for row in rows),
            "excursion_px_p50": float(np.percentile([row["dominant_axis_excursion_px_at_180x320"] for row in rows], 50)),
            "excursion_px_max": max(row["dominant_axis_excursion_px_at_180x320"] for row in rows),
            "path_efficiency_p50": float(np.percentile([row["path_efficiency"] for row in rows], 50)),
        },
        "method_limits": "Global phase translation can be confounded by subject movement, cuts, scale interpolation and codec noise. Turning points describe residual crop trajectory shape; they do not clear subjective comfort, lipsync, breath, identity or causal continuity.",
        "gate_results": {"trajectory_shape_localization": "PASS", "subjective_comfort": "NOT_CLEARED", "continuous_realtime_human_watch": "NOT_COMPLETE", "promotion": "NOT_GRANTED"},
        "credits": {"pay": 0, "refund": 0, "net": 0},
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT.relative_to(ROOT)), "sha256": sha256(OUTPUT), "aggregate": report["aggregate"]}))


if __name__ == "__main__":
    main()
