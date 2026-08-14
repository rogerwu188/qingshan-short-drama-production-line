#!/usr/bin/env python3
"""Full-runtime native-frame phase-motion diagnostic for V15 versus V18C."""

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
OUTPUT = ROOT / "qa/e36_agentcut_20260730/E36_V18C_FULL_NATIVE24_PHASE_MOTION_DIAGNOSTIC_V1.json"
WIDTH, HEIGHT = 180, 320


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def percentile(values: list[float], q: float) -> float:
    return float(np.percentile(np.asarray(values), q)) if values else 0.0


def autocorrelation(vectors: dict[int, tuple[float, float]], lag: int) -> dict:
    dots = left_energy = right_energy = 0.0
    count = 0
    for index, current in vectors.items():
        previous = vectors.get(index - lag)
        if previous is None:
            continue
        dots += previous[0] * current[0] + previous[1] * current[1]
        left_energy += previous[0] ** 2 + previous[1] ** 2
        right_energy += current[0] ** 2 + current[1] ** 2
        count += 1
    value = dots / math.sqrt(left_energy * right_energy) if left_energy and right_energy else 0.0
    return {"lag_frames": lag, "lag_seconds": lag / 24.0, "pair_count": count, "vector_autocorrelation": value}


def main() -> None:
    path_audit = json.loads(PATH_AUDIT.read_text(encoding="utf-8"))
    scale_records = path_audit["sampling_records"]
    source = cv2.VideoCapture(str(SOURCE))
    candidate = cv2.VideoCapture(str(CANDIDATE))
    frame_count = min(int(source.get(cv2.CAP_PROP_FRAME_COUNT)), int(candidate.get(cv2.CAP_PROP_FRAME_COUNT)))
    if frame_count != 6751:
        raise SystemExit(f"unexpected frame count {frame_count}")
    window = cv2.createHanningWindow((WIDTH, HEIGHT), cv2.CV_32F)

    def read_gray(cap: cv2.VideoCapture) -> np.ndarray:
        ok, frame = cap.read()
        if not ok:
            raise EOFError
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return cv2.resize(gray, (WIDTH, HEIGHT), interpolation=cv2.INTER_AREA).astype(np.float32)

    prev_source, prev_candidate = read_gray(source), read_gray(candidate)
    vectors: dict[int, tuple[float, float]] = {}
    records = []
    top = []
    for index in range(1, frame_count):
        current_source, current_candidate = read_gray(source), read_gray(candidate)
        source_shift, source_response = cv2.phaseCorrelate(prev_source, current_source, window)
        candidate_shift, candidate_response = cv2.phaseCorrelate(prev_candidate, current_candidate, window)
        timestamp = index / 24.0
        scale = float(scale_records[min(len(scale_records) - 1, round(timestamp / 0.5))]["scale"])
        reliable = (
            source_response >= 0.12
            and candidate_response >= 0.12
            and math.hypot(*source_shift) <= 30
            and math.hypot(*candidate_shift) <= 30
        )
        if reliable:
            dx = candidate_shift[0] - source_shift[0] * scale
            dy = candidate_shift[1] - source_shift[1] * scale
            magnitude = math.hypot(dx, dy)
            vectors[index] = (dx, dy)
            item = {"frame": index, "time_seconds": timestamp, "dx": dx, "dy": dy, "translation": magnitude, "source_response": source_response, "candidate_response": candidate_response, "cross_scale": scale}
            records.append(item)
            top.append(item)
        prev_source, prev_candidate = current_source, current_candidate
    source.release()
    candidate.release()
    translations = [item["translation"] for item in records]
    top = sorted(top, key=lambda item: item["translation"], reverse=True)[:100]
    per_second = []
    for second in range(math.ceil((frame_count - 1) / 24)):
        values = [item["translation"] for item in records if second <= item["time_seconds"] < second + 1]
        if values:
            per_second.append({"second": second, "reliable_pairs": len(values), "p50": percentile(values, 50), "p95": percentile(values, 95), "max": max(values)})
    lag_results = [autocorrelation(vectors, lag) for lag in range(1, 13)]
    report = {
        "schema": "e36_v18c_full_native24_phase_motion_diagnostic_v1",
        "source_cl2x": "CL2X-913",
        "source_mailbox_sha256": "6e4678c691873227857cbbe804617d64930b1df18e79d1039174e11ddb6b4632",
        "source": {"path": str(SOURCE.relative_to(ROOT)), "sha256": sha256(SOURCE)},
        "candidate": {"path": str(CANDIDATE.relative_to(ROOT)), "sha256": sha256(CANDIDATE), "status": "REVERSIBLE_NOT_PROMOTED"},
        "scale_authority": {"path": str(PATH_AUDIT.relative_to(ROOT)), "sha256": sha256(PATH_AUDIT)},
        "sampling": {"frame_rate": 24, "interval_seconds": 1 / 24, "frame_count": frame_count, "pair_count": frame_count - 1, "analysis_size": [WIDTH, HEIGHT]},
        "aggregate": {
            "reliable_pair_count": len(records),
            "reliable_pair_ratio": len(records) / (frame_count - 1),
            "excess_translation_px_at_180x320": {"p50": percentile(translations, 50), "p90": percentile(translations, 90), "p95": percentile(translations, 95), "p99": percentile(translations, 99), "max": max(translations, default=0.0)},
            "lag_autocorrelation_1_to_12_frames": lag_results,
            "quarter_second_lag6": lag_results[5],
        },
        "largest_excess_motion_pairs": top,
        "per_second": per_second,
        "method": {
            "motion": "Hanning-window phase correlation on every decoded frame",
            "attribution": "candidate translation minus source translation multiplied by nearest 0.5-second empirical crop scale",
            "reliability": "both phase responses at least0.12 and both translations at most30px at180x320",
            "aliasing": "1/24-second sampling supplies six samples per suspected 0.25-second period",
            "limitations": "Subject motion, scene cuts, scale interpolation and phase-estimation error remain confounds. Metrics localize motion frequency and cannot decide subjective comfort.",
        },
        "gate_results": {
            "full_runtime_native_rate_sampling": "PASS_24FPS_6750_PAIRS",
            "quarter_second_visual_aliasing": "BYPASSED_WITH_SIX_SAMPLES_PER_PERIOD",
            "reliable_pair_ratio": "PASS" if len(records) / (frame_count - 1) >= 0.70 else "FAIL_LOW_RELIABILITY",
            "subjective_comfort": "NOT_CLEARED",
            "continuous_realtime_human_watch": "NOT_COMPLETE",
            "promotion": "NOT_GRANTED",
        },
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT.relative_to(ROOT)), "sha256": sha256(OUTPUT), "reliable": len(records), "pairs": frame_count - 1, "p95": report["aggregate"]["excess_translation_px_at_180x320"]["p95"], "lag6": report["aggregate"]["quarter_second_lag6"]["vector_autocorrelation"]}))


if __name__ == "__main__":
    main()
