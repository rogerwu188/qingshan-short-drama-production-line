#!/usr/bin/env python3
"""Measure whether V18C adds a distinct 4 Hz reframe oscillation over V15."""

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
PHASE_AUDIT = ROOT / "qa/e36_agentcut_20260730/E36_V18C_FULL_NATIVE24_PHASE_MOTION_DIAGNOSTIC_V1.json"
OUTPUT = ROOT / "qa/e36_agentcut_20260730/E36_V18C_NATIVE24_MOTION_SPECTRUM_DIAGNOSTIC_V1.json"
WIDTH, HEIGHT, FPS = 180, 320, 24
WINDOW_FRAMES, HOP_FRAMES = 96, 48


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def percentile(values: list[float], q: float) -> float:
    return float(np.percentile(np.asarray(values), q)) if values else 0.0


def main() -> None:
    path_audit = json.loads(PATH_AUDIT.read_text(encoding="utf-8"))
    phase_audit = json.loads(PHASE_AUDIT.read_text(encoding="utf-8"))
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
    magnitudes = []
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
    spectrum_sum = np.zeros_like(freqs)
    accepted_windows = []
    rejected_windows = 0
    taper = np.hanning(WINDOW_FRAMES)
    sample_index = np.arange(WINDOW_FRAMES)
    for start in range(0, len(vectors) - WINDOW_FRAMES + 1, HOP_FRAMES):
        block = vectors[start:start + WINDOW_FRAMES].copy()
        valid = np.isfinite(block[:, 0]) & np.isfinite(block[:, 1])
        if int(valid.sum()) < 90:
            rejected_windows += 1
            continue
        for axis in range(2):
            block[:, axis] = np.interp(sample_index, sample_index[valid], block[valid, axis])
        magnitude = np.linalg.norm(block, axis=1)
        over = magnitude > clip_limit
        if np.any(over):
            block[over] *= (clip_limit / magnitude[over])[:, None]
        # Remove constant drift and linear ramps before looking for periodic energy.
        design = np.column_stack([np.ones(WINDOW_FRAMES), sample_index])
        block -= design @ np.linalg.lstsq(design, block, rcond=None)[0]
        fft_x = np.fft.rfft(block[:, 0] * taper)
        fft_y = np.fft.rfft(block[:, 1] * taper)
        power = np.abs(fft_x) ** 2 + np.abs(fft_y) ** 2
        spectrum_sum += power
        target = int(np.argmin(np.abs(freqs - 4.0)))
        usable = (freqs >= 0.5) & (freqs <= 10.0)
        usable_power = power[usable]
        target_power = float(power[target])
        accepted_windows.append({
            "start_seconds": start / FPS,
            "end_seconds": (start + WINDOW_FRAMES) / FPS,
            "valid_pairs": int(valid.sum()),
            "power_4hz": target_power,
            "power_4hz_fraction_0p5_to_10hz": target_power / float(usable_power.sum()) if usable_power.sum() else 0.0,
        })

    usable_indices = np.where((freqs >= 0.5) & (freqs <= 10.0))[0]
    ranked = sorted(usable_indices, key=lambda i: float(spectrum_sum[i]), reverse=True)
    target = int(np.argmin(np.abs(freqs - 4.0)))
    target_rank = ranked.index(target) + 1
    target_power = float(spectrum_sum[target])
    usable_power = [float(spectrum_sum[i]) for i in usable_indices]
    target_percentile = 100.0 * sum(v <= target_power for v in usable_power) / len(usable_power)
    neighbors = [i for i in usable_indices if 3.25 <= freqs[i] <= 4.75 and i != target]
    neighbor_median = float(np.median([spectrum_sum[i] for i in neighbors]))
    dominant = [{"frequency_hz": float(freqs[i]), "power": float(spectrum_sum[i]), "relative_to_4hz": float(spectrum_sum[i] / target_power) if target_power else None} for i in ranked[:12]]
    strongest_4hz_windows = sorted(accepted_windows, key=lambda row: row["power_4hz_fraction_0p5_to_10hz"], reverse=True)[:20]
    distinct_4hz = target_rank <= 3 and target_power >= 2.0 * neighbor_median
    report = {
        "schema": "e36_v18c_native24_motion_spectrum_diagnostic_v1",
        "source_cl2x": "CL2X-914",
        "source_mailbox_sha256": "fea59b5aa15786cd2e1224d9c4e5fca57f6d07f80a2e8c132495d43e6f4050b0",
        "source": {"path": str(SOURCE.relative_to(ROOT)), "sha256": sha256(SOURCE)},
        "candidate": {"path": str(CANDIDATE.relative_to(ROOT)), "sha256": sha256(CANDIDATE), "status": "REVERSIBLE_NOT_PROMOTED"},
        "scale_authority": {"path": str(PATH_AUDIT.relative_to(ROOT)), "sha256": sha256(PATH_AUDIT)},
        "phase_authority": {"path": str(PHASE_AUDIT.relative_to(ROOT)), "sha256": sha256(PHASE_AUDIT)},
        "sampling": {"fps": FPS, "frame_pairs": frame_count - 1, "reliable_pairs": int(np.isfinite(vectors[:, 0]).sum()), "window_frames": WINDOW_FRAMES, "window_seconds": WINDOW_FRAMES / FPS, "hop_frames": HOP_FRAMES, "hop_seconds": HOP_FRAMES / FPS, "accepted_windows": len(accepted_windows), "rejected_windows": rejected_windows, "frequency_resolution_hz": FPS / WINDOW_FRAMES},
        "preprocessing": {"missing_pairs": "LINEAR_INTERPOLATION_ONLY_WHEN_AT_LEAST_90_OF_96_PAIRS_RELIABLE", "cut_and_outlier_control": f"VECTOR_MAGNITUDE_WINSORIZED_AT_GLOBAL_P99_{clip_limit:.6f}PX", "detrending": "REMOVE_WINDOW_MEAN_AND_LINEAR_RAMP", "taper": "HANN"},
        "aggregate_spectrum": {
            "analysis_band_hz": [0.5, 10.0],
            "target_frequency_hz": float(freqs[target]),
            "target_power": target_power,
            "target_rank_in_band": target_rank,
            "frequency_bin_count_in_band": len(usable_indices),
            "target_power_percentile_in_band": target_percentile,
            "target_to_local_neighbor_median_ratio": target_power / neighbor_median if neighbor_median else None,
            "dominant_frequencies": dominant,
            "distinct_4hz_resonance": distinct_4hz,
        },
        "strongest_4hz_windows": strongest_4hz_windows,
        "cross_check": {"lag6_vector_autocorrelation": phase_audit["aggregate"]["quarter_second_lag6"]["vector_autocorrelation"], "interpretation": "Broad positive autocorrelation can coexist with low-frequency drift; spectral rank tests whether 4Hz is a distinct resonance rather than a sampling artifact."},
        "method_limits": "Phase-derived global translation remains confounded by subject motion, scene cuts, crop-scale interpolation and codec noise. This test can reject or support a distinct 4Hz mechanism but cannot clear subjective comfort or continuous audiovisual review.",
        "gate_results": {
            "native_rate_spectrum": "PASS",
            "quarter_second_aliasing": "BYPASSED_24FPS_WITH_4_SECOND_HANN_WINDOWS",
            "distinct_4hz_reframe_resonance": "SUPPORTED" if distinct_4hz else "NOT_SUPPORTED",
            "subjective_comfort": "NOT_CLEARED",
            "continuous_realtime_human_watch": "NOT_COMPLETE",
            "promotion": "NOT_GRANTED",
        },
        "credits": {"pay": 0, "refund": 0, "net": 0},
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT.relative_to(ROOT)), "sha256": sha256(OUTPUT), "accepted_windows": len(accepted_windows), "target_rank": target_rank, "target_percentile": target_percentile, "target_neighbor_ratio": report["aggregate_spectrum"]["target_to_local_neighbor_median_ratio"], "distinct_4hz": distinct_4hz}))


if __name__ == "__main__":
    main()
