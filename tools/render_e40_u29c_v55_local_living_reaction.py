#!/usr/bin/env python3
"""Render a zero-cost local U29C two-person micro-reaction candidate.

This is a materially different representation from the quarantined Seedance
V5 output: it uses the admitted V2 exact-start plate as the only RGB source,
performs no provider call, and applies deterministic photometric-only changes
inside explicit eye and garment interiors.  Frame zero remains pixel exact,
the background and all anatomy outside the eye interiors remain immutable, and
the lossless RGB master contains no audio stream.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np


EXPECTED_SOURCE_SHA256 = "962bf54654a66e01ada6fe0924a28252a7d1114e44efe889360a427183c4aadd"
EXPECTED_JIAOTU_LAYER_SHA256 = "b205169fd657be9b719c8235bb836b307820ff3569265cae6e6edda52ef2a731"
EXPECTED_YUNYANG_LAYER_SHA256 = "2b191009a679db656bc3823e1fbe43882e78d4af867c8b20df62b0c55937f8db"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def irregular_value(seconds: float, keyframes: tuple[tuple[float, float], ...]) -> float:
    times = np.asarray([item[0] for item in keyframes], np.float32)
    values = np.asarray([item[1] for item in keyframes], np.float32)
    clipped = float(np.clip(seconds, float(times[0]), float(times[-1])))
    index = int(np.clip(np.searchsorted(times, clipped, side="right") - 1, 0, len(times) - 2))
    span = max(1e-6, float(times[index + 1] - times[index]))
    phase = (clipped - float(times[index])) / span
    return float(values[index] * (1.0 - phase) + values[index + 1] * phase)


def soft_polygon(height: int, width: int, points: list[tuple[int, int]], sigma: float) -> np.ndarray:
    mask = np.zeros((height, width), np.float32)
    cv2.fillPoly(mask, [np.asarray(points, np.int32)], 1.0)
    if sigma:
        mask = cv2.GaussianBlur(mask, (0, 0), sigma)
    mask[mask < 0.025] = 0.0
    return mask


def placed_alpha(layer_path: Path, xy: tuple[int, int], shape: tuple[int, int]) -> np.ndarray:
    layer = cv2.imread(str(layer_path), cv2.IMREAD_UNCHANGED)
    if layer is None or layer.ndim != 3 or layer.shape[2] != 4:
        raise RuntimeError(f"Expected RGBA layer: {layer_path}")
    height, width = shape
    x, y = xy
    alpha = np.zeros((height, width), np.float32)
    layer_height, layer_width = layer.shape[:2]
    alpha[y:y + layer_height, x:x + layer_width] = layer[:, :, 3].astype(np.float32) / 255.0
    return alpha


def build_masks(
    height: int,
    width: int,
    jiaotu_layer: Path,
    yunyang_layer: Path,
) -> dict[str, np.ndarray]:
    jiaotu_alpha = placed_alpha(jiaotu_layer, (58, 707), (height, width))
    yunyang_alpha = placed_alpha(yunyang_layer, (617, 756), (height, width))

    jiaotu_eyes = np.maximum(
        soft_polygon(height, width, [(202, 837), (213, 832), (232, 837), (231, 850), (211, 852), (201, 847)], 1.5),
        soft_polygon(height, width, [(244, 837), (254, 832), (274, 837), (273, 850), (253, 852), (243, 847)], 1.5),
    ) * np.clip(jiaotu_alpha * 1.2, 0.0, 1.0)
    yunyang_eyes = np.maximum(
        soft_polygon(height, width, [(718, 849), (727, 846), (742, 849), (741, 858), (726, 859), (718, 856)], 1.2),
        soft_polygon(height, width, [(750, 848), (758, 845), (774, 848), (773, 857), (758, 859), (750, 856)], 1.2),
    ) * np.clip(yunyang_alpha * 1.2, 0.0, 1.0)

    # Garment interiors intentionally exclude faces, hands, hair, silhouettes,
    # props and all alpha boundaries.  Changes are photometric-only.
    jiaotu_garment = np.maximum(
        soft_polygon(height, width, [(150, 956), (302, 956), (304, 1120), (147, 1120)], 7.0),
        soft_polygon(height, width, [(144, 1160), (302, 1160), (300, 1575), (151, 1575)], 8.0),
    ) * (jiaotu_alpha > 0.92).astype(np.float32)
    yunyang_garment = np.maximum(
        soft_polygon(height, width, [(692, 927), (794, 927), (791, 1075), (692, 1075)], 6.0),
        soft_polygon(height, width, [(703, 1110), (792, 1110), (790, 1410), (704, 1410)], 7.0),
    ) * (yunyang_alpha > 0.92).astype(np.float32)

    for mask in (jiaotu_eyes, yunyang_eyes, jiaotu_garment, yunyang_garment):
        mask[mask < 0.025] = 0.0
    allowed = np.maximum.reduce([jiaotu_eyes, yunyang_eyes, jiaotu_garment, yunyang_garment])
    return {
        "jiaotu_eyes": jiaotu_eyes,
        "yunyang_eyes": yunyang_eyes,
        "jiaotu_garment": jiaotu_garment,
        "yunyang_garment": yunyang_garment,
        "allowed": allowed,
    }


def apply_tone(frame: np.ndarray, alpha: np.ndarray, tone: np.ndarray | float) -> np.ndarray:
    delta = alpha * tone
    return np.clip(frame.astype(np.float32) + delta[:, :, None] if isinstance(delta, np.ndarray) else frame.astype(np.float32), 0, 255).astype(np.uint8)


def make_frame(source: np.ndarray, index: int, fps: int, masks: dict[str, np.ndarray]) -> tuple[np.ndarray, dict[str, float]]:
    if index == 0:
        return source.copy(), {
            "jiaotu_eye_tone": 0.0,
            "yunyang_eye_tone": 0.0,
            "jiaotu_garment_tone": 0.0,
            "yunyang_garment_tone": 0.0,
        }
    seconds = index / float(fps)
    jiaotu_eye_tone = irregular_value(seconds, (
        (0.0, 0.0), (0.58, -2.0), (1.04, -7.5), (1.27, -1.0),
        (1.89, 1.8), (2.46, -3.2), (3.12, -6.0), (3.37, -1.2), (4.0, 0.0),
    ))
    yunyang_eye_tone = irregular_value(seconds, (
        (0.0, 0.0), (0.41, 2.5), (0.96, -2.0), (1.63, 3.8),
        (2.21, -1.2), (2.83, -4.8), (3.31, 2.2), (4.0, 0.0),
    ))
    jiaotu_garment_tone = irregular_value(seconds, (
        (0.0, 0.0), (0.49, 2.2), (1.12, -1.8), (1.77, 2.8),
        (2.36, -2.2), (3.05, 1.9), (3.54, -1.5), (4.0, 0.0),
    ))
    yunyang_garment_tone = irregular_value(seconds, (
        (0.0, 0.0), (0.62, -2.0), (1.31, 1.6), (1.94, -2.6),
        (2.57, 2.1), (3.16, -1.7), (3.71, 1.2), (4.0, 0.0),
    ))

    height, width = source.shape[:2]
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    jiaotu_texture = 0.72 + 0.28 * np.clip((xx - 220.0) / 145.0, -1.0, 1.0)
    yunyang_texture = 0.76 + 0.24 * np.clip((yy - 1050.0) / 390.0, -1.0, 1.0)
    eye_gradient_jiaotu = 0.74 + 0.26 * np.clip((850.0 - yy) / 18.0, 0.0, 1.0)
    eye_gradient_yunyang = 0.70 + 0.30 * np.clip((xx - 746.0) / 38.0, -1.0, 1.0)
    delta = (
        masks["jiaotu_eyes"] * eye_gradient_jiaotu * jiaotu_eye_tone
        + masks["yunyang_eyes"] * eye_gradient_yunyang * yunyang_eye_tone
        + masks["jiaotu_garment"] * jiaotu_texture * jiaotu_garment_tone
        + masks["yunyang_garment"] * yunyang_texture * yunyang_garment_tone
    )
    result = np.clip(source.astype(np.float32) + delta[:, :, None], 0, 255).astype(np.uint8)
    # Redundant hard restore makes any future mask support regression visible.
    result[masks["allowed"] == 0.0] = source[masks["allowed"] == 0.0]
    return result, {
        "jiaotu_eye_tone": round(jiaotu_eye_tone, 6),
        "yunyang_eye_tone": round(yunyang_eye_tone, 6),
        "jiaotu_garment_tone": round(jiaotu_garment_tone, 6),
        "yunyang_garment_tone": round(yunyang_garment_tone, 6),
    }


def render(args: argparse.Namespace) -> dict:
    source_sha = sha256(args.source)
    jiaotu_sha = sha256(args.jiaotu_layer)
    yunyang_sha = sha256(args.yunyang_layer)
    if source_sha != EXPECTED_SOURCE_SHA256:
        raise RuntimeError(f"Source SHA drift: {source_sha}")
    if jiaotu_sha != EXPECTED_JIAOTU_LAYER_SHA256:
        raise RuntimeError(f"Jiaotu layer SHA drift: {jiaotu_sha}")
    if yunyang_sha != EXPECTED_YUNYANG_LAYER_SHA256:
        raise RuntimeError(f"Yunyang layer SHA drift: {yunyang_sha}")

    source = cv2.imread(str(args.source), cv2.IMREAD_COLOR)
    if source is None:
        raise RuntimeError(f"Cannot read source: {args.source}")
    height, width = source.shape[:2]
    if (width, height) != (1008, 1792):
        raise RuntimeError(f"Unexpected source dimensions: {(width, height)}")
    masks = build_masks(height, width, args.jiaotu_layer, args.yunyang_layer)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    motion_series: list[dict[str, float]] = []
    changed_outside_allowed: list[int] = []
    changed_inside_allowed: list[int] = []
    with tempfile.TemporaryDirectory(prefix="e40_u29c_v55_frames_") as temporary:
        frame_dir = Path(temporary)
        for index in range(args.frames):
            frame, motion = make_frame(source, index, args.fps, masks)
            changed = np.any(frame != source, axis=2)
            changed_outside_allowed.append(int(np.count_nonzero(changed & (masks["allowed"] == 0.0))))
            changed_inside_allowed.append(int(np.count_nonzero(changed & (masks["allowed"] > 0.0))))
            motion_series.append(motion)
            if not cv2.imwrite(str(frame_dir / f"frame_{index:03d}.png"), frame, [cv2.IMWRITE_PNG_COMPRESSION, 3]):
                raise RuntimeError("Could not write intermediate frame")
        subprocess.run([
            "ffmpeg", "-v", "error", "-y", "-framerate", str(args.fps),
            "-i", str(frame_dir / "frame_%03d.png"), "-c:v", "libx264rgb",
            "-crf", "0", "-preset", "medium", "-pix_fmt", "rgb24", "-an", str(args.output),
        ], check=True)

    source_raw_rgb = cv2.cvtColor(source, cv2.COLOR_BGR2RGB).tobytes()
    decoded_frame0 = subprocess.check_output([
        "ffmpeg", "-v", "error", "-i", str(args.output), "-frames:v", "1",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ])
    probe = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(args.output),
    ]))
    audio_count = len([row for row in probe.get("streams", []) if row.get("codec_type") == "audio"])
    layer_maxima = {
        key: max(abs(float(row[key])) for row in motion_series)
        for key in motion_series[0]
    }
    all_layers_active = all(layer_maxima[key] >= threshold for key, threshold in {
        "jiaotu_eye_tone": 5.5,
        "yunyang_eye_tone": 4.0,
        "jiaotu_garment_tone": 2.0,
        "yunyang_garment_tone": 1.8,
    }.items())
    status = "PASS" if (
        decoded_frame0 == source_raw_rgb
        and audio_count == 0
        and max(changed_outside_allowed) == 0
        and max(changed_inside_allowed) > 0
        and all_layers_active
    ) else "FAIL"
    payload = {
        "schema": "qingshan.e40.u29c.v55.local_living_reaction_render_report.v1",
        "status": status,
        "representation": "LOCAL_DETERMINISTIC_PHOTOMETRIC_MICRO_REACTION",
        "materially_different_from_quarantined_v5_seedance": True,
        "authority_trigger": "USER_DIRECTIVE_CONTINUE_GENERATION_LOCAL_ONLY_SCOPE",
        "source": str(args.source.resolve()),
        "source_sha256": source_sha,
        "jiaotu_layer": str(args.jiaotu_layer.resolve()),
        "jiaotu_layer_sha256": jiaotu_sha,
        "yunyang_layer": str(args.yunyang_layer.resolve()),
        "yunyang_layer_sha256": yunyang_sha,
        "output": str(args.output.resolve()),
        "output_sha256": sha256(args.output),
        "renderer": str(Path(__file__).resolve()),
        "renderer_sha256": sha256(Path(__file__).resolve()),
        "width": width,
        "height": height,
        "fps": args.fps,
        "frame_count": args.frames,
        "duration_seconds": args.frames / args.fps,
        "codec": "libx264rgb_crf0",
        "frame0_raw_rgb_exact": decoded_frame0 == source_raw_rgb,
        "frame0_raw_rgb_sha256": hashlib.sha256(decoded_frame0).hexdigest(),
        "source_raw_rgb_sha256": hashlib.sha256(source_raw_rgb).hexdigest(),
        "audio_stream_count": audio_count,
        "motion_policy": {
            "spatial_displacement_pixels": 0,
            "global_transform": False,
            "background_immutable": True,
            "mouths_hands_face_contours_immutable": True,
            "eyes_photometric_only": True,
            "garment_interiors_photometric_only": True,
            "non_periodic_tracks": True,
            "max_absolute_tone": {key: round(value, 6) for key, value in layer_maxima.items()},
        },
        "support_gate": {
            "allowed_support_pixels": int(np.count_nonzero(masks["allowed"])),
            "max_changed_pixels_inside_allowed": max(changed_inside_allowed),
            "max_changed_pixels_outside_allowed": max(changed_outside_allowed),
            "outside_allowed_exact": max(changed_outside_allowed) == 0,
            "all_required_layers_active": all_layers_active,
        },
        "editorial_admission": "FORBIDDEN_UNTIL_MACHINE_AND_HUMAN_QA",
        "provider_model": None,
        "provider_posts": 0,
        "provider_queries": 0,
        "transactions": 0,
        "credits": 0,
        "retries": 0,
    }
    atomic_json(args.report, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--jiaotu-layer", type=Path, required=True)
    parser.add_argument("--yunyang-layer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--frames", type=int, default=96)
    args = parser.parse_args()
    payload = render(args)
    print(json.dumps({"status": payload["status"], "output": payload["output"], "sha256": payload["output_sha256"]}))
    return 0 if payload["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
