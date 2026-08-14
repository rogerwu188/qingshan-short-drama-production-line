#!/usr/bin/env python3
"""Measure V18C/V18E boundary mismatch and render a registered 8-second preview."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import cv2
import imageio_ffmpeg
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
V18C = ROOT / "working_assets/e36_agentcut_20260731/accepted_only_v18_zero_credit_dynamic_reframe_probe/E36_ACCEPTED_ONLY_AGENTCUT_V18C_TWO_PART_DYNAMIC_REFRAME_EXACT_V15_AUDIO_PROBE.mp4"
V18E = ROOT / "working_assets/e36_agentcut_20260731/accepted_only_v18e_cut_aware_zero_velocity_cycle_probe/E36_ACCEPTED_ONLY_AGENTCUT_V18E_CUT_AWARE_ZERO_VELOCITY_CYCLE_EXACT_V15_AUDIO_PROBE.mp4"
OUT_DIR = ROOT / "qa/e36_agentcut_20260730/v18c_v18e_temporally_smoothed_registration_preview_v4"
PREVIEW = OUT_DIR / "E36_V18C_V18E_TEMPORALLY_SMOOTHED_REGISTERED_160_168S_PREVIEW_V4.mp4"
CONTACT = OUT_DIR / "E36_V18C_V18E_TEMPORALLY_SMOOTHED_REGISTERED_BOUNDARY_CONTACT_V4.jpg"
DECODE = OUT_DIR / "E36_V18C_V18E_TEMPORALLY_SMOOTHED_REGISTERED_PREVIEW_DECODE_V4.log"
REPORT = ROOT / "qa/e36_agentcut_20260730/E36_V18C_V18E_TEMPORALLY_SMOOTHED_BOUNDARY_REGISTRATION_QA_V4.json"
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

FPS = 24.0
PREVIEW_START = 160.0
PREVIEW_END = 168.0
WINDOW_START = 162.0
WINDOW_END = 166.0
RAMP = 0.5
SCALE = 0.5


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def read_frame(cap: cv2.VideoCapture, seconds: float) -> np.ndarray:
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(seconds * FPS)))
    ok, frame = cap.read()
    if not ok:
        raise RuntimeError(f"Could not read frame at {seconds:.6f}s")
    return frame


def gray_small(frame: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return cv2.resize(gray, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0


def estimate_affine(template: np.ndarray, moving: np.ndarray) -> tuple[np.ndarray, float, tuple[float, float], float]:
    t = gray_small(template)
    m = gray_small(moving)
    hann = cv2.createHanningWindow((t.shape[1], t.shape[0]), cv2.CV_32F)
    phase_shift, phase_response = cv2.phaseCorrelate(t, m, hann)
    warp = np.eye(2, 3, dtype=np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 150, 1e-6)
    ecc, warp = cv2.findTransformECC(t, m, warp, cv2.MOTION_AFFINE, criteria, None, 3)
    warp[0, 2] /= SCALE
    warp[1, 2] /= SCALE
    return warp, float(ecc), (float(phase_shift[0] / SCALE), float(phase_shift[1] / SCALE)), float(phase_response)


def warp_to_template(frame: np.ndarray, warp: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    return cv2.warpAffine(
        frame,
        warp,
        size,
        flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
        borderMode=cv2.BORDER_REFLECT_101,
    )


def central_mae(a: np.ndarray, b: np.ndarray) -> float:
    h, w = a.shape[:2]
    y0, y1 = h // 8, h - h // 8
    x0, x1 = w // 10, w - w // 10
    ag = cv2.cvtColor(a[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY).astype(np.float32)
    bg = cv2.cvtColor(b[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY).astype(np.float32)
    return float(np.mean(np.abs(ag - bg)))


def blend_weight(seconds: float) -> float:
    if seconds < WINDOW_START or seconds >= WINDOW_END:
        return 0.0
    if seconds < WINDOW_START + RAMP:
        return 0.5 - 0.5 * math.cos(math.pi * (seconds - WINDOW_START) / RAMP)
    if seconds >= WINDOW_END - RAMP:
        return 0.5 + 0.5 * math.cos(math.pi * (seconds - (WINDOW_END - RAMP)) / RAMP)
    return 1.0


def registration_weight(seconds: float) -> float:
    """Apply geometry before/after blends so aligned and raw images are never mixed."""
    if WINDOW_START <= seconds < WINDOW_START + RAMP:
        return 1.0
    if WINDOW_START + RAMP <= seconds < WINDOW_START + 2.0 * RAMP:
        return 0.5 + 0.5 * math.cos(math.pi * (seconds - (WINDOW_START + RAMP)) / RAMP)
    if WINDOW_END - 2.0 * RAMP <= seconds < WINDOW_END - RAMP:
        return 0.5 - 0.5 * math.cos(math.pi * (seconds - (WINDOW_END - 2.0 * RAMP)) / RAMP)
    if WINDOW_END - RAMP <= seconds < WINDOW_END:
        return 1.0
    return 0.0


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cap_c = cv2.VideoCapture(str(V18C))
    cap_e = cv2.VideoCapture(str(V18E))
    if not cap_c.isOpened() or not cap_e.isOpened():
        raise RuntimeError("Could not open source videos")
    width = int(cap_c.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap_c.get(cv2.CAP_PROP_FRAME_HEIGHT))

    boundary = {}
    matrices = {}
    for label, seconds in (("start", WINDOW_START), ("end", WINDOW_END - 1.0 / FPS)):
        c = read_frame(cap_c, seconds)
        e = read_frame(cap_e, seconds)
        warp, ecc, phase_shift, phase_response = estimate_affine(c, e)
        registered = warp_to_template(e, warp, (width, height))
        raw_mae = central_mae(c, e)
        registered_mae = central_mae(c, registered)
        matrices[label] = warp
        boundary[label] = {
            "base_seconds": seconds,
            "ecc": ecc,
            "phase_translation_full_resolution_px": [round(phase_shift[0], 4), round(phase_shift[1], 4)],
            "phase_response": phase_response,
            "affine_moving_v18e_to_template_v18c": [[round(float(v), 8) for v in row] for row in warp],
            "central_grayscale_mae_raw": round(raw_mae, 6),
            "central_grayscale_mae_registered": round(registered_mae, 6),
            "mae_reduction_fraction": round((raw_mae - registered_mae) / raw_mae, 6) if raw_mae else 0.0,
        }

    frame_count = int(round((PREVIEW_END - PREVIEW_START) * FPS))
    registration_warps = np.repeat(np.eye(2, 3, dtype=np.float32)[None, :, :], frame_count, axis=0)
    for index in range(frame_count):
        seconds = PREVIEW_START + index / FPS
        if registration_weight(seconds):
            c = read_frame(cap_c, seconds)
            e = read_frame(cap_e, seconds)
            registration_warps[index], _, _, _ = estimate_affine(c, e)
    for segment_start, segment_end in ((48, 72), (120, 144)):
        segment = registration_warps[segment_start:segment_end]
        for row in range(2):
            for col in range(3):
                padded = np.pad(segment[:, row, col], (3, 3), mode="edge")
                registration_warps[segment_start:segment_end, row, col] = np.convolve(padded, np.ones(7) / 7, mode="valid")

    frame_dir = Path(tempfile.mkdtemp(prefix="e36_reg_frames_", dir=str(OUT_DIR)))
    preview_frames: list[np.ndarray] = []
    try:
        for index in range(frame_count):
            seconds = PREVIEW_START + index / FPS
            c = read_frame(cap_c, seconds)
            e = read_frame(cap_e, seconds)
            reg_weight = registration_weight(seconds)
            per_frame_warp = registration_warps[index]
            warp = np.eye(2, 3, dtype=np.float32) * (1.0 - reg_weight) + per_frame_warp * reg_weight
            registered = warp_to_template(e, warp, (width, height))
            weight = blend_weight(seconds)
            output = cv2.addWeighted(c, 1.0 - weight, registered, weight, 0.0) if weight else c
            preview_frames.append(output)
            if not cv2.imwrite(str(frame_dir / f"frame_{index:04d}.jpg"), output, [cv2.IMWRITE_JPEG_QUALITY, 96]):
                raise RuntimeError("Could not write preview frame")

        temp_preview = PREVIEW.with_suffix(".tmp.mp4")
        subprocess.run([
            FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
            "-framerate", "24", "-i", str(frame_dir / "frame_%04d.jpg"),
            "-ss", str(PREVIEW_START), "-t", str(PREVIEW_END - PREVIEW_START), "-i", str(V18C),
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "h264_videotoolbox", "-b:v", "8M",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", "-shortest", str(temp_preview),
        ], check=True)
        temp_preview.replace(PREVIEW)

        sample_times = [161.75, 161.875, 162.0, 162.125, 162.25, 162.375,
                        162.5, 163.0, 164.0, 165.0, 165.5, 165.625,
                        165.75, 165.875, 165.958333, 166.0, 166.125, 166.25]
        thumbs = []
        for seconds in sample_times:
            idx = min(len(preview_frames) - 1, max(0, int(round((seconds - PREVIEW_START) * FPS))))
            thumb = cv2.resize(preview_frames[idx], (180, 320), interpolation=cv2.INTER_AREA)
            cv2.rectangle(thumb, (0, 0), (180, 24), (0, 0, 0), -1)
            cv2.putText(thumb, f"base {seconds:.3f}s", (5, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1, cv2.LINE_AA)
            thumbs.append(thumb)
        sheet = np.zeros((3 * 320, 6 * 180, 3), dtype=np.uint8)
        for i, thumb in enumerate(thumbs):
            sheet[(i // 6) * 320:(i // 6 + 1) * 320, (i % 6) * 180:(i % 6 + 1) * 180] = thumb
        if not cv2.imwrite(str(CONTACT), sheet, [cv2.IMWRITE_JPEG_QUALITY, 94]):
            raise RuntimeError("Could not write contact sheet")
    finally:
        cap_c.release()
        cap_e.release()
        shutil.rmtree(frame_dir, ignore_errors=True)

    decode_result = subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-i", str(PREVIEW), "-f", "null", "-"],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
    )
    DECODE.write_text(decode_result.stderr, encoding="utf-8")
    if decode_result.returncode != 0 or decode_result.stderr:
        raise RuntimeError("Registered preview decode failed")

    reductions = [boundary[k]["mae_reduction_fraction"] for k in ("start", "end")]
    report = {
        "schema": "e36_v18c_v18e_temporally_smoothed_boundary_registration_qa_v4",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_cl2x": "CL2X-918",
        "sources": {
            "v18c": {"path": rel(V18C), "sha256": sha256(V18C)},
            "v18e": {"path": rel(V18E), "sha256": sha256(V18E)},
        },
        "target_window_base_seconds": [WINDOW_START, WINDOW_END],
        "method": "STAGGERED_GEOMETRY_AND_PIXEL_TRANSITIONS_PER_FRAME_ECC_AFFINE_REGISTRATION_WITH_7_FRAME_TEMPORAL_SMOOTHING_AND_0P5S_COSINE_RAMPS",
        "transition_schedule": {
            "162P0_162P5": "PIXEL_BLEND_V18C_TO_REGISTERED_V18E",
            "162P5_163P0": "V18E_ONLY_GEOMETRY_EASE_REGISTERED_TO_NATIVE",
            "163P0_165P0": "V18E_NATIVE_SMOOTH_TRAJECTORY",
            "165P0_165P5": "V18E_ONLY_GEOMETRY_EASE_NATIVE_TO_REGISTERED",
            "165P5_166P0": "PIXEL_BLEND_REGISTERED_V18E_TO_V18C",
        },
        "boundary_measurements": boundary,
        "objective_registration_gate": {
            "minimum_endpoint_mae_reduction_fraction": min(reductions),
            "threshold": 0.25,
            "status": "PASS" if min(reductions) >= 0.25 else "FAIL",
        },
        "preview": {
            "path": rel(PREVIEW), "sha256": sha256(PREVIEW), "seconds": PREVIEW_END - PREVIEW_START,
            "resolution": [width, height], "fps": FPS, "audio": "EXACT_V18C_SOURCE_WINDOW_160_168S",
            "full_decode": "PASS_ZERO_ERRORS", "decode_log": {"path": rel(DECODE), "sha256": sha256(DECODE)},
        },
        "contact_sheet": {"path": rel(CONTACT), "sha256": sha256(CONTACT), "samples": 18},
        "gate_results": {
            "canonical_script_manifest": "PASS_EXACT_PREVIOUSLY_VERIFIED_UNCHANGED",
            "registration_objective": "PASS" if min(reductions) >= 0.25 else "FAIL",
            "direct_visual": "PENDING_MANUAL_REVIEW_V4",
            "whole_film_rerender": "NOT_STARTED_PREVIEW_FIRST",
            "v20b": "FAIL_PRESERVED_VISIBLE_GHOST",
            "v19": "REVERSIBLE_NOT_PROMOTED",
            "promotion": "NOT_GRANTED",
            "release": "HOLD",
        },
        "credits": {"pay": 0, "refund": 0, "net": 0, "episode_source_attributable_net": 9976, "cap": 10000, "headroom": 24},
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": rel(REPORT), "preview": rel(PREVIEW), "contact": rel(CONTACT), "boundary": boundary}, indent=2))


if __name__ == "__main__":
    main()
