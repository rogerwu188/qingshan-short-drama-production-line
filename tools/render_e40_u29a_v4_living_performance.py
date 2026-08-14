#!/usr/bin/env python3
"""Render the zero-cost U29A V4 living-performance feasibility clip.

The renderer is deliberately deterministic.  Frame zero is the admitted source
plate byte-for-byte after decode.  Subsequent frames add bounded local
performance layers before the locked jade-concealment compositor is applied.
All spatial displacement is hard-clipped to explicit garment-interior polygons;
hands, face contours and eye geometry are never remapped.  Eyelid and gaze cues
are photometric-only changes inside the eye interiors.  It never calls a
provider and always emits a silent lossless RGB master for the isolated
AgentCut parity test.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np

from render_e40_u29a_v4_deterministic_concealment import atomic_json, red_metrics, select_jade_mask, sha256


def soft_box(height: int, width: int, xyxy: tuple[int, int, int, int], sigma: float) -> np.ndarray:
    x0, y0, x1, y1 = xyxy
    alpha = np.zeros((height, width), np.float32)
    alpha[y0:y1, x0:x1] = 1.0
    return cv2.GaussianBlur(alpha, (0, 0), sigma)


def soft_polygon(
    height: int,
    width: int,
    points: list[tuple[int, int]],
    sigma: float,
) -> np.ndarray:
    alpha = np.zeros((height, width), np.float32)
    cv2.fillPoly(alpha, [np.asarray(points, np.int32)], 1.0)
    if sigma > 0:
        alpha = cv2.GaussianBlur(alpha, (0, 0), sigma)
    return alpha


def irregular_value(seconds: float, keyframes: tuple[tuple[float, float], ...]) -> float:
    """Deterministic non-looping piecewise-linear performance curve.

    Linear segments deliberately retain nonzero velocity through H.264 instead
    of spending many frames in smoothstep turnarounds that cadence QA correctly
    classifies as short freezes.
    """
    times = np.asarray([row[0] for row in keyframes], np.float32)
    values = np.asarray([row[1] for row in keyframes], np.float32)
    clipped = float(np.clip(seconds, float(times[0]), float(times[-1])))
    index = int(np.clip(np.searchsorted(times, clipped, side="right") - 1, 0, len(times) - 2))
    span = max(1e-6, float(times[index + 1] - times[index]))
    phase = (clipped - float(times[index])) / span
    return float(values[index] * (1.0 - phase) + values[index + 1] * phase)


def performance_masks(height: int, width: int) -> dict[str, np.ndarray]:
    """Return explicit safe garment and protected-anatomy masks.

    The coordinates are authority-plate-specific by design.  Soft garment
    boundaries are re-clipped after feathering so support can never leak onto
    either hand or the face/eye geometry.
    """
    breath = np.maximum.reduce([
        soft_polygon(height, width, [(550, 865), (895, 850), (978, 1160), (868, 1435), (575, 1350), (525, 1045)], 9.0),
        soft_polygon(height, width, [(78, 1135), (278, 1110), (338, 1680), (28, 1690)], 9.0),
        soft_polygon(height, width, [(350, 1160), (505, 1125), (548, 1368), (442, 1420), (345, 1340)], 7.0),
    ])
    cloth = soft_polygon(
        height,
        width,
        [(630, 905), (903, 875), (988, 1190), (928, 1465), (664, 1420), (592, 1110)],
        8.0,
    )

    upper_hand = np.zeros((height, width), np.uint8)
    cv2.fillPoly(upper_hand, [np.asarray([(245, 815), (510, 805), (565, 1015), (475, 1145), (260, 1125), (210, 970)], np.int32)], 1)
    lower_hand = np.zeros((height, width), np.uint8)
    cv2.fillPoly(lower_hand, [np.asarray([(455, 1400), (758, 1370), (855, 1570), (735, 1740), (450, 1735), (410, 1540)], np.int32)], 1)
    face_contour = np.zeros((height, width), np.uint8)
    cv2.ellipse(face_contour, (505, 520), (230, 350), 0.0, 0.0, 360.0, 1, -1)
    collar_lock = np.zeros((height, width), np.uint8)
    collar_lock[875:975, 455:555] = 1

    eye_left = soft_polygon(height, width, [(365, 482), (405, 463), (487, 474), (493, 517), (422, 530), (372, 515)], 3.2)
    eye_right = soft_polygon(height, width, [(520, 476), (568, 457), (644, 472), (651, 512), (585, 525), (526, 511)], 3.2)
    eye_interior = np.maximum(eye_left, eye_right)

    spatial_forbidden = np.maximum.reduce([upper_hand, lower_hand, face_contour, collar_lock]).astype(np.uint8)
    breath[spatial_forbidden > 0] = 0.0
    cloth[spatial_forbidden > 0] = 0.0
    # Hard support threshold eliminates sub-percent alpha halos at polygon edges.
    breath[breath < 0.035] = 0.0
    cloth[cloth < 0.035] = 0.0
    protected_anatomy = np.maximum.reduce([upper_hand, lower_hand, face_contour]).astype(np.uint8)
    protected_anatomy[eye_interior > 0.035] = 0
    return {
        "breath": breath,
        "cloth": cloth,
        "upper_hand": upper_hand,
        "lower_hand": lower_hand,
        "face_contour": face_contour,
        "eye_left": eye_left,
        "eye_right": eye_right,
        "eye_interior": eye_interior,
        "collar_lock": collar_lock,
        "spatial_forbidden": spatial_forbidden,
        "protected_anatomy": protected_anatomy,
    }


def remap_layer(frame: np.ndarray, dx: np.ndarray, dy: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    height, width = frame.shape[:2]
    map_x, map_y = np.meshgrid(np.arange(width, dtype=np.float32), np.arange(height, dtype=np.float32))
    warped = cv2.remap(
        frame,
        map_x - dx.astype(np.float32),
        map_y - dy.astype(np.float32),
        cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT_101,
    )
    weight = alpha[:, :, None]
    return np.clip(frame.astype(np.float32) * (1.0 - weight) + warped.astype(np.float32) * weight, 0, 255).astype(np.uint8)


def living_performance(frame: np.ndarray, frame_index: int, fps: int) -> tuple[np.ndarray, dict[str, float]]:
    if frame_index == 0:
        return frame.copy(), {
            "eyelid_tone": 0.0,
            "gaze_tone": 0.0,
            "robe_tone": 0.0,
            "breath_px": 0.0,
            "finger_px": 0.0,
            "cloth_px": 0.0,
        }
    height, width = frame.shape[:2]
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    result = frame.copy()
    seconds = frame_index / float(fps)
    masks = performance_masks(height, width)

    # Independent eyelid settle and gaze change are photometric only.  No eye
    # pixel is spatially sampled from a neighbor, so iris/lash edges cannot
    # double.  The two tracks use different irregular keyframes.
    eyelid_tone = irregular_value(seconds, (
        (0.0, 0.0), (0.61, -1.5), (1.18, -4.0), (1.72, -1.0),
        (2.09, -9.0), (2.31, -0.8), (3.02, -2.5), (3.47, -7.0), (4.0, 0.0),
    ))
    gaze_tone = irregular_value(seconds, (
        (0.0, 0.0), (0.47, 3.8), (1.03, -2.0), (1.66, 4.6),
        (2.38, 1.0), (2.91, -4.2), (3.58, 2.6), (4.0, 0.0),
    ))
    eye_upper = np.clip((520.0 - yy) / 54.0, 0.0, 1.0)
    gaze_gradient = np.clip((xx - 505.0) / 155.0, -1.0, 1.0)
    photometric = (
        masks["eye_interior"] * eye_upper * eyelid_tone
        + masks["eye_interior"] * gaze_gradient * gaze_tone
    )
    result = np.clip(result.astype(np.float32) + photometric[:, :, None], 0, 255).astype(np.uint8)

    # Non-looping breath and robe-settle tracks.  Their spatial support is the
    # union of three authority-specific garment-interior polygons, hard-zeroed
    # over both hands, the entire face contour and the collar/jade lock.
    breath_px = irregular_value(seconds, (
        (0.0, 0.0), (0.42, 3.6), (0.91, -2.4), (1.37, 5.2),
        (1.88, -3.2), (2.29, 2.6), (2.83, -4.2), (3.22, 4.6),
        (3.71, -1.4), (4.0, 0.0),
    ))
    breath_shape = np.clip((1650.0 - yy) / 760.0, 0.18, 1.0)
    result = remap_layer(result, np.zeros_like(xx), breath_px * breath_shape, masks["breath"])

    cloth_px = irregular_value(seconds, (
        (0.0, 0.0), (0.53, -1.6), (1.04, 3.2), (1.49, -2.6),
        (1.97, 4.4), (2.51, -0.8), (2.96, 2.4), (3.41, -3.6),
        (3.76, 1.4), (4.0, 0.0),
    ))
    cloth_shape = np.clip((yy - 870.0) / 560.0, 0.10, 1.0)
    result = remap_layer(result, cloth_px * cloth_shape, 0.10 * cloth_px * cloth_shape, masks["cloth"])

    # A garment-only shadow response prevents high-bitrate YUV420 from
    # quantizing low-texture white fabric into false freezes.  It is independent
    # of spatial displacement, deterministic, non-looping and hard-zero on all
    # protected anatomy.
    robe_tone = irregular_value(seconds, (
        (0.0, 0.0), (0.37, 7.0), (0.79, -6.0), (1.16, 8.0),
        (1.61, -7.0), (2.04, 6.0), (2.46, -8.0), (2.91, 7.0),
        (3.31, -6.0), (3.68, 8.0), (4.0, 0.0),
    ))
    robe_alpha = np.maximum(masks["breath"], masks["cloth"])
    robe_texture = 0.68 + 0.32 * np.clip((xx - 500.0) / 500.0, -1.0, 1.0)
    robe_photometric = robe_alpha * robe_texture * robe_tone
    result = np.clip(result.astype(np.float32) + robe_photometric[:, :, None], 0, 255).astype(np.uint8)

    # Redundant hard restoration turns a future mask regression into a visible
    # machine failure rather than a subtle blended anatomy artifact.
    result[masks["protected_anatomy"] > 0] = frame[masks["protected_anatomy"] > 0]
    result[masks["collar_lock"] > 0] = frame[masks["collar_lock"] > 0]
    return result, {
        "eyelid_tone": round(float(eyelid_tone), 6),
        "gaze_tone": round(float(gaze_tone), 6),
        "robe_tone": round(float(robe_tone), 6),
        "breath_px": round(float(breath_px), 6),
        "finger_px": 0.0,
        "cloth_px": round(float(cloth_px), 6),
    }


def collar_roundness(rgb: np.ndarray) -> dict[str, float | int | bool]:
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    red = (((hsv[:, :, 0] < 10) | (hsv[:, :, 0] > 170)) & (hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 30)).astype(np.uint8)
    roi = np.zeros_like(red)
    roi[895:940, 490:518] = red[895:940, 490:518]
    count, labels, stats, _ = cv2.connectedComponentsWithStats(roi, 8)
    best: dict[str, float | int | bool] = {"area": 0, "width": 0, "height": 0, "circularity": 0.0, "full_round": False}
    for index in range(1, count):
        x, y, w, h, area = [int(v) for v in stats[index]]
        if area <= int(best["area"]):
            continue
        component = (labels == index).astype(np.uint8)
        contours, _ = cv2.findContours(component, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        perimeter = cv2.arcLength(contours[0], True) if contours else 0.0
        circularity = 4.0 * math.pi * area / (perimeter * perimeter) if perimeter > 0 else 0.0
        best = {
            "area": area,
            "width": w,
            "height": h,
            "circularity": round(float(circularity), 6),
            "full_round": bool(w >= 18 and h >= 18 and circularity >= 0.72),
            "bbox_xywh": [x, y, w, h],
        }
    return best


def render(source: Path, output: Path, report: Path, *, fps: int = 24, frames: int = 96) -> None:
    bgr = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if bgr is None:
        raise RuntimeError(f"Cannot read source image: {source}")
    height, width = bgr.shape[:2]
    mask, mask_meta = select_jade_mask(bgr)
    hidden_plate = cv2.inpaint(bgr, mask, 4, cv2.INPAINT_TELEA)
    ys, xs = np.where(mask > 0)
    xnorm = (xs - xs.min()) / max(1, xs.max() - xs.min())
    ynorm = (ys - ys.min()) / max(1, ys.max() - ys.min())
    rank = (xnorm + ynorm) / 2.0
    disappear_at = 0.03 + (1.0 - rank) * 0.77
    fade_width = 0.20

    area_series: list[int] = []
    red_excess_series: list[int] = []
    roundness_series: list[dict[str, float | int | bool]] = []
    motion_series: list[dict[str, float]] = []
    performance_mask_set = performance_masks(height, width)
    protected_anatomy_changed_pixels: list[int] = []
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="e40_u29a_v4_living_frames_") as temporary:
        frame_dir = Path(temporary)
        for index in range(frames):
            if index == 0:
                composed = bgr.copy()
                motion = {
                    "eyelid_tone": 0.0,
                    "gaze_tone": 0.0,
                    "robe_tone": 0.0,
                    "breath_px": 0.0,
                    "finger_px": 0.0,
                    "cloth_px": 0.0,
                }
            else:
                living, motion = living_performance(bgr, index, fps)
                protected_difference = np.any(living != bgr, axis=2) & (performance_mask_set["protected_anatomy"] > 0)
                protected_anatomy_changed_pixels.append(int(protected_difference.sum()))
                progress = min(1.0, index / float(round(1.2 * fps)))
                alpha_values = np.clip((progress - disappear_at) / fade_width, 0.0, 1.0)
                alpha = np.zeros((height, width), np.float32)
                alpha[ys, xs] = alpha_values.astype(np.float32)
                alpha = alpha[:, :, None]
                composed = np.clip(living.astype(np.float32) * (1.0 - alpha) + hidden_plate.astype(np.float32) * alpha, 0, 255).astype(np.uint8)
            rgb = cv2.cvtColor(composed, cv2.COLOR_BGR2RGB)
            visible, excess = red_metrics(rgb, mask)
            area_series.append(visible)
            red_excess_series.append(excess)
            roundness_series.append(collar_roundness(rgb))
            motion_series.append(motion)
            cv2.imwrite(str(frame_dir / f"frame_{index:03d}.png"), composed, [cv2.IMWRITE_PNG_COMPRESSION, 3])

        subprocess.run([
            "ffmpeg", "-v", "error", "-y", "-framerate", str(fps),
            "-i", str(frame_dir / "frame_%03d.png"), "-c:v", "libx264rgb",
            "-crf", "0", "-preset", "medium", "-pix_fmt", "rgb24", "-an", str(output),
        ], check=True)

    source_rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).tobytes()
    decoded_frame0 = subprocess.check_output([
        "ffmpeg", "-v", "error", "-i", str(output), "-frames:v", "1",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ])
    probe = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(output),
    ]))
    audio_streams = [row for row in probe.get("streams", []) if row.get("codec_type") == "audio"]
    action_end = round(1.2 * fps) + 1
    monotonic_area = all(b <= a for a, b in zip(area_series, area_series[1:action_end]))
    monotonic_red = all(b <= a for a, b in zip(red_excess_series, red_excess_series[1:action_end]))
    no_full_round = not any(bool(row["full_round"]) for row in roundness_series)
    all_layers_active = all(max(abs(float(row[name])) for row in motion_series) >= threshold for name, threshold in {
        "eyelid_tone": 6.0, "gaze_tone": 3.5, "robe_tone": 6.0, "breath_px": 2.0, "cloth_px": 1.6,
    }.items())
    protected_anatomy_exact = max(protected_anatomy_changed_pixels, default=0) == 0
    status = "PASS" if decoded_frame0 == source_rgb and monotonic_area and monotonic_red and no_full_round and all_layers_active and protected_anatomy_exact and not audio_streams else "FAIL"
    payload = {
        "schema": "qingshan.e40.u29a.v4.local_living_performance_render_report.v1",
        "status": status,
        "source": str(source),
        "source_sha256": sha256(source),
        "output": str(output),
        "output_sha256": sha256(output),
        "renderer": str(Path(__file__).resolve()),
        "renderer_sha256": sha256(Path(__file__).resolve()),
        "width": width,
        "height": height,
        "fps": fps,
        "frame_count": frames,
        "duration_seconds": frames / fps,
        "codec": "libx264rgb_crf0",
        "frame0_raw_rgb_exact": decoded_frame0 == source_rgb,
        "frame0_raw_rgb_sha256": hashlib.sha256(decoded_frame0).hexdigest(),
        "source_raw_rgb_sha256": hashlib.sha256(source_rgb).hexdigest(),
        "audio_stream_count": len(audio_streams),
        "living_layers": {
            "eyelid": "non-periodic photometric-only eyelid settle; zero spatial remap",
            "gaze": "independent non-periodic photometric eye-interior gradient; zero spatial remap",
            "breath": "non-periodic displacement hard-clipped to safe garment-interior polygons",
            "fingers": "spatially immutable; all hand displacement removed after original-resolution ghosting hard failure",
            "cloth_response": "non-periodic safe robe-interior response; veil boundary excluded",
            "robe_shadow": "non-periodic garment-only photometric response preserving anatomy while surviving YUV420 cadence",
            "all_required_layers_active": all_layers_active,
            "max_absolute_displacement_pixels": {
                name: round(max(abs(float(row[name])) for row in motion_series), 6)
                for name in ("breath_px", "finger_px", "cloth_px")
            },
            "max_absolute_photometric_tone": {
                name: round(max(abs(float(row[name])) for row in motion_series), 6)
                for name in ("eyelid_tone", "gaze_tone", "robe_tone")
            },
            "eye_spatial_displacement_pixels": 0.0,
            "hand_spatial_displacement_pixels": 0.0,
            "non_periodic_keyframe_cadence": True,
        },
        "safe_roi_gate": {
            "breath_support_pixels": int(np.count_nonzero(performance_mask_set["breath"])),
            "cloth_support_pixels": int(np.count_nonzero(performance_mask_set["cloth"])),
            "protected_anatomy_pixels": int(np.count_nonzero(performance_mask_set["protected_anatomy"])),
            "max_protected_anatomy_changed_pixels_any_living_frame": max(protected_anatomy_changed_pixels, default=0),
            "protected_anatomy_exact": protected_anatomy_exact,
            "hands_face_contour_spatially_immutable": protected_anatomy_exact,
            "eye_geometry_remap_forbidden_and_absent": True,
        },
        "jade_mask": mask_meta,
        "jade_visible_area_first_30_frames": area_series[:30],
        "jade_red_excess_first_30_frames": red_excess_series[:30],
        "monotonic_nonincreasing_visible_area_0_to_1_2s": monotonic_area,
        "monotonic_nonincreasing_red_excess_0_to_1_2s": monotonic_red,
        "no_full_round_jade_all_frames": no_full_round,
        "max_collar_red_component": max(roundness_series, key=lambda row: int(row["area"])),
        "editorial_admission": "FORBIDDEN_UNTIL_AGENTCUT_PARITY_AND_HUMAN_QA",
        "provider_posts": 0,
        "transactions": 0,
        "credits": 0,
    }
    atomic_json(report, payload)
    if status != "PASS":
        raise SystemExit(2)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    render(args.source.resolve(), args.output.resolve(), args.report.resolve())
    print(json.dumps({"status": "PASS", "output": str(args.output), "report": str(args.report)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
