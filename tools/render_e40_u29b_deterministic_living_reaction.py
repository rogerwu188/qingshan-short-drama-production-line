#!/usr/bin/env python3
"""Render a local-only deterministic U29B living-reaction feasibility clip.

The admitted U29B plate supplies every output pixel.  A quarantined provider
take is used only as a motion-field donor; its pixels and audio are never
copied.  Frame zero is the Lanczos-resized admitted plate, encoded losslessly.
This is a no-submit feasibility artifact, not an AgentCut admission.
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


AUTHORITY_SHA256 = "fdc833988f3a6fb7551cadf117d20512ae47f0d053641e257101fe0699067dea"
DONOR_SHA256 = "caffa28f91bc9aa6b2f7029c583ad416614b61b1937ec404c501475b6be06acb"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_video_frames(path: Path, limit: int) -> tuple[list[np.ndarray], float]:
    capture = cv2.VideoCapture(str(path))
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    frames: list[np.ndarray] = []
    while len(frames) < limit:
        ok, frame = capture.read()
        if not ok:
            break
        frames.append(frame)
    capture.release()
    if abs(fps - 24.0) > 0.01 or len(frames) < limit:
        raise RuntimeError(f"Donor must provide at least {limit} frames at 24fps; got {len(frames)} at {fps}")
    return frames, fps


def polygon_mask(height: int, width: int, points: list[tuple[int, int]], feather: float) -> np.ndarray:
    mask = np.zeros((height, width), np.float32)
    cv2.fillPoly(mask, [np.asarray(points, dtype=np.int32)], 1.0)
    if feather:
        mask = cv2.GaussianBlur(mask, (0, 0), feather)
    return np.clip(mask, 0.0, 1.0)


def ellipse_mask(
    height: int,
    width: int,
    center: tuple[int, int],
    axes: tuple[int, int],
    feather: float,
) -> np.ndarray:
    mask = np.zeros((height, width), np.float32)
    cv2.ellipse(mask, center, axes, 0, 0, 360, 1.0, -1)
    if feather:
        mask = cv2.GaussianBlur(mask, (0, 0), feather)
    return np.clip(mask, 0.0, 1.0)


def local_translate(
    current: np.ndarray,
    source: np.ndarray,
    map_x0: np.ndarray,
    map_y0: np.ndarray,
    mask: np.ndarray,
    dx: float,
    dy: float,
) -> np.ndarray:
    warped = cv2.remap(
        source,
        (map_x0 - dx).astype(np.float32),
        (map_y0 - dy).astype(np.float32),
        interpolation=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REFLECT_101,
    )
    alpha = mask[:, :, None]
    return np.clip(current.astype(np.float32) * (1.0 - alpha) + warped.astype(np.float32) * alpha, 0, 255).astype(np.uint8)


def smoothstep(value: float) -> float:
    value = float(np.clip(value, 0.0, 1.0))
    return value * value * (3.0 - 2.0 * value)


def donor_timing_profile(frames: list[np.ndarray]) -> list[float]:
    """Extract only a normalized timing envelope; never copy donor pixels."""
    base = cv2.cvtColor(frames[0], cv2.COLOR_BGR2GRAY).astype(np.float32)
    raw = []
    for frame in frames:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
        raw.append(float(np.mean(np.abs(gray - base))))
    peak = max(raw) or 1.0
    return [value / peak for value in raw]


def frame_difference(left: np.ndarray, right: np.ndarray, roi: tuple[int, int, int, int]) -> float:
    x0, y0, x1, y1 = roi
    a = left[y0:y1, x0:x1].astype(np.float32)
    b = right[y0:y1, x0:x1].astype(np.float32)
    return float(np.abs(a - b).mean())


def render(authority: Path, donor: Path, output: Path, report: Path) -> None:
    if sha256(authority) != AUTHORITY_SHA256:
        raise RuntimeError("Authority SHA mismatch")
    if sha256(donor) != DONOR_SHA256:
        raise RuntimeError("Motion-donor SHA mismatch")

    donor_frames, fps = read_video_frames(donor, 96)
    height, width = donor_frames[0].shape[:2]
    if (width, height) != (720, 1280):
        raise RuntimeError(f"Unexpected donor dimensions: {width}x{height}")
    admitted = cv2.imread(str(authority), cv2.IMREAD_COLOR)
    if admitted is None:
        raise RuntimeError("Authority image cannot be decoded")
    base = cv2.resize(admitted, (width, height), interpolation=cv2.INTER_LANCZOS4)
    # Deliberately small actor-only regions.  The previous feasibility pass
    # used broad optical-flow ellipses and bent the door frame and faces.  These
    # garment/eye masks keep architecture, face contour, hands and props locked.
    chenji_garment = polygon_mask(
        height, width,
        [(44, 400), (110, 350), (315, 350), (405, 430), (410, 720), (335, 770), (135, 760), (65, 700)],
        5.0,
    )
    ashuan_garment = polygon_mask(
        height, width,
        [(450, 500), (500, 455), (620, 460), (665, 535), (655, 790), (455, 790)],
        4.0,
    )
    chenji_eye_left = ellipse_mask(height, width, (143, 273), (13, 5), 1.2)
    chenji_eye_right = ellipse_mask(height, width, (193, 272), (13, 5), 1.2)
    ashuan_eye_left = ellipse_mask(height, width, (537, 370), (11, 4), 1.0)
    ashuan_eye_right = ellipse_mask(height, width, (575, 369), (11, 4), 1.0)
    timing = donor_timing_profile(donor_frames[:96])
    mask_meta = {
        "chenji_garment_polygon": [[44, 400], [110, 350], [315, 350], [405, 430], [410, 720], [335, 770], [135, 760], [65, 700]],
        "ashuan_garment_polygon": [[450, 500], [500, 455], [620, 460], [665, 535], [655, 790], [455, 790]],
        "chenji_eye_centers": [[143, 273], [193, 272]],
        "ashuan_eye_centers": [[537, 370], [575, 369]],
        "background_face_contours_hands_props": "LOCKED",
    }
    map_x0, map_y0 = np.meshgrid(np.arange(width, dtype=np.float32), np.arange(height, dtype=np.float32))

    chenji_roi = (0, 70, 505, 1279)
    ashuan_roi = (365, 220, 719, 1279)
    consecutive_duplicate_count = 0
    chenji_diff: list[float] = []
    ashuan_diff: list[float] = []
    rendered_frames: list[np.ndarray] = []

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="e40_u29b_living_frames_") as temporary:
        frame_dir = Path(temporary)
        for index, donor_frame in enumerate(donor_frames[:96]):
            if index == 0:
                composed = base.copy()
            else:
                seconds = index / fps
                chenji_turn = smoothstep(seconds / 0.5)
                ashuan_release = smoothstep(seconds / 0.7)
                # The quarantined take contributes timing only.  Amplitudes and
                # pixels are deterministic functions of the admitted plate.
                donor_pulse = timing[index]
                chenji_breath = 0.42 * np.sin(2.0 * np.pi * seconds / 2.15) + 0.08 * donor_pulse
                ashuan_breath = 0.55 * np.sin(2.0 * np.pi * seconds / 2.45 + 0.35) + 0.10 * donor_pulse
                composed = base.copy()
                composed = local_translate(
                    composed, base, map_x0, map_y0, chenji_garment,
                    dx=0.45 * chenji_turn, dy=chenji_breath,
                )
                composed = local_translate(
                    composed, base, map_x0, map_y0, ashuan_garment,
                    dx=0.0, dy=0.75 * ashuan_release + ashuan_breath,
                )
                # Gaze settles forward in the first half second, then retains a
                # subpixel living hold.  The masks cover only the iris/eye slit.
                chenji_eye_dx = 1.15 * chenji_turn + 0.12 * np.sin(2.0 * np.pi * seconds / 1.7)
                ashuan_eye_dx = 0.55 * ashuan_release + 0.10 * np.sin(2.0 * np.pi * seconds / 1.9 + 0.4)
                for eye_mask in (chenji_eye_left, chenji_eye_right):
                    composed = local_translate(composed, base, map_x0, map_y0, eye_mask, chenji_eye_dx, 0.0)
                for eye_mask in (ashuan_eye_left, ashuan_eye_right):
                    composed = local_translate(composed, base, map_x0, map_y0, eye_mask, ashuan_eye_dx, 0.0)
            rendered_frames.append(composed)
            chenji_diff.append(frame_difference(base, composed, chenji_roi))
            ashuan_diff.append(frame_difference(base, composed, ashuan_roi))
            if index and np.array_equal(composed, rendered_frames[index - 1]):
                consecutive_duplicate_count += 1
            cv2.imwrite(str(frame_dir / f"frame_{index:03d}.png"), composed, [cv2.IMWRITE_PNG_COMPRESSION, 3])

        command = [
            "ffmpeg", "-v", "error", "-y", "-fflags", "+bitexact",
            "-framerate", "24", "-i", str(frame_dir / "frame_%03d.png"),
            "-map_metadata", "-1", "-c:v", "libx264rgb", "-crf", "0",
            "-preset", "medium", "-pix_fmt", "rgb24", "-flags:v", "+bitexact",
            "-an", str(output),
        ]
        subprocess.run(command, check=True)

    decoded_frame0 = subprocess.check_output([
        "ffmpeg", "-v", "error", "-i", str(output), "-frames:v", "1",
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-",
    ])
    base_bytes = base.tobytes()
    probe = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-count_frames", "-show_streams", "-show_format", "-of", "json", str(output),
    ]))
    audio_streams = [row for row in probe.get("streams", []) if row.get("codec_type") == "audio"]
    video_stream = next(row for row in probe.get("streams", []) if row.get("codec_type") == "video")
    first_half_second = 12
    first_displacement = next((index for index, value in enumerate(chenji_diff[1:first_half_second + 1], 1) if value >= 0.05), None)
    ashuan_first_displacement = next((index for index, value in enumerate(ashuan_diff[1:first_half_second + 1], 1) if value >= 0.05), None)
    status = "PASS" if (
        decoded_frame0 == base_bytes
        and not audio_streams
        and consecutive_duplicate_count == 0
        and first_displacement is not None
        and ashuan_first_displacement is not None
    ) else "FAIL"
    payload = {
        "schema": "qingshan.e40.u29b.deterministic_living_reaction_render_report.v1",
        "status": status,
        "authority": str(authority),
        "authority_sha256": AUTHORITY_SHA256,
        "motion_donor": str(donor),
        "motion_donor_sha256": DONOR_SHA256,
        "motion_donor_usage": "NORMALIZED_TIMING_ENVELOPE_ONLY_NO_PIXEL_OR_AUDIO_COPY",
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
        "consecutive_duplicate_frame_count": consecutive_duplicate_count,
        "chenji_first_displacement_frame": first_displacement,
        "ashuan_first_displacement_frame": ashuan_first_displacement,
        "chenji_difference_from_frame0_first_13": chenji_diff[:13],
        "ashuan_difference_from_frame0_first_13": ashuan_diff[:13],
        "motion_masks": mask_meta,
        "pixel_provenance": "ALL_OUTPUT_PIXELS_SAMPLED_FROM_ADMITTED_AUTHORITY_PLATE",
        "identity_or_prop_generation": False,
        "u29a_semantic_tail_claimed": False,
        "editorial_admission": "FORBIDDEN_FEASIBILITY_TEST_ONLY",
        "provider_posts": 0,
        "transactions": 0,
        "credits": 0
    }
    atomic_json(report, payload)
    if status != "PASS":
        raise SystemExit(2)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--authority", type=Path, required=True)
    parser.add_argument("--motion-donor", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    render(args.authority.resolve(), args.motion_donor.resolve(), args.output.resolve(), args.report.resolve())
    print(json.dumps({"status": "PASS", "output": str(args.output), "report": str(args.report)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
