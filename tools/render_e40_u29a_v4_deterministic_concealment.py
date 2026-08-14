#!/usr/bin/env python3
"""Render a local-only deterministic U29A jade-concealment feasibility clip.

This does not call a provider and is not an AgentCut assembly.  Frame zero is
the admitted PNG.  Only the physically visible jade component is progressively
replaced by a deterministic inpainted collar plate, while a sub-pixel lower-
robe warp supplies living breath motion outside the action mask.
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


def select_jade_mask(bgr: np.ndarray) -> tuple[np.ndarray, dict]:
    height, width = bgr.shape[:2]
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    red = (((hsv[:, :, 0] < 10) | (hsv[:, :, 0] > 170)) & (hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 30)).astype(np.uint8)
    spatial = np.zeros((height, width), np.uint8)
    spatial[880:950, 485:525] = red[880:950, 485:525]
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(spatial, 8)
    candidates = []
    expected = np.array([503.0, 920.0])
    for index in range(1, count):
        x, y, w, h, area = [int(value) for value in stats[index]]
        if area < 8:
            continue
        distance = float(np.linalg.norm(centroids[index] - expected))
        candidates.append((distance, -area, index, x, y, w, h, area))
    if not candidates:
        raise RuntimeError("No jade-colored connected component found in locked collar ROI")
    _, _, chosen, x, y, w, h, area = min(candidates)
    if not (490 <= x <= 510 and 900 <= y <= 925 and 30 <= area <= 180):
        raise RuntimeError(f"Jade component outside locked bounds: x={x} y={y} area={area}")
    core = (labels == chosen).astype(np.uint8) * 255
    mask = cv2.dilate(core, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)), iterations=1)
    locked = np.zeros_like(mask)
    locked[895:940, 490:518] = 255
    mask = cv2.bitwise_and(mask, locked)
    ys, xs = np.where(mask > 0)
    return mask, {
        "component_bbox_xywh": [x, y, w, h],
        "component_area_pixels": area,
        "expanded_mask_bbox_xyxy": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())],
        "expanded_mask_pixels": int(len(xs)),
        "expected_seed_xy": [503, 920],
    }


def red_metrics(rgb: np.ndarray, mask: np.ndarray) -> tuple[int, int]:
    pixels = rgb[mask > 0].astype(np.int32)
    visible = (pixels[:, 0] > 45) & (pixels[:, 0] > pixels[:, 1] * 1.28) & (pixels[:, 0] > pixels[:, 2] * 1.18)
    excess = np.maximum(pixels[:, 0] - np.maximum(pixels[:, 1], pixels[:, 2]), 0)
    return int(visible.sum()), int(excess.sum())


def breath_warp(frame: np.ndarray, frame_index: int, fps: int) -> np.ndarray:
    if frame_index == 0:
        return frame
    height, width = frame.shape[:2]
    phase = 2.0 * np.pi * frame_index / (fps * 2.4)
    displacement = float(0.85 * np.sin(phase))
    map_x, map_y = np.meshgrid(np.arange(width, dtype=np.float32), np.arange(height, dtype=np.float32))
    warped_y = map_y.copy()
    warped_y[1000:1650, 120:900] -= displacement
    warped = cv2.remap(frame, map_x, warped_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)
    alpha = np.zeros((height, width), np.float32)
    alpha[1020:1630, 140:880] = 1.0
    alpha = cv2.GaussianBlur(alpha, (0, 0), 18.0)[:, :, None]
    return np.clip(frame.astype(np.float32) * (1.0 - alpha) + warped.astype(np.float32) * alpha, 0, 255).astype(np.uint8)


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
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="e40_u29a_v4_frames_") as temporary:
        frame_dir = Path(temporary)
        for index in range(frames):
            if index == 0:
                composed = bgr.copy()
            else:
                progress = min(1.0, index / float(round(1.2 * fps)))
                alpha_values = np.clip((progress - disappear_at) / fade_width, 0.0, 1.0)
                alpha = np.zeros((height, width), np.float32)
                alpha[ys, xs] = alpha_values.astype(np.float32)
                alpha = alpha[:, :, None]
                composed = np.clip(bgr.astype(np.float32) * (1.0 - alpha) + hidden_plate.astype(np.float32) * alpha, 0, 255).astype(np.uint8)
                composed = breath_warp(composed, index, fps)
            rgb = cv2.cvtColor(composed, cv2.COLOR_BGR2RGB)
            visible, excess = red_metrics(rgb, mask)
            area_series.append(visible)
            red_excess_series.append(excess)
            cv2.imwrite(str(frame_dir / f"frame_{index:03d}.png"), composed, [cv2.IMWRITE_PNG_COMPRESSION, 3])

        command = [
            "ffmpeg", "-v", "error", "-y", "-framerate", str(fps),
            "-i", str(frame_dir / "frame_%03d.png"), "-c:v", "libx264rgb",
            "-crf", "0", "-preset", "medium", "-pix_fmt", "rgb24", "-an", str(output),
        ]
        subprocess.run(command, check=True)

    source_rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).tobytes()
    decoded_frame0 = subprocess.check_output([
        "ffmpeg", "-v", "error", "-i", str(output), "-frames:v", "1",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ])
    probe = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(output),
    ]))
    audio_streams = [row for row in probe.get("streams", []) if row.get("codec_type") == "audio"]
    monotonic_area = all(b <= a for a, b in zip(area_series, area_series[1:30]))
    monotonic_red = all(b <= a for a, b in zip(red_excess_series, red_excess_series[1:30]))
    payload = {
        "schema": "qingshan.e40.u29a.v4.deterministic_local_render_report.v1",
        "status": "PASS" if decoded_frame0 == source_rgb and monotonic_area and monotonic_red and not audio_streams else "FAIL",
        "source": str(source),
        "source_sha256": sha256(source),
        "output": str(output),
        "output_sha256": sha256(output),
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
        "jade_mask": mask_meta,
        "jade_visible_area_first_30_frames": area_series[:30],
        "jade_red_excess_first_30_frames": red_excess_series[:30],
        "monotonic_nonincreasing_visible_area_0_to_1_2s": monotonic_area,
        "monotonic_nonincreasing_red_excess_0_to_1_2s": monotonic_red,
        "editorial_admission": "FORBIDDEN_FEASIBILITY_TEST_ONLY",
        "provider_posts": 0,
        "transactions": 0,
        "credits": 0,
    }
    atomic_json(report, payload)
    if payload["status"] != "PASS":
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
