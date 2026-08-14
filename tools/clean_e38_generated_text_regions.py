#!/usr/bin/env python3
"""Remove bounded generated captions and cabinet label plates without paid rerolls."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import cv2
import numpy as np


def parse_band(value: str) -> tuple[int, int, float, float]:
    y0, y1, start, end = value.split(":")
    return int(y0), int(y1), float(start), float(end)


def parse_roi(value: str) -> tuple[int, int, int, int]:
    x, y, width, height = value.split(":")
    return int(x), int(y), int(width), int(height)


def parse_ellipse(value: str) -> tuple[int, int, int, int]:
    center_x, center_y, radius_x, radius_y = value.split(":")
    return int(center_x), int(center_y), int(radius_x), int(radius_y)


def parse_timed_roi(value: str) -> tuple[int, int, int, int, float, float]:
    x, y, width, height, start, end = value.split(":")
    return int(x), int(y), int(width), int(height), float(start), float(end)


def caption_mask(frame: np.ndarray, y0: int, y1: int) -> np.ndarray:
    height, width = frame.shape[:2]
    y0, y1 = max(0, y0), min(height, y1)
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    raw = ((hsv[:, :, 1] < 72) & (hsv[:, :, 2] > 166)).astype(np.uint8) * 255
    bounded = np.zeros((height, width), dtype=np.uint8)
    bounded[y0:y1] = raw[y0:y1]
    bounded = cv2.morphologyEx(
        bounded,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (5, 3)),
    )
    mask = np.zeros_like(bounded)
    for contour in cv2.findContours(bounded, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
        x, y, box_width, box_height = cv2.boundingRect(contour)
        area = box_width * box_height
        if 18 <= area <= 24000 and 3 <= box_width <= 820 and 3 <= box_height <= 135:
            cv2.drawContours(mask, [contour], -1, 255, thickness=-1)
    return cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))


def cabinet_mask(frame: np.ndarray, roi: tuple[int, int, int, int]) -> np.ndarray:
    height, width = frame.shape[:2]
    x0, y0, roi_width, roi_height = roi
    x1, y1 = min(width, x0 + roi_width), min(height, y0 + roi_height)
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    raw = ((hsv[:, :, 1] < 112) & (hsv[:, :, 2] > 106)).astype(np.uint8) * 255
    bounded = np.zeros((height, width), dtype=np.uint8)
    bounded[y0:y1, x0:x1] = raw[y0:y1, x0:x1]
    bounded = cv2.morphologyEx(
        bounded,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (9, 5)),
    )
    value = hsv[:, :, 2]
    mask = np.zeros_like(bounded)
    for contour in cv2.findContours(bounded, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
        x, y, box_width, box_height = cv2.boundingRect(contour)
        area = box_width * box_height
        aspect = box_width / max(box_height, 1)
        if not (130 <= area <= 16000 and 12 <= box_width <= 240 and 8 <= box_height <= 120 and 0.45 <= aspect <= 7.0):
            continue
        pad = 8
        rx0, ry0 = max(0, x - pad), max(0, y - pad)
        rx1, ry1 = min(width, x + box_width + pad), min(height, y + box_height + pad)
        inside = float(value[y:y + box_height, x:x + box_width].mean())
        ring = value[ry0:ry1, rx0:rx1].copy()
        ring[pad:pad + box_height, pad:pad + box_width] = 0
        ring_values = ring[ring > 0]
        if ring_values.size and inside - float(ring_values.mean()) >= 24:
            cv2.rectangle(mask, (max(0, x - 5), max(0, y - 5)), (min(width - 1, x + box_width + 5), min(height - 1, y + box_height + 5)), 255, -1)
    return mask


def apply_bounded_defocus(
    frame: np.ndarray,
    rois: list[tuple[int, int, int, int]],
    preserved: list[tuple[int, int, int, int]],
) -> np.ndarray:
    if not rois:
        return frame
    height, width = frame.shape[:2]
    alpha = np.zeros((height, width), dtype=np.uint8)
    for x, y, roi_width, roi_height in rois:
        cv2.rectangle(alpha, (x, y), (min(width - 1, x + roi_width), min(height - 1, y + roi_height)), 255, -1)
    for center_x, center_y, radius_x, radius_y in preserved:
        cv2.ellipse(alpha, (center_x, center_y), (radius_x, radius_y), 0, 0, 360, 0, -1)
    alpha = cv2.GaussianBlur(alpha, (51, 51), 0).astype(np.float32)[:, :, None] / 255.0
    blurred = cv2.GaussianBlur(frame, (61, 61), 0)
    return np.clip(frame * (1.0 - alpha) + blurred * alpha, 0, 255).astype(np.uint8)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--caption-band", action="append", default=[], type=parse_band)
    parser.add_argument("--cabinet-roi", action="append", default=[], type=parse_roi)
    parser.add_argument("--defocus-roi", action="append", default=[], type=parse_roi)
    parser.add_argument("--timed-defocus-roi", action="append", default=[], type=parse_timed_roi)
    parser.add_argument("--preserve-ellipse", action="append", default=[], type=parse_ellipse)
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
    frame_index = 0
    altered_frames = 0
    altered_pixels = 0
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        seconds = frame_index / fps
        active_defocus = list(args.defocus_roi)
        active_defocus.extend(
            (x, y, width, height)
            for x, y, width, height, start, end in args.timed_defocus_roi
            if start <= seconds <= end
        )
        if active_defocus:
            frame = apply_bounded_defocus(frame, active_defocus, args.preserve_ellipse)
        mask = np.zeros((height, width), dtype=np.uint8)
        for y0, y1, start, end in args.caption_band:
            if start <= seconds <= end:
                mask = cv2.bitwise_or(mask, caption_mask(frame, y0, y1))
        for roi in args.cabinet_roi:
            mask = cv2.bitwise_or(mask, cabinet_mask(frame, roi))
        changed = int(np.count_nonzero(mask))
        if changed:
            frame = cv2.inpaint(frame, mask, 5, cv2.INPAINT_TELEA)
            altered_frames += 1
            altered_pixels += changed
        writer.write(frame)
        frame_index += 1
    capture.release()
    writer.release()

    try:
        from imageio_ffmpeg import get_ffmpeg_exe

        ffmpeg = get_ffmpeg_exe()
    except ImportError:
        ffmpeg = "ffmpeg"
    subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(silent), "-i", str(source),
            "-map", "0:v:0", "-map", "1:a?", "-c:v", "libx264", "-crf", "17",
            "-preset", "medium", "-c:a", "copy", "-shortest", str(output),
        ],
        check=True,
    )
    silent.unlink(missing_ok=True)
    print(f"frames={frame_index} altered_frames={altered_frames} altered_pixels={altered_pixels} output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
