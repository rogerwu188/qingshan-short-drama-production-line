#!/usr/bin/env python3
"""Localize low-frequency V18C reframe energy for targeted realtime review."""

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
SPECTRUM_AUDIT = ROOT / "qa/e36_agentcut_20260730/E36_V18C_NATIVE24_MOTION_SPECTRUM_DIAGNOSTIC_V1.json"
OUTPUT = ROOT / "qa/e36_agentcut_20260730/E36_V18C_NATIVE24_LOW_FREQUENCY_DRIFT_LOCALIZATION_V1.json"
WIDTH, HEIGHT, FPS = 180, 320, 24
WINDOW_FRAMES, HOP_FRAMES = 96, 48


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    path_audit = json.loads(PATH_AUDIT.read_text(encoding="utf-8"))
    spectrum_audit = json.loads(SPECTRUM_AUDIT.read_text(encoding="utf-8"))
    scale_records = path_audit["sampling_records"]
    source = cv2.VideoCapture(str(SOURCE))
    candidate = cv2.VideoCapture(str(CANDIDATE))
    frame_count = min(int(source.get(cv2.CAP_PROP_FRAME_COUNT)), int(candidate.get(cv2.CAP_PROP_FRAME_COUNT)))
    if frame_count != 6751:
        raise SystemExit(f"unexpected frame count {frame_count}")
    hanning2d = cv2.createHanningWindow((WIDTH, HEIGHT), cv2.CV_32F)

    def read_gray(cap: cv2.VideoCapture) -> np.ndarray:
        ok, frame = cap.read()
        if not ok:
            raise EOFError
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return cv2.resize(gray, (WIDTH, HEIGHT), interpolation=cv2.INTER_AREA).astype(np.float32)

    vectors = np.full((frame_count - 1, 2), np.nan, dtype=np.float64)
    magnitudes: list[float] = []
    prev_source, prev_candidate = read_gray(source), read_gray(candidate)
    for index in range(1, frame_count):
        current_source, current_candidate = read_gray(source), read_gray(candidate)
        source_shift, source_response = cv2.phaseCorrelate(prev_source, current_source, hanning2d)
        candidate_shift, candidate_response = cv2.phaseCorrelate(prev_candidate, current_candidate, hanning2d)
        timestamp = index / FPS
        scale = float(scale_records[min(len(scale_records) - 1, round(timestamp / 0.5))]["scale"])
        reliable = (
            source_response >= 0.12 and candidate_response >= 0.12
            and math.hypot(*source_shift) <= 30 and math.hypot(*candidate_shift) <= 30
        )
        if reliable:
            dx = candidate_shift[0] - source_shift[0] * scale
            dy = candidate_shift[1] - source_shift[1] * scale
            vectors[index - 1] = (dx, dy)
            magnitudes.append(math.hypot(dx, dy))
        prev_source, prev_candidate = current_source, current_candidate
    source.release()
    candidate.release()

    clip_limit = float(np.percentile(np.asarray(magnitudes), 99))
    freqs = np.fft.rfftfreq(WINDOW_FRAMES, d=1 / FPS)
    taper = np.hanning(WINDOW_FRAMES)
    sample_index = np.arange(WINDOW_FRAMES)
    band = (freqs >= 0.5) & (freqs <= 1.25)
    analysis_band = (freqs >= 0.5) & (freqs <= 10.0)
    rows = []
    rejected = 0
    for start in range(0, len(vectors) - WINDOW_FRAMES + 1, HOP_FRAMES):
        block = vectors[start:start + WINDOW_FRAMES].copy()
        valid = np.isfinite(block[:, 0]) & np.isfinite(block[:, 1])
        if int(valid.sum()) < 90:
            rejected += 1
            continue
        for axis in range(2):
            block[:, axis] = np.interp(sample_index, sample_index[valid], block[valid, axis])
        magnitude = np.linalg.norm(block, axis=1)
        over = magnitude > clip_limit
        if np.any(over):
            block[over] *= (clip_limit / magnitude[over])[:, None]
        design = np.column_stack([np.ones(WINDOW_FRAMES), sample_index])
        block -= design @ np.linalg.lstsq(design, block, rcond=None)[0]
        fft_x = np.fft.rfft(block[:, 0] * taper)
        fft_y = np.fft.rfft(block[:, 1] * taper)
        power = np.abs(fft_x) ** 2 + np.abs(fft_y) ** 2
        low_power = float(power[band].sum())
        usable_power = float(power[analysis_band].sum())
        dominant_index = int(np.where(analysis_band)[0][np.argmax(power[analysis_band])])
        rows.append({
            "start_seconds": start / FPS,
            "end_seconds": (start + WINDOW_FRAMES) / FPS,
            "valid_pairs": int(valid.sum()),
            "low_band_power_0p5_to_1p25hz": low_power,
            "low_band_fraction_0p5_to_10hz": low_power / usable_power if usable_power else 0.0,
            "dominant_frequency_hz": float(freqs[dominant_index]),
        })

    ranked = sorted(rows, key=lambda row: row["low_band_power_0p5_to_1p25hz"], reverse=True)
    non_overlapping = []
    for row in ranked:
        if all(row["end_seconds"] <= kept["start_seconds"] or row["start_seconds"] >= kept["end_seconds"] for kept in non_overlapping):
            non_overlapping.append(row)
        if len(non_overlapping) == 6:
            break
    report = {
        "schema": "e36_v18c_native24_low_frequency_drift_localization_v1",
        "source_cl2x": "CL2X-915",
        "source_mailbox_sha256": "e62dade34f0da40e44d35d0cf3d58099af66454180f169b6dc020f91a583d620",
        "source": {"path": str(SOURCE.relative_to(ROOT)), "sha256": sha256(SOURCE)},
        "candidate": {"path": str(CANDIDATE.relative_to(ROOT)), "sha256": sha256(CANDIDATE), "status": "REVERSIBLE_NOT_PROMOTED"},
        "scale_authority": {"path": str(PATH_AUDIT.relative_to(ROOT)), "sha256": sha256(PATH_AUDIT)},
        "spectrum_authority": {"path": str(SPECTRUM_AUDIT.relative_to(ROOT)), "sha256": sha256(SPECTRUM_AUDIT)},
        "sampling": {"fps": FPS, "frame_pairs": frame_count - 1, "reliable_pairs": int(np.isfinite(vectors[:, 0]).sum()), "window_seconds": 4.0, "hop_seconds": 2.0, "accepted_windows": len(rows), "rejected_windows": rejected},
        "preprocessing": {"minimum_reliable_pairs_per_window": 90, "vector_winsor_p99_px": clip_limit, "detrending": "REMOVE_WINDOW_MEAN_AND_LINEAR_RAMP", "taper": "HANN"},
        "low_frequency_band_hz": [0.5, 1.25],
        "strongest_non_overlapping_windows": non_overlapping,
        "aggregate_cross_check": {"dominant_frequency_hz": spectrum_audit["aggregate_spectrum"]["dominant_frequencies"][0]["frequency_hz"], "distinct_4hz_resonance": spectrum_audit["aggregate_spectrum"]["distinct_4hz_resonance"]},
        "method_limits": "Low-frequency phase energy can be intended pans, subject motion, cut transitions, crop drift or codec noise. This localizes review targets but cannot clear subjective comfort, lip sync or causal continuity.",
        "gate_results": {"native24_low_frequency_localization": "PASS", "target_windows": "PASS_6_NON_OVERLAPPING", "subjective_comfort": "NOT_CLEARED", "continuous_realtime_human_watch": "NOT_COMPLETE", "promotion": "NOT_GRANTED"},
        "credits": {"pay": 0, "refund": 0, "net": 0},
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT.relative_to(ROOT)), "sha256": sha256(OUTPUT), "accepted_windows": len(rows), "rejected_windows": rejected, "strongest_non_overlapping_windows": non_overlapping}))


if __name__ == "__main__":
    main()
