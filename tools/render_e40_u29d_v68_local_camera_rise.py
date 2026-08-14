#!/usr/bin/env python3
"""Render E40 U29D V68 as a deterministic, zero-cost local camera-rise candidate."""

from __future__ import annotations

import argparse
import math
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw


FPS = 24
DURATION = 2.625
FRAME_COUNT = 63
OUT_W = 720
OUT_H = 1280


def smoothstep(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def render_frame(source: Image.Image, index: int) -> Image.Image:
    progress = index / (FRAME_COUNT - 1)
    # Complete the physical rise by the 1.2s contract boundary so Wuyun has
    # fully cleared the lower frame instead of lingering as a partial silhouette.
    rise_boundary = 1.2 / DURATION
    rise = smoothstep(min(progress / rise_boundary, 1.0))
    zoom = 1.0 + 1.18 * rise
    # Keep the shot physically alive after the cat clears. A second slower,
    # nonperiodic rise crosses the curtain and timber instead of holding a crop.
    fade_start = 1.9 / DURATION
    if progress > rise_boundary:
        continuation = smoothstep(min((progress - rise_boundary) / (fade_start - rise_boundary), 1.0))
        zoom += 0.34 * continuation

    crop_w = max(2, round(source.width / zoom))
    crop_h = max(2, round(source.height / zoom))
    crop_x = round((source.width - crop_w) * 0.50)
    crop_y = 0
    frame = source.crop((crop_x, crop_y, crop_x + crop_w, crop_y + crop_h))
    frame = frame.resize((OUT_W, OUT_H), Image.Resampling.LANCZOS)

    # Two sparse, deterministic flakes cross the cold window edge only.
    flake_start = 1.9 / DURATION
    flake_end = 2.48 / DURATION
    if flake_start <= progress <= flake_end:
        draw = ImageDraw.Draw(frame, "RGBA")
        local = (progress - flake_start) / (flake_end - flake_start)
        flakes = ((618, 260, 3, 180), (665, 390, 2, 145))
        for seed_x, seed_y, radius, alpha in flakes:
            x = seed_x - round(22 * local)
            y = seed_y + round(150 * local)
            pulse = 0.75 + 0.25 * math.sin(local * math.pi)
            a = round(alpha * pulse)
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(228, 238, 244, a))

    # Authored continuous fade to black begins at 1.9 seconds.
    if progress >= fade_start:
        fade = smoothstep((progress - fade_start) / (1.0 - fade_start))
        black = Image.new("RGB", frame.size, (0, 0, 0))
        frame = Image.blend(frame, black, fade)
    return frame


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    source = Image.open(args.input).convert("RGB")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="e40_u29d_v68_") as temp_dir:
        temp = Path(temp_dir)
        for index in range(FRAME_COUNT):
            render_frame(source, index).save(temp / f"frame_{index:04d}.png", compress_level=2)
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-framerate", str(FPS), "-i", str(temp / "frame_%04d.png"),
                "-c:v", "libx264", "-preset", "slow", "-crf", "12",
                "-pix_fmt", "yuv444p", "-movflags", "+faststart", str(args.output),
            ],
            check=True,
        )


if __name__ == "__main__":
    main()
