#!/usr/bin/env python3
"""Deterministic local U29C articulated-head renderer.

Later frames are recomposed from the SHA-pinned clean hall, shadow recipe and
admitted RGBA character layers.  Each head is separated from its fixed body and
sheared about a fixed neck pivot with a distinct signed, non-periodic track.
Frame zero is always the admitted integrated plate byte-for-byte after decode.
No provider or network capability exists in this renderer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from render_e40_u29c_v55_local_living_reaction import atomic_json, irregular_value, sha256


EXPECTED = {
    "source": "962bf54654a66e01ada6fe0924a28252a7d1114e44efe889360a427183c4aadd",
    "clean_hall": "2d18e76c9989618d46c699d976d2f5491e9d662df3c3f40c81f5dd76f6c011a2",
    "jiaotu": "b205169fd657be9b719c8235bb836b307820ff3569265cae6e6edda52ef2a731",
    "yunyang": "2b191009a679db656bc3823e1fbe43882e78d4af867c8b20df62b0c55937f8db",
    "failure_memory": "32f3df2bd1e72e388a64acdeec0db855ef8f3a2a43f46c64f8540ae257b29f71",
    "spec": "d8b60afa366b5b1c398153e426f7160ff7bb48e926c55834613596dd9a76ca79",
}


def verify_authorities(args: argparse.Namespace) -> None:
    actual = {
        "source": sha256(args.source),
        "clean_hall": sha256(args.clean_hall),
        "jiaotu": sha256(args.jiaotu_layer),
        "yunyang": sha256(args.yunyang_layer),
        "failure_memory": sha256(args.failure_memory),
        "spec": sha256(args.spec),
    }
    drift = {key: [EXPECTED[key], value] for key, value in actual.items() if value != EXPECTED[key]}
    if drift:
        raise RuntimeError(f"Authority SHA drift: {drift}")


def shadowed_hall(clean_hall: Path) -> Image.Image:
    base = Image.open(clean_hall).convert("RGBA")
    shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(shadow)
    draw.ellipse((100, 1640, 426, 1750), fill=(15, 7, 3, 105))
    draw.ellipse((668, 1432, 899, 1502), fill=(12, 6, 3, 70))
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    base.alpha_composite(shadow)
    return base


def head_weight(shape: tuple[int, int], points: list[tuple[int, int]], sigma: float) -> np.ndarray:
    height, width = shape
    mask = np.zeros((height, width), np.float32)
    cv2.fillPoly(mask, [np.asarray(points, np.int32)], 1.0)
    mask = cv2.GaussianBlur(mask, (0, 0), sigma)
    mask[mask < 0.01] = 0.0
    return mask


def split_layer(layer: np.ndarray, which: str) -> tuple[np.ndarray, np.ndarray, dict]:
    height, width = layer.shape[:2]
    if which == "jiaotu":
        points = [(102, 0), (250, 0), (258, 155), (236, 224), (205, 258), (139, 258), (102, 222), (88, 150)]
        pivot = (174.0, 246.0)
        nominal_shear = -math.tan(math.radians(3.0))
    elif which == "yunyang":
        points = [(62, 0), (191, 0), (194, 118), (177, 174), (151, 201), (102, 201), (75, 173), (58, 112)]
        pivot = (126.0, 192.0)
        nominal_shear = math.tan(math.radians(2.0))
    else:
        raise ValueError(which)
    weight = head_weight((height, width), points, 5.0)
    alpha = layer[:, :, 3].astype(np.float32) / 255.0
    head_alpha = alpha * weight
    body_alpha = alpha * (1.0 - weight)
    head = layer.copy()
    body = layer.copy()
    head[:, :, 3] = np.clip(np.rint(head_alpha * 255.0), 0, 255).astype(np.uint8)
    body[:, :, 3] = np.clip(np.rint(body_alpha * 255.0), 0, 255).astype(np.uint8)
    return body, head, {
        "weight": weight,
        "pivot": pivot,
        "nominal_shear": nominal_shear,
        "equivalent_degrees": round(math.degrees(math.atan(abs(nominal_shear))), 6),
    }


def warp_premultiplied_rgba(layer: np.ndarray, shear: float, pivot_y: float) -> np.ndarray:
    height, width = layer.shape[:2]
    alpha = layer[:, :, 3].astype(np.float32) / 255.0
    premultiplied = layer[:, :, :3].astype(np.float32) * alpha[:, :, None]
    matrix = np.asarray([[1.0, shear, -shear * pivot_y], [0.0, 1.0, 0.0]], np.float32)
    warped_alpha = cv2.warpAffine(alpha, matrix, (width, height), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=0.0)
    warped_premultiplied = cv2.warpAffine(premultiplied, matrix, (width, height), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=(0.0, 0.0, 0.0))
    warped_alpha = np.clip(warped_alpha, 0.0, 1.0)
    rgb = np.zeros_like(warped_premultiplied)
    valid = warped_alpha > 1e-5
    rgb[valid] = warped_premultiplied[valid] / warped_alpha[valid, None]
    output = np.dstack([
        np.clip(np.rint(rgb), 0, 255).astype(np.uint8),
        np.clip(np.rint(warped_alpha * 255.0), 0, 255).astype(np.uint8),
    ])
    return output


def alpha_composite_cv(background: np.ndarray, foreground: np.ndarray, xy: tuple[int, int]) -> np.ndarray:
    result = background.astype(np.float32)
    x, y = xy
    height, width = foreground.shape[:2]
    region = result[y:y + height, x:x + width]
    alpha = foreground[:, :, 3:4].astype(np.float32) / 255.0
    region[:] = foreground[:, :, :3].astype(np.float32) * alpha + region * (1.0 - alpha)
    return np.clip(np.rint(result), 0, 255).astype(np.uint8)


def articulation_amplitudes(seconds: float) -> tuple[float, float]:
    # Signed tracks differ in both extrema and keyframe timing.  They approach
    # hall center between 0.5 and 1.2 seconds, then settle independently.
    jiaotu = irregular_value(seconds, (
        (0.0, 0.0), (0.50, 0.0), (0.83, 0.56), (1.20, 1.0),
        (1.52, 0.48), (1.80, 0.22), (2.44, 0.31), (3.17, 0.17), (4.0, 0.20),
    ))
    yunyang = irregular_value(seconds, (
        (0.0, 0.0), (0.50, 0.0), (0.91, 0.72), (1.20, 1.0),
        (1.43, 0.55), (1.80, 0.18), (2.21, 0.25), (2.86, 0.12), (3.55, 0.23), (4.0, 0.16),
    ))
    return jiaotu, yunyang


def prepare(args: argparse.Namespace) -> dict:
    verify_authorities(args)
    source = cv2.imread(str(args.source), cv2.IMREAD_COLOR)
    if source is None:
        raise RuntimeError("Cannot decode source")
    jiaotu = cv2.imread(str(args.jiaotu_layer), cv2.IMREAD_UNCHANGED)
    yunyang = cv2.imread(str(args.yunyang_layer), cv2.IMREAD_UNCHANGED)
    if jiaotu is None or yunyang is None or jiaotu.shape[2] != 4 or yunyang.shape[2] != 4:
        raise RuntimeError("Cannot decode exact RGBA layers")
    # OpenCV BGRA is intentional because all later video frames are BGR.
    jiaotu_body, jiaotu_head, jiaotu_meta = split_layer(jiaotu, "jiaotu")
    yunyang_body, yunyang_head, yunyang_meta = split_layer(yunyang, "yunyang")
    base_rgb = np.asarray(shadowed_hall(args.clean_hall).convert("RGB"))
    base_bgr = cv2.cvtColor(base_rgb, cv2.COLOR_RGB2BGR)
    exact = alpha_composite_cv(alpha_composite_cv(base_bgr, yunyang, (617, 756)), jiaotu, (58, 707))
    recomposition_mae = float(np.abs(exact.astype(np.int16) - source.astype(np.int16)).mean())
    return {
        "source": source,
        "base": base_bgr,
        "jiaotu": jiaotu,
        "yunyang": yunyang,
        "jiaotu_body": jiaotu_body,
        "jiaotu_head": jiaotu_head,
        "jiaotu_meta": jiaotu_meta,
        "yunyang_body": yunyang_body,
        "yunyang_head": yunyang_head,
        "yunyang_meta": yunyang_meta,
        "exact_recomposition_mae": recomposition_mae,
    }


def make_frame(prepared: dict, index: int, fps: int) -> tuple[np.ndarray, dict]:
    if index == 0:
        return prepared["source"].copy(), {
            "jiaotu_amplitude": 0.0,
            "yunyang_amplitude": 0.0,
            "jiaotu_equivalent_degrees": 0.0,
            "yunyang_equivalent_degrees": 0.0,
        }
    seconds = index / float(fps)
    jiaotu_amplitude, yunyang_amplitude = articulation_amplitudes(seconds)
    jiaotu_shear = prepared["jiaotu_meta"]["nominal_shear"] * jiaotu_amplitude
    yunyang_shear = prepared["yunyang_meta"]["nominal_shear"] * yunyang_amplitude
    jiaotu_head = warp_premultiplied_rgba(prepared["jiaotu_head"], jiaotu_shear, prepared["jiaotu_meta"]["pivot"][1])
    yunyang_head = warp_premultiplied_rgba(prepared["yunyang_head"], yunyang_shear, prepared["yunyang_meta"]["pivot"][1])
    frame = prepared["base"].copy()
    frame = alpha_composite_cv(frame, prepared["yunyang_body"], (617, 756))
    frame = alpha_composite_cv(frame, yunyang_head, (617, 756))
    frame = alpha_composite_cv(frame, prepared["jiaotu_body"], (58, 707))
    frame = alpha_composite_cv(frame, jiaotu_head, (58, 707))
    return frame, {
        "jiaotu_amplitude": round(jiaotu_amplitude, 6),
        "yunyang_amplitude": round(yunyang_amplitude, 6),
        "jiaotu_equivalent_degrees": round(math.degrees(math.atan(abs(jiaotu_shear))), 6),
        "yunyang_equivalent_degrees": round(math.degrees(math.atan(abs(yunyang_shear))), 6),
    }


def render(args: argparse.Namespace) -> dict:
    prepared = prepare(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    motion: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="e40_u29c_v58_frames_") as temporary:
        frame_dir = Path(temporary)
        for index in range(args.frames):
            frame, metadata = make_frame(prepared, index, args.fps)
            motion.append(metadata)
            if not cv2.imwrite(str(frame_dir / f"frame_{index:03d}.png"), frame, [cv2.IMWRITE_PNG_COMPRESSION, 3]):
                raise RuntimeError("Could not write frame")
        subprocess.run([
            "ffmpeg", "-v", "error", "-y", "-framerate", str(args.fps),
            "-i", str(frame_dir / "frame_%03d.png"), "-c:v", "libx264rgb",
            "-crf", "0", "-preset", "medium", "-pix_fmt", "rgb24", "-an", str(args.output),
        ], check=True)
    source_raw = cv2.cvtColor(prepared["source"], cv2.COLOR_BGR2RGB).tobytes()
    decoded_frame0 = subprocess.check_output([
        "ffmpeg", "-v", "error", "-i", str(args.output), "-frames:v", "1",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ])
    probe = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(args.output),
    ]))
    audio_count = len([item for item in probe.get("streams", []) if item.get("codec_type") == "audio"])
    peak_jiaotu = max(row["jiaotu_equivalent_degrees"] for row in motion)
    peak_yunyang = max(row["yunyang_equivalent_degrees"] for row in motion)
    status = "PASS_RENDER_PENDING_MACHINE_AND_HUMAN_QA" if (
        decoded_frame0 == source_raw
        and audio_count == 0
        and 2.9 <= peak_jiaotu <= 3.1
        and 1.9 <= peak_yunyang <= 2.1
    ) else "FAIL_CLOSED"
    report = {
        "schema": "qingshan.e40.u29c.v58.articulated_head_render_report.v1",
        "status": status,
        "source_sha256": sha256(args.source),
        "clean_hall_sha256": sha256(args.clean_hall),
        "jiaotu_layer_sha256": sha256(args.jiaotu_layer),
        "yunyang_layer_sha256": sha256(args.yunyang_layer),
        "failure_memory_sha256": sha256(args.failure_memory),
        "spec_sha256": sha256(args.spec),
        "renderer_sha256": sha256(Path(__file__).resolve()),
        "output": str(args.output.resolve()),
        "output_sha256": sha256(args.output),
        "frame0_raw_rgb_exact": decoded_frame0 == source_raw,
        "audio_stream_count": audio_count,
        "fps": args.fps,
        "frame_count": args.frames,
        "duration_seconds": args.frames / args.fps,
        "articulation": {
            "jiaotu_peak_equivalent_degrees": peak_jiaotu,
            "yunyang_peak_equivalent_degrees": peak_yunyang,
            "opposite_signed_shears": prepared["jiaotu_meta"]["nominal_shear"] * prepared["yunyang_meta"]["nominal_shear"] < 0,
            "distinct_tracks": True,
            "neck_pivots_fixed": True,
            "body_layers_fixed": True,
        },
        "provider_posts": 0,
        "provider_queries": 0,
        "transactions": 0,
        "credits": 0,
        "retries": 0,
        "editorial_admission": False,
    }
    atomic_json(args.report, report)
    return report


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--source", type=Path, required=True)
    result.add_argument("--clean-hall", type=Path, required=True)
    result.add_argument("--jiaotu-layer", type=Path, required=True)
    result.add_argument("--yunyang-layer", type=Path, required=True)
    result.add_argument("--failure-memory", type=Path, required=True)
    result.add_argument("--spec", type=Path, required=True)
    result.add_argument("--output", type=Path, required=True)
    result.add_argument("--report", type=Path, required=True)
    result.add_argument("--fps", type=int, default=24)
    result.add_argument("--frames", type=int, default=96)
    return result


def main() -> int:
    args = parser().parse_args()
    report = render(args)
    print(json.dumps({"status": report["status"], "output": report["output"], "sha256": report["output_sha256"]}))
    return 0 if report["status"].startswith("PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
