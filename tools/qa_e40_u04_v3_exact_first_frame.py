#!/usr/bin/env python3
"""Non-mutating exact-first-frame gate for E40 U04 V3."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
VIDEO = ROOT / "working_assets/e40_production_20260814/u04_v3_fast720/E40-U04-V3-FAST720-COHERENT-EXACT-FIRST-FRAME-FROST-RECEDE-SILENT-V1_03a0e327-56ff-4d12-ac25-19137127d6f8.mp4"
AUTHORITY = ROOT / "working_assets/e40_preproduction_20260814/u04_v2_imagegen_coherent_exact_start_frame_v1/E40_U04_V2_IMAGEGEN_COHERENT_EXACT_START_FRAME_720X1280_V1.png"
OUT_DIR = ROOT / "qa/e40_production_20260814/u04_v3_fast720_harvest_qa_v1"
REPORT = OUT_DIR / "E40_U04_V3_EXACT_FIRST_FRAME_GATE_V1.json"
COMPARE = OUT_DIR / "E40_U04_V3_AUTHORITY_VS_FRAME0_V1.png"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def ssim(a: np.ndarray, b: np.ndarray) -> float:
    """Return the established episode gate's global three-channel SSIM."""
    a = a.astype(np.float64)
    b = b.astype(np.float64)
    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2
    scores = []
    for channel in range(3):
        x = a[:, :, channel].reshape(-1)
        y = b[:, :, channel].reshape(-1)
        mu_x = float(np.mean(x))
        mu_y = float(np.mean(y))
        var_x = float(np.var(x))
        var_y = float(np.var(y))
        covariance = float(np.mean((x - mu_x) * (y - mu_y)))
        scores.append(
            ((2 * mu_x * mu_y + c1) * (2 * covariance + c2))
            / ((mu_x * mu_x + mu_y * mu_y + c1) * (var_x + var_y + c2))
        )
    return float(np.mean(scores))


def phash_bits(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
    low = cv2.dct(resized)[:8, :8]
    return low > np.median(low)


def metrics(a: np.ndarray, b: np.ndarray, flow: bool = False) -> dict:
    delta = np.abs(a.astype(np.float32) - b.astype(np.float32))
    mae = float(np.mean(delta))
    mse = float(np.mean((a.astype(np.float64) - b.astype(np.float64)) ** 2))
    result = {
        "mae": mae,
        "ssim": ssim(a, b),
        "phash_hamming": int(np.count_nonzero(phash_bits(a) != phash_bits(b))),
        "psnr_db": float("inf") if mse == 0 else float(10 * np.log10((255.0 ** 2) / mse)),
    }
    if flow:
        ga = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)
        gb = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY)
        optical = cv2.calcOpticalFlowFarneback(ga, gb, None, 0.5, 3, 15, 3, 5, 1.2, 0)
        result.update(
            {
                "mean_luma_jump": float(abs(float(np.mean(ga)) - float(np.mean(gb)))),
                "mean_optical_flow": float(np.mean(np.sqrt(optical[..., 0] ** 2 + optical[..., 1] ** 2))),
            }
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, default=VIDEO)
    parser.add_argument("--authority", type=Path, default=AUTHORITY)
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--compare", type=Path, default=COMPARE)
    args = parser.parse_args()
    video = args.video.resolve()
    authority_path = args.authority.resolve()
    report_path = args.report.resolve()
    compare_path = args.compare.resolve()
    if report_path.exists() or compare_path.exists():
        raise SystemExit("exact-frame artifacts already exist; repeat gate forbidden")
    authority = cv2.imread(str(authority_path), cv2.IMREAD_COLOR)
    if authority is None:
        raise SystemExit("authority image unreadable")
    capture = cv2.VideoCapture(str(video))
    frames = []
    for _ in range(14):
        ok, frame = capture.read()
        if not ok:
            break
        frames.append(frame)
    capture.release()
    if len(frames) < 2:
        raise SystemExit("video has fewer than two decoded frames")
    if authority.shape != frames[0].shape:
        raise SystemExit(f"authority/frame0 shape mismatch: {authority.shape} != {frames[0].shape}")
    frame0 = metrics(authority, frames[0])
    transition = metrics(frames[0], frames[1], flow=True)
    thresholds = {
        "minimum_frame0_ssim": 0.98,
        "maximum_frame0_mae": 3.0,
        "maximum_frame0_phash_hamming": 3,
        "maximum_transition_mae": 3.0,
        "maximum_transition_phash_hamming": 5,
        "maximum_transition_luma_jump": 3.0,
        "maximum_transition_mean_optical_flow": 1.0,
    }
    authority_pass = frame0["ssim"] >= 0.98 and frame0["mae"] <= 3.0 and frame0["phash_hamming"] <= 3
    transition_pass = (
        transition["mae"] <= 3.0
        and transition["phash_hamming"] <= 5
        and transition["mean_luma_jump"] <= 3.0
        and transition["mean_optical_flow"] <= 1.0
        and transition["mae"] > 0.01
    )
    baseline = [metrics(frames[index], frames[index + 1], flow=True) for index in range(1, len(frames) - 1)]
    baseline_medians = {
        key: float(np.median([row[key] for row in baseline]))
        for key in ("mae", "phash_hamming", "mean_luma_jump", "mean_optical_flow")
    }
    diff = cv2.absdiff(authority, frames[0])
    compare_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(compare_path), np.hstack([authority, frames[0], diff]))
    payload = {
        "schema": "backlotos.exact_first_frame_post_harvest_gate.v1",
        "status": "PASS" if authority_pass and transition_pass else "FAIL",
        "frame0_authority": {"status": "PASS" if authority_pass else "FAIL", "metrics": frame0},
        "frame0_to_frame1_continuity": {
            "status": "PASS" if transition_pass else "FAIL",
            "operands": ["decoded_frame0", "decoded_frame1"],
            "metrics": transition,
        },
        "baseline_medians": baseline_medians,
        "thresholds": thresholds,
        "automatic_repair": "FORBIDDEN_NO_PREPEND_NO_REPLACEMENT",
        "video": str(video),
        "video_sha256": digest(video),
        "authority_image": str(authority_path),
        "authority_image_sha256": digest(authority_path),
        "comparison_image": str(compare_path.relative_to(ROOT)),
        "comparison_image_sha256": digest(compare_path),
        "human_review_required": [
            "double silhouette or duplicate edge",
            "one-frame exposure flash",
            "pose teleport or camera/crop jump",
            "hand/frost owner-count-transfer discontinuity",
        ],
        "policy": "This gate never mutates media. A failure is preserved and classified before any retry.",
    }
    atomic_json(report_path, payload)
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
