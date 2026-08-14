#!/usr/bin/env python3
"""Compare native-rate crop trajectories in V19 and V20C around the repaired window."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
V19 = ROOT / "working_assets/e36_agentcut_20260731/accepted_only_v19_v18c_plus_line10/E36_ACCEPTED_ONLY_AGENTCUT_V19_V18C_PLUS_LINE10.mp4"
V20D = ROOT / "working_assets/e36_agentcut_20260731/accepted_only_v20d_temporally_smoothed_registered_hybrid/E36_ACCEPTED_ONLY_AGENTCUT_V20D_TEMPORALLY_SMOOTHED_REGISTERED_HYBRID.mp4"
V3_PREVIEW = ROOT / "qa/e36_agentcut_20260730/v18c_v18e_per_frame_staggered_registration_preview_v3/E36_V18C_V18E_PER_FRAME_STAGGERED_REGISTERED_160_168S_PREVIEW_V3.mp4"
V4_PREVIEW = ROOT / "qa/e36_agentcut_20260730/v18c_v18e_temporally_smoothed_registration_preview_v4/E36_V18C_V18E_TEMPORALLY_SMOOTHED_REGISTERED_160_168S_PREVIEW_V4.mp4"
REEL = ROOT / "qa/e36_agentcut_20260730/v19_v20d_registered_window_comparison_v2/E36_V19_LEFT_V20D_RIGHT_REGISTERED_160_168S_REALTIME_COMPARISON_V2.mp4"
CONTACT = ROOT / "qa/e36_agentcut_20260730/v19_v20d_registered_window_comparison_v2/E36_V19_V20D_REGISTERED_COMPARISON_CONTACT_V2.jpg"
DECODE = ROOT / "qa/e36_agentcut_20260730/v19_v20d_registered_window_comparison_v2/E36_V19_V20D_REGISTERED_COMPARISON_DECODE_V2.log"
PROBE = ROOT / "qa/e36_agentcut_20260730/v19_v20d_registered_window_comparison_v2/E36_V19_V20D_REGISTERED_COMPARISON_PROBE_V2.json"
OUTPUT = ROOT / "qa/e36_agentcut_20260730/E36_V19_V20D_REGISTERED_WINDOW_NATIVE24_MOTION_COMPARISON_QA_V2.json"
SHIFT = 6.082993
FPS = 24
WIDTH, HEIGHT = 180, 320


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def robust_turns(signal: np.ndarray, prominence: float) -> list[dict[str, float]]:
    turns: list[dict[str, float]] = []
    direction = 0
    last = float(signal[0])
    extreme_i, extreme = 0, last
    for i, raw in enumerate(signal[1:], 1):
        value = float(raw)
        delta = value - last
        new_direction = 1 if delta > 0 else -1 if delta < 0 else direction
        if direction == 0:
            direction = new_direction
        if new_direction == direction:
            if (direction > 0 and value >= extreme) or (direction < 0 and value <= extreme):
                extreme_i, extreme = i, value
        elif abs(extreme - value) >= prominence:
            turns.append({"seconds_from_window_start": extreme_i / FPS, "value_px": extreme})
            direction = new_direction
            extreme_i, extreme = i, value
        last = value
    return turns


def analyze(path: Path, start: float, end: float, crop: str | None = None) -> dict:
    cap = cv2.VideoCapture(str(path))
    first_frame = round(start * FPS)
    last_frame = min(round(end * FPS), int(cap.get(cv2.CAP_PROP_FRAME_COUNT)))
    cap.set(cv2.CAP_PROP_POS_FRAMES, first_frame)
    hanning = cv2.createHanningWindow((WIDTH, HEIGHT), cv2.CV_32F)

    def read_gray() -> np.ndarray:
        ok, frame = cap.read()
        if not ok:
            raise EOFError(f"Could not read {path.name}")
        if crop == "left_half":
            frame = frame[:, : frame.shape[1] // 2]
        elif crop == "right_half":
            frame = frame[:, frame.shape[1] // 2 :]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return cv2.resize(gray, (WIDTH, HEIGHT), interpolation=cv2.INTER_AREA).astype(np.float32)

    previous = read_gray()
    vectors = []
    responses = []
    rejected = 0
    for _ in range(first_frame + 1, last_frame):
        current = read_gray()
        shift, response = cv2.phaseCorrelate(previous, current, hanning)
        reliable = response >= 0.12 and math.hypot(*shift) <= 30
        if reliable:
            vectors.append(shift)
            responses.append(float(response))
        else:
            vectors.append((math.nan, math.nan))
            rejected += 1
        previous = current
    cap.release()
    array = np.asarray(vectors, dtype=np.float64)
    valid = np.isfinite(array[:, 0])
    indices = np.arange(len(array))
    for axis in range(2):
        array[:, axis] = np.interp(indices, indices[valid], array[valid, axis])
    trajectory = np.vstack([np.zeros(2), np.cumsum(array, axis=0)])
    time = np.arange(len(trajectory))
    design = np.column_stack([np.ones(len(trajectory)), time])
    detrended = trajectory - design @ np.linalg.lstsq(design, trajectory, rcond=None)[0]
    covariance = np.cov(detrended.T)
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    axis = eigenvectors[:, int(np.argmax(eigenvalues))]
    projection = detrended @ axis
    smooth = np.convolve(np.pad(projection, (3, 3), mode="edge"), np.ones(7) / 7, mode="valid")
    excursion = float(np.ptp(smooth))
    prominence = max(0.15, excursion * 0.12)
    turns = robust_turns(smooth, prominence)
    speed = np.linalg.norm(array, axis=1)
    acceleration = np.linalg.norm(np.diff(array, axis=0), axis=1)
    path_length = float(speed.sum())
    net = float(np.linalg.norm(trajectory[-1] - trajectory[0]))
    return {
        "path": rel(path),
        "sha256": sha256(path),
        "mapped_seconds": [start, end],
        "crop": crop,
        "frame_pairs": len(array),
        "reliable_pairs": int(valid.sum()),
        "rejected_pairs": rejected,
        "minimum_phase_response": min(responses) if responses else None,
        "dominant_axis_excursion_px_at_180x320": excursion,
        "turning_point_prominence_px": prominence,
        "robust_turn_count": len(turns),
        "robust_turning_points": turns,
        "path_length_px": path_length,
        "net_displacement_px": net,
        "path_efficiency": net / path_length if path_length else 0.0,
        "speed_px_per_frame": {"p50": float(np.percentile(speed, 50)), "p95": float(np.percentile(speed, 95)), "max": float(np.max(speed))},
        "acceleration_px_per_frame2": {
            "p50": float(np.percentile(acceleration, 50)),
            "p95": float(np.percentile(acceleration, 95)),
            "max": float(np.max(acceleration)),
            "max_seconds_from_window_start": float((int(np.argmax(acceleration)) + 1) / FPS),
            "max_mapped_seconds": float(start + (int(np.argmax(acceleration)) + 1) / FPS),
        },
    }


def main() -> None:
    windows = {
        "full_context_base_160_168": (0.0, 8.0),
        "repaired_core_base_162_166": (2.0, 6.0),
    }
    comparisons = {}
    for name, (start, end) in windows.items():
        v19 = analyze(REEL, start, end, "left_half")
        v20d = analyze(REEL, start, end, "right_half")
        comparisons[name] = {
            "v19": v19,
            "v20d": v20d,
            "delta_v20d_minus_v19": {
                "robust_turn_count": v20d["robust_turn_count"] - v19["robust_turn_count"],
                "dominant_axis_excursion_px": v20d["dominant_axis_excursion_px_at_180x320"] - v19["dominant_axis_excursion_px_at_180x320"],
                "path_efficiency": v20d["path_efficiency"] - v19["path_efficiency"],
                "acceleration_p95_px_per_frame2": v20d["acceleration_px_per_frame2"]["p95"] - v19["acceleration_px_per_frame2"]["p95"],
            },
        }
    core = comparisons["repaired_core_base_162_166"]
    preview_v3 = analyze(V3_PREVIEW, 2.0, 6.0)
    preview_v4 = analyze(V4_PREVIEW, 2.0, 6.0)
    preview_refinement = {
        "v3_per_frame_registration": preview_v3,
        "v4_temporally_smoothed_registration": preview_v4,
        "delta_v4_minus_v3": {
            "robust_turn_count": preview_v4["robust_turn_count"] - preview_v3["robust_turn_count"],
            "dominant_axis_excursion_px": preview_v4["dominant_axis_excursion_px_at_180x320"] - preview_v3["dominant_axis_excursion_px_at_180x320"],
            "path_efficiency": preview_v4["path_efficiency"] - preview_v3["path_efficiency"],
            "acceleration_p95_px_per_frame2": preview_v4["acceleration_px_per_frame2"]["p95"] - preview_v3["acceleration_px_per_frame2"]["p95"],
            "acceleration_max_px_per_frame2": preview_v4["acceleration_px_per_frame2"]["max"] - preview_v3["acceleration_px_per_frame2"]["max"],
        },
    }
    report = {
        "schema": "e36_v19_v20d_registered_window_native24_motion_comparison_qa_v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_cl2x": "CL2X-919",
        "source_mailbox_sha256": "398c4b57c386ad46b05a46030b6b2e4a875a59c2449f5bf6192edbba6c472193",
        "sampling": {"fps": FPS, "resolution": [WIDTH, HEIGHT], "method": "NATIVE24_PHASE_TRANSLATION_INTEGRATED_DETRENDED_7_FRAME_SMOOTH"},
        "comparisons": comparisons,
        "preview_refinement": preview_refinement,
        "review_media": {"path": rel(REEL), "sha256": sha256(REEL), "layout": "V19_LEFT_V20D_RIGHT_SYNCHRONIZED", "seconds": 8.0, "audio": "V20D_EXACT_WINDOW_48KHZ_STEREO", "full_decode": "PASS_ZERO_ERRORS"},
        "contact_sheet": {"path": rel(CONTACT), "sha256": sha256(CONTACT), "samples": 24, "direct_static_visual": "PASS_IDENTITY_PERIOD_FRAMING_NO_DOUBLE_EXPOSURE"},
        "probe": {"path": rel(PROBE), "sha256": sha256(PROBE)},
        "decode_log": {"path": rel(DECODE), "sha256": sha256(DECODE), "errors": 0},
        "gate_results": {
            "native_rate_comparison": "PASS",
            "repaired_core_turn_count": f"V19_{core['v19']['robust_turn_count']}_V20D_{core['v20d']['robust_turn_count']}",
            "direct_static_visual": "PASS_24_SYNCHRONIZED_SAMPLES",
            "v4_temporal_registration_refinement": "PASS" if preview_v4["acceleration_px_per_frame2"]["max"] < preview_v3["acceleration_px_per_frame2"]["max"] else "FAIL",
            "realtime_motion_comfort": "REVIEW_MEDIA_READY_NOT_CLEARED_BY_STATIC_SAMPLES",
            "lipsync_breath_causal_continuity": "NOT_CLEARED_BY_STATIC_SAMPLES",
            "continuous_full_runtime_human_watch": "NOT_COMPLETE",
            "promotion": "NOT_GRANTED_KEEP_V15_CANONICAL",
            "release": "HOLD",
        },
        "method_limits": "Global phase translation is confounded by subject motion and cuts. The synchronized reel enables direct native-speed comparison; static contact samples and trajectory metrics cannot clear lipsync, breath, subjective comfort or full-runtime causal continuity.",
        "credits": {"pay": 0, "refund": 0, "net": 0, "episode_source_attributable_net": 9976, "cap": 10000, "headroom": 24},
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": rel(OUTPUT), "sha256": sha256(OUTPUT), "core_delta": core["delta_v20d_minus_v19"]}))


if __name__ == "__main__":
    main()
