#!/usr/bin/env python3
"""Render the zero-cost U29B editorial-performance feasibility candidate.

All output pixels originate in the admitted authority plate.  The quarantined
provider take contributes only a normalized timing envelope.  The performance
program uses non-periodic keyframes for gaze, breath, garment weight and
interior hand tension; it never moves background geometry, face contours or
hand silhouettes.  The output is an isolated QA artifact, never a final edit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np

from render_e40_u29b_deterministic_living_reaction import (
    AUTHORITY_SHA256,
    DONOR_SHA256,
    atomic_json,
    donor_timing_profile,
    ellipse_mask,
    frame_difference,
    local_translate,
    polygon_mask,
    read_video_frames,
    sha256,
    smoothstep,
)


def keyed(frame: int, points: list[tuple[int, float]]) -> float:
    if frame <= points[0][0]:
        return points[0][1]
    if frame >= points[-1][0]:
        return points[-1][1]
    for (left_frame, left_value), (right_frame, right_value) in zip(points, points[1:]):
        if left_frame <= frame <= right_frame:
            progress = smoothstep((frame - left_frame) / max(1, right_frame - left_frame))
            return float(left_value + (right_value - left_value) * progress)
    raise AssertionError("unreachable keyframe interval")


def blink(frame: int, center: int, half_width: int = 4) -> float:
    distance = abs(frame - center)
    if distance >= half_width:
        return 0.0
    return smoothstep(1.0 - distance / half_width)


def local_sample_shift(
    current: np.ndarray,
    source: np.ndarray,
    map_x0: np.ndarray,
    map_y0: np.ndarray,
    mask: np.ndarray,
    sample_dx: float,
    sample_dy: float,
) -> np.ndarray:
    sampled = cv2.remap(
        source,
        (map_x0 + sample_dx).astype(np.float32),
        (map_y0 + sample_dy).astype(np.float32),
        interpolation=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REFLECT_101,
    )
    alpha = mask[:, :, None]
    return np.clip(current.astype(np.float32) * (1.0 - alpha) + sampled.astype(np.float32) * alpha, 0, 255).astype(np.uint8)


def render(authority: Path, donor: Path, output: Path, report: Path) -> None:
    if sha256(authority) != AUTHORITY_SHA256:
        raise RuntimeError("Authority SHA mismatch")
    if sha256(donor) != DONOR_SHA256:
        raise RuntimeError("Timing-donor SHA mismatch")

    donor_frames, fps = read_video_frames(donor, 96)
    height, width = donor_frames[0].shape[:2]
    if (width, height) != (720, 1280):
        raise RuntimeError(f"Unexpected donor dimensions: {width}x{height}")
    admitted = cv2.imread(str(authority), cv2.IMREAD_COLOR)
    if admitted is None:
        raise RuntimeError("Authority image cannot be decoded")
    base = cv2.resize(admitted, (width, height), interpolation=cv2.INTER_LANCZOS4)
    map_x0, map_y0 = np.meshgrid(np.arange(width, dtype=np.float32), np.arange(height, dtype=np.float32))
    timing = donor_timing_profile(donor_frames[:96])

    # Masks remain strictly inside garment, eye and hand silhouettes.  Broad
    # optical-flow regions are prohibited by the prior human hard-fail.
    chenji_garment = polygon_mask(
        height, width,
        [(48, 410), (115, 360), (308, 360), (398, 438), (402, 708), (332, 748), (142, 744), (72, 690)],
        4.0,
    )
    ashuan_garment = polygon_mask(
        height, width,
        [(457, 505), (505, 465), (615, 470), (657, 540), (648, 785), (462, 785)],
        3.5,
    )
    chenji_eyes = [
        ellipse_mask(height, width, (143, 273), (13, 5), 1.0),
        ellipse_mask(height, width, (193, 272), (13, 5), 1.0),
    ]
    ashuan_eyes = [
        ellipse_mask(height, width, (537, 370), (11, 4), 0.9),
        ellipse_mask(height, width, (575, 369), (11, 4), 0.9),
    ]
    # Interior-only masks: hand contours and finger counts remain unchanged.
    chenji_hand_interiors = [
        ellipse_mask(height, width, (57, 915), (13, 48), 2.0),
        ellipse_mask(height, width, (374, 900), (12, 45), 2.0),
    ]
    ashuan_hand_interiors = [
        ellipse_mask(height, width, (448, 805), (8, 27), 1.5),
        ellipse_mask(height, width, (653, 804), (8, 27), 1.5),
    ]

    chenji_roi = (0, 70, 505, 1279)
    ashuan_roi = (365, 220, 719, 1279)
    consecutive_duplicates = 0
    chenji_diff: list[float] = []
    ashuan_diff: list[float] = []
    frames: list[np.ndarray] = []

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="e40_u29b_editorial80_frames_") as temporary:
        frame_dir = Path(temporary)
        for index in range(96):
            if index == 0:
                composed = base.copy()
            else:
                donor_pulse = timing[index]
                # 0.0-0.5s: gaze retracts and first controlled exhale begins.
                chenji_eye_dx = keyed(index, [(0, 0.0), (6, 1.75), (12, 3.05), (24, 2.62), (48, 2.95), (72, 2.48), (95, 2.72)])
                ashuan_eye_dx = keyed(index, [(0, 0.0), (8, 0.72), (12, 1.35), (30, 1.08), (55, 1.55), (80, 1.22), (95, 1.42)])
                # 0.5-1.2s: Chenji transfers weight; Ashuan's shoulders release.
                chenji_dx = keyed(index, [(0, 0.0), (6, 1.25), (12, 3.15), (28, 7.15), (47, 5.55), (69, 7.65), (95, 6.08)])
                chenji_dy = keyed(index, [(0, 0.0), (12, -0.82), (28, -3.05), (51, -1.25), (74, -3.55), (95, -2.08)])
                ashuan_dy = keyed(index, [(0, 0.0), (7, 1.55), (12, 3.05), (28, 7.45), (49, 4.62), (73, 7.82), (95, 5.48)])
                # Irregular garment-settle beats keep the living hold legible
                # through YUV420p transcode.  Unequal intervals and amplitudes
                # deliberately avoid a breathing loop or periodic signature.
                chenji_dy += keyed(index, [(0, 0.0), (9, -1.3), (18, 1.8), (27, -1.1), (37, 2.1), (46, -1.7), (58, 2.4), (67, -1.2), (77, 2.0), (86, -1.6), (95, 0.7)])
                ashuan_dy += keyed(index, [(0, 0.0), (8, 1.6), (17, -1.4), (26, 2.2), (36, -1.8), (45, 1.3), (56, -2.1), (66, 1.9), (75, -1.5), (85, 2.3), (95, -0.8)])
                # Donor affects only a bounded subpixel timing accent.
                chenji_dy += 0.09 * donor_pulse
                ashuan_dy += 0.12 * donor_pulse

                composed = base.copy()
                composed = local_translate(composed, base, map_x0, map_y0, chenji_garment, chenji_dx, chenji_dy)
                composed = local_translate(composed, base, map_x0, map_y0, ashuan_garment, 0.0, ashuan_dy)
                for eye_mask in chenji_eyes:
                    composed = local_translate(composed, base, map_x0, map_y0, eye_mask, chenji_eye_dx, 0.0)
                for eye_mask in ashuan_eyes:
                    composed = local_translate(composed, base, map_x0, map_y0, eye_mask, ashuan_eye_dx, 0.0)

                # Two asynchronous, non-periodic blinks copied from skin pixels
                # immediately above each eye; no face contour is touched.
                chenji_blink = blink(index, 43, 4)
                ashuan_blink = max(blink(index, 34, 4), blink(index, 79, 4))
                for eye_mask in chenji_eyes:
                    if chenji_blink:
                        composed = local_sample_shift(composed, base, map_x0, map_y0, eye_mask * chenji_blink, 0.0, -5.0)
                for eye_mask in ashuan_eyes:
                    if ashuan_blink:
                        composed = local_sample_shift(composed, base, map_x0, map_y0, eye_mask * ashuan_blink, 0.0, -4.0)

                # Interior hand tension releases after the body reaction.  Only
                # skin texture shifts subpixel; silhouettes and finger count lock.
                hand_release = keyed(index, [(0, 0.0), (12, 0.18), (28, 0.92), (48, 1.35), (72, 1.02), (95, 1.22)])
                for hand_mask in chenji_hand_interiors:
                    composed = local_translate(composed, base, map_x0, map_y0, hand_mask, 0.28 * hand_release, 0.46 * hand_release)
                for hand_mask in ashuan_hand_interiors:
                    composed = local_translate(composed, base, map_x0, map_y0, hand_mask, -0.18 * hand_release, 0.34 * hand_release)

            frames.append(composed)
            chenji_diff.append(frame_difference(base, composed, chenji_roi))
            ashuan_diff.append(frame_difference(base, composed, ashuan_roi))
            if index and np.array_equal(composed, frames[index - 1]):
                consecutive_duplicates += 1
            cv2.imwrite(str(frame_dir / f"frame_{index:03d}.png"), composed, [cv2.IMWRITE_PNG_COMPRESSION, 3])

        subprocess.run([
            "ffmpeg", "-v", "error", "-y", "-fflags", "+bitexact",
            "-framerate", "24", "-i", str(frame_dir / "frame_%03d.png"),
            "-map_metadata", "-1", "-c:v", "libx264rgb", "-crf", "0",
            "-preset", "medium", "-pix_fmt", "rgb24", "-flags:v", "+bitexact",
            "-an", str(output),
        ], check=True)

    decoded_frame0 = subprocess.check_output([
        "ffmpeg", "-v", "error", "-i", str(output), "-frames:v", "1",
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-",
    ])
    probe = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-count_frames", "-show_streams", "-show_format", "-of", "json", str(output),
    ]))
    audio_streams = [row for row in probe.get("streams", []) if row.get("codec_type") == "audio"]
    video_stream = next(row for row in probe.get("streams", []) if row.get("codec_type") == "video")
    base_bytes = base.tobytes()
    first_window = 12
    chenji_first = next((i for i, value in enumerate(chenji_diff[1:first_window + 1], 1) if value >= 0.05), None)
    ashuan_first = next((i for i, value in enumerate(ashuan_diff[1:first_window + 1], 1) if value >= 0.05), None)
    status = "PASS" if (
        decoded_frame0 == base_bytes and not audio_streams and consecutive_duplicates == 0
        and chenji_first is not None and ashuan_first is not None
    ) else "FAIL"
    atomic_json(report, {
        "schema": "qingshan.e40.u29b.editorial80_living_reaction_render_report.v1",
        "status": status,
        "authority": str(authority),
        "authority_sha256": AUTHORITY_SHA256,
        "timing_donor": str(donor),
        "timing_donor_sha256": DONOR_SHA256,
        "timing_donor_usage": "NORMALIZED_TIMING_ENVELOPE_ONLY_NO_PIXEL_OR_AUDIO_COPY",
        "output": str(output),
        "output_sha256": sha256(output),
        "codec": "libx264rgb_crf0_bitexact",
        "width": width,
        "height": height,
        "fps": fps,
        "frame_count": int(video_stream.get("nb_read_frames") or 0),
        "duration_seconds": 4.0,
        "frame0_raw_bgr_exact_to_lanczos_authority": decoded_frame0 == base_bytes,
        "frame0_raw_bgr_sha256": hashlib.sha256(decoded_frame0).hexdigest(),
        "authority_lanczos_raw_bgr_sha256": hashlib.sha256(base_bytes).hexdigest(),
        "audio_stream_count": len(audio_streams),
        "consecutive_duplicate_frame_count": consecutive_duplicates,
        "chenji_first_displacement_frame": chenji_first,
        "ashuan_first_displacement_frame": ashuan_first,
        "performance_windows": {
            "gaze_and_first_exhale_frames": [0, 12],
            "weight_and_shoulder_release_frames": [12, 28],
            "chenji_blink_center_frame": 43,
            "ashuan_blink_center_frames": [34, 79],
            "temporal_program": "ASYMMETRIC_NON_PERIODIC_KEYFRAMES"
        },
        "locked_geometry": ["background", "face_contours", "hand_silhouettes", "finger_count", "props"],
        "pixel_provenance": "ALL_OUTPUT_PIXELS_SAMPLED_FROM_ADMITTED_AUTHORITY_PLATE",
        "u29a_semantic_tail_claimed": False,
        "editorial_admission": "FORBIDDEN_UNTIL_HUMAN80_AND_AGENTCUT_PARITY_QA",
        "provider_posts": 0,
        "transactions": 0,
        "credits": 0
    })
    if status != "PASS":
        raise SystemExit(2)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--authority", type=Path, required=True)
    parser.add_argument("--timing-donor", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    render(args.authority.resolve(), args.timing_donor.resolve(), args.output.resolve(), args.report.resolve())
    print(json.dumps({"status": "PASS", "output": str(args.output), "report": str(args.report)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
