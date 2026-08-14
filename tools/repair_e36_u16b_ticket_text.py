#!/usr/bin/env python3
"""Remove unauthorized pseudo-text from the tracked U16B ticket surface."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/video_repair_v2_outputs/E36_E36-CW-U16B-VIDEO-V1_41086408-36bb-454b-b956-01125c388b09.mp4"
OUTPUT = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/video_repair_v2_outputs/E36_E36-CW-U16B-VIDEO-V1_41086408-36bb-454b-b956-01125c388b09_TICKET_TEXT_REPAIR_V1.mp4"
SILENT = OUTPUT.with_name(OUTPUT.stem + "_silent.mp4")
REPORT = ROOT / "qa/e36_v2_stills_repair_20260729/u16_video_runtime/E36_U16B_TICKET_TEXT_REPAIR_REPORT_V1.json"
FFMPEG = shutil.which("ffmpeg") or str(
    next((ROOT / ".agentcut_env").glob("lib/python*/site-packages/agentcut/vendor/darwin-arm64/ffmpeg"))
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def feature_points(gray: np.ndarray, polygon: np.ndarray) -> np.ndarray:
    mask = np.zeros_like(gray)
    cv2.fillConvexPoly(mask, polygon.astype(np.int32), 255)
    points = cv2.goodFeaturesToTrack(
        gray,
        maxCorners=80,
        qualityLevel=0.01,
        minDistance=4,
        mask=mask,
        blockSize=5,
    )
    if points is None or len(points) < 8:
        raise RuntimeError("insufficient ticket features for tracking")
    return points


def clean_ticket(frame: np.ndarray, polygon: np.ndarray) -> tuple[np.ndarray, int]:
    polygon_i = polygon.astype(np.int32)
    surface = np.zeros(frame.shape[:2], dtype=np.uint8)
    cv2.fillConvexPoly(surface, polygon_i, 255)
    surface = cv2.erode(surface, np.ones((13, 13), np.uint8), iterations=1)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    paper_l = lab[:, :, 0]
    dark = ((gray < 145) & (paper_l < 175)).astype(np.uint8) * 255
    text_mask = cv2.bitwise_and(dark, surface)
    text_mask = cv2.morphologyEx(text_mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    text_mask = cv2.dilate(text_mask, np.ones((5, 5), np.uint8), iterations=1)
    cleaned = cv2.inpaint(frame, text_mask, 5, cv2.INPAINT_TELEA)
    return cleaned, int(np.count_nonzero(text_mask))


def main() -> int:
    capture = cv2.VideoCapture(str(SOURCE))
    if not capture.isOpened():
        raise SystemExit(f"cannot open {SOURCE}")
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 24.0)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(SILENT),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )
    ok, first = capture.read()
    if not ok:
        raise SystemExit("source has no frames")

    # Clockwise ticket corners measured on the 720x1280 first frame.
    polygon = np.array([[281.0, 792.0], [361.0, 778.0], [493.0, 899.0], [407.0, 925.0]], dtype=np.float32)
    previous_gray = cv2.cvtColor(first, cv2.COLOR_BGR2GRAY)
    previous_points = feature_points(previous_gray, polygon)
    cleaned, masked_pixels = clean_ticket(first, polygon)
    writer.write(cleaned)
    masked_pixel_counts = [masked_pixels]
    tracking_failures = 0
    written = 1

    while True:
        ok, frame = capture.read()
        if not ok:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        next_points, status, _ = cv2.calcOpticalFlowPyrLK(
            previous_gray,
            gray,
            previous_points,
            None,
            winSize=(31, 31),
            maxLevel=3,
            criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
        )
        valid = status.reshape(-1).astype(bool) if status is not None else np.zeros(0, dtype=bool)
        if next_points is None or valid.sum() < 6:
            tracking_failures += 1
        else:
            transform, inliers = cv2.estimateAffine2D(
                previous_points.reshape(-1, 2)[valid],
                next_points.reshape(-1, 2)[valid],
                method=cv2.RANSAC,
                ransacReprojThreshold=3.0,
            )
            if transform is None or inliers is None or int(inliers.sum()) < 4:
                tracking_failures += 1
            else:
                polygon = cv2.transform(polygon.reshape(1, -1, 2), transform).reshape(-1, 2)
        cleaned, masked_pixels = clean_ticket(frame, polygon)
        writer.write(cleaned)
        masked_pixel_counts.append(masked_pixels)
        written += 1
        previous_gray = gray
        try:
            previous_points = feature_points(gray, polygon)
        except RuntimeError:
            tracking_failures += 1
            previous_points = next_points[valid].reshape(-1, 1, 2) if next_points is not None and valid.any() else previous_points

    capture.release()
    writer.release()
    subprocess.run(
        [
            FFMPEG,
            "-hide_banner",
            "-y",
            "-i",
            str(SILENT),
            "-i",
            str(SOURCE),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-crf",
            "16",
            "-preset",
            "medium",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            "-shortest",
            str(OUTPUT),
        ],
        check=True,
        capture_output=True,
    )
    SILENT.unlink(missing_ok=True)
    report = {
        "schema": "qingshan.zero_credit_ticket_text_repair.v1",
        "episode": "E36",
        "unit": "U16B",
        "status": "PASS" if tracking_failures == 0 and written == frame_count else "FAIL_REVIEW_REQUIRED",
        "source": str(SOURCE.relative_to(ROOT)),
        "source_sha256": sha(SOURCE),
        "output": str(OUTPUT.relative_to(ROOT)),
        "output_sha256": sha(OUTPUT),
        "credits": 0,
        "fps": fps,
        "source_frame_count": frame_count,
        "written_frame_count": written,
        "tracking_failures": tracking_failures,
        "masked_pixels_min": min(masked_pixel_counts),
        "masked_pixels_max": max(masked_pixel_counts),
        "method": "sequential LK feature tracking plus affine RANSAC; dark pseudo-text in the eroded ticket interior is inpainted while ticket edges and hands remain unchanged",
        "audio_policy": "original video-model-native audio stream copied without modification",
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
