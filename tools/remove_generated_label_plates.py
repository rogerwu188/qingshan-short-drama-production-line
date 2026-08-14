#!/usr/bin/env python3
"""Remove small generated label plates while preserving actors and large paper props."""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np


def label_boxes(frame: np.ndarray, max_x_ratio: float) -> list[tuple[int, int, int, int]]:
    height, width = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    mask = ((saturation < 105) & (value > 112)).astype(np.uint8) * 255
    mask[:, int(width * max_x_ratio) :] = 0
    mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (7, 5)),
    )
    boxes: list[tuple[int, int, int, int]] = []
    for contour in cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
        x, y, w, h = cv2.boundingRect(contour)
        area = w * h
        aspect = w / max(h, 1)
        if 120 <= area <= 3200 and 10 <= w <= 110 and 7 <= h <= 55 and 0.75 <= aspect <= 4.5:
            boxes.append((x, y, w, h))
    return boxes


def pixelate(region: np.ndarray) -> np.ndarray:
    height, width = region.shape[:2]
    small = cv2.resize(region, (max(1, width // 10), max(1, height // 10)), interpolation=cv2.INTER_AREA)
    return cv2.resize(small, (width, height), interpolation=cv2.INTER_LINEAR)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-x-ratio", type=float, default=0.62)
    args = parser.parse_args()

    source = Path(args.input)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise SystemExit(f"cannot open {source}")
    fps = capture.get(cv2.CAP_PROP_FPS) or 24.0
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    silent = output.with_suffix(".silent.mp4")
    writer = cv2.VideoWriter(str(silent), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    frames = 0
    box_count = 0
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        for x, y, w, h in label_boxes(frame, args.max_x_ratio):
            pad_x, pad_y = max(3, w // 8), max(3, h // 6)
            x0, y0 = max(0, x - pad_x), max(0, y - pad_y)
            x1, y1 = min(width, x + w + pad_x), min(height, y + h + pad_y)
            frame[y0:y1, x0:x1] = pixelate(frame[y0:y1, x0:x1])
            box_count += 1
        writer.write(frame)
        frames += 1
    capture.release()
    writer.release()

    # Restore the untouched provider audio while converting the OpenCV stream to H.264.
    import subprocess

    try:
        from imageio_ffmpeg import get_ffmpeg_exe
        ffmpeg = get_ffmpeg_exe()
    except ImportError:
        ffmpeg = "ffmpeg"
    subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(silent), "-i", str(source),
            "-map", "0:v:0", "-map", "1:a?", "-c:v", "libx264", "-crf", "18",
            "-preset", "medium", "-c:a", "copy", "-shortest", str(output),
        ],
        check=True,
    )
    silent.unlink(missing_ok=True)
    print(f"frames={frames} label_boxes={box_count} output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
