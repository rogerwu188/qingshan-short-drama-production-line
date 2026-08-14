#!/usr/bin/env python3
"""Build an independent zero-credit U04 motion plate from the admitted authority.

The failed provider clip is never read. Frame zero is the admitted authority;
later frames add bounded frost recession, hand/wrist pressure, gaze movement and
candle micro-flicker. The output intentionally contains no audio stream.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
AUTHORITY = ROOT / "working_assets/e40_preproduction_20260814/u04_v2_imagegen_coherent_exact_start_frame_v1/E40_U04_V2_IMAGEGEN_COHERENT_EXACT_START_FRAME_720X1280_V1.png"
AUTHORITY_SHA = "c7604c76ba3f56e1ccab8a0c400fe3cf039091c37551bdf5259376204ccd853a"
OUT_DIR = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u04_v4_local_authority_motion_v1"
VIDEO = OUT_DIR / "E40_U04_V4_LOCAL_AUTHORITY_MOTION_CANDIDATE_V1.mp4"
CONTACT = OUT_DIR / "E40_U04_V4_LOCAL_AUTHORITY_MOTION_CONTACT_SHEET_V1.png"
SPEC = OUT_DIR / "E40_U04_V4_LOCAL_AUTHORITY_MOTION_SPEC_V1.json"
RECEIPT = ROOT / "workflow/tasks/E40_U04_V4_LOCAL_AUTHORITY_MOTION_BUILD_20260814.json"
MOTION_PROFILE = "V4"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def smoothstep(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def soft_ellipse(shape: tuple[int, int], center: tuple[int, int], axes: tuple[int, int], sigma: float) -> np.ndarray:
    mask = np.zeros(shape, np.uint8)
    cv2.ellipse(mask, center, axes, 0, 0, 360, 255, -1)
    return cv2.GaussianBlur(mask, (0, 0), sigma).astype(np.float32) / 255.0


def detect_frost(source: np.ndarray) -> np.ndarray:
    b, g, r = cv2.split(source.astype(np.int16))
    chroma = ((b - r > 18) & (b - g > 3) & (b > 135)).astype(np.uint8) * 255
    region = np.zeros(chroma.shape, np.uint8)
    cv2.ellipse(region, (386, 1002), (110, 82), -10, 0, 360, 255, -1)
    mask = cv2.bitwise_and(chroma, region)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), iterations=1)
    mask = cv2.dilate(mask, np.ones((5, 5), np.uint8), iterations=1)
    return mask


def main() -> int:
    global OUT_DIR, VIDEO, CONTACT, SPEC, RECEIPT, MOTION_PROFILE
    parser = argparse.ArgumentParser()
    parser.add_argument("--cadence-repair-v5", action="store_true")
    parser.add_argument("--semantic-repair-v6", action="store_true")
    args = parser.parse_args()
    if args.cadence_repair_v5 and args.semantic_repair_v6:
        raise SystemExit("choose one repair profile")
    if args.cadence_repair_v5:
        MOTION_PROFILE = "V5_CADENCE_REPAIR"
        OUT_DIR = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u04_v5_local_authority_cadence_repair_v1"
        VIDEO = OUT_DIR / "E40_U04_V5_LOCAL_AUTHORITY_MOTION_CADENCE_REPAIR_CANDIDATE_V1.mp4"
        CONTACT = OUT_DIR / "E40_U04_V5_LOCAL_AUTHORITY_MOTION_CONTACT_SHEET_V1.png"
        SPEC = OUT_DIR / "E40_U04_V5_LOCAL_AUTHORITY_MOTION_SPEC_V1.json"
        RECEIPT = ROOT / "workflow/tasks/E40_U04_V5_LOCAL_AUTHORITY_MOTION_BUILD_20260814.json"
    if args.semantic_repair_v6:
        MOTION_PROFILE = "V6_SEMANTIC_MASK_REPAIR"
        OUT_DIR = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u04_v6_local_semantic_mask_repair_v1"
        VIDEO = OUT_DIR / "E40_U04_V6_LOCAL_SEMANTIC_MASK_REPAIR_CANDIDATE_V1.mp4"
        CONTACT = OUT_DIR / "E40_U04_V6_LOCAL_SEMANTIC_MASK_REPAIR_CONTACT_SHEET_V1.png"
        SPEC = OUT_DIR / "E40_U04_V6_LOCAL_SEMANTIC_MASK_REPAIR_SPEC_V1.json"
        RECEIPT = ROOT / "workflow/tasks/E40_U04_V6_LOCAL_SEMANTIC_MASK_REPAIR_BUILD_20260814.json"
    if not AUTHORITY.exists() or sha(AUTHORITY) != AUTHORITY_SHA:
        raise SystemExit("FAIL_CLOSED_AUTHORITY_PIN_MISMATCH")
    if VIDEO.exists() or CONTACT.exists() or SPEC.exists() or RECEIPT.exists():
        raise SystemExit("V4 outputs already exist; repeat render forbidden")
    source = cv2.imread(str(AUTHORITY), cv2.IMREAD_COLOR)
    if source is None or source.shape[:2] != (1280, 720):
        raise SystemExit("FAIL_CLOSED_AUTHORITY_DECODE_OR_DIMENSIONS")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    height, width = source.shape[:2]
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    hand_alpha = soft_ellipse((height, width), (330, 1010), (420, 420), 18.0)
    if MOTION_PROFILE == "V6_SEMANTIC_MASK_REPAIR":
        hand_alpha *= np.clip((yy - 675.0) / 95.0, 0.0, 1.0)
    else:
        hand_alpha *= (yy > 610).astype(np.float32)
    hand_alpha = cv2.GaussianBlur(hand_alpha, (0, 0), 8.0)
    finger_alpha = soft_ellipse((height, width), (395, 1060), (145, 245), 14.0)
    gaze_alpha = soft_ellipse((height, width), (337, 346), (160, 66), 12.0)
    frost_mask = detect_frost(source)
    if int(np.count_nonzero(frost_mask)) < 12:
        raise SystemExit("FAIL_CLOSED_FROST_MASK_TOO_SMALL")
    frost_clean_mask = cv2.dilate(frost_mask, np.ones((11, 11), np.uint8), iterations=1)
    clean_frost = cv2.inpaint(source, frost_clean_mask, 5, cv2.INPAINT_TELEA)
    frost_alpha = cv2.GaussianBlur(frost_clean_mask, (0, 0), 2.2).astype(np.float32)[:, :, None] / 255.0

    background_hole = (np.clip(hand_alpha * 255.0, 0, 255)).astype(np.uint8)
    background = cv2.inpaint(source, cv2.dilate(background_hole, np.ones((7, 7), np.uint8)), 5, cv2.INPAINT_TELEA)

    fps, frame_count = 24, 96
    command = [
        "ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
        "-s", "720x1280", "-r", str(fps), "-i", "-", "-an", "-c:v", "libx264",
        "-preset", "slow", "-crf", "8", "-pix_fmt", "yuv420p", "-r", str(fps),
        "-g", "48", "-movflags", "+faststart", str(VIDEO),
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    samples: list[np.ndarray] = []
    for index in range(frame_count):
        if index == 0:
            frame = source.copy()
        else:
            t = index / fps
            frost_progress = smoothstep(min(t / 1.18, 1.0))
            recoil = smoothstep(max(0.0, min((t - 0.15) / 3.75, 1.0)))
            flex = smoothstep(max(0.0, min((t - 1.05) / 0.75, 1.0)))
            flex -= 0.42 * smoothstep(max(0.0, min((t - 2.05) / 1.4, 1.0)))
            gaze = smoothstep(max(0.0, min((t - 1.95) / 0.95, 1.0)))

            dx = 3.8 * recoil + 0.45 * math.sin(2 * math.pi * 0.83 * t + 0.2)
            dy = -2.6 * recoil + 0.38 * math.sin(2 * math.pi * 1.07 * t + 0.5)
            if MOTION_PROFILE in {"V5_CADENCE_REPAIR", "V6_SEMANTIC_MASK_REPAIR"}:
                opening = smoothstep(min(t / 0.18, 1.0))
                dx += 0.72 * opening + 1.35 * math.sin(2 * math.pi * 1.31 * t) + 0.62 * math.sin(2 * math.pi * 2.17 * t + 0.3)
                dy += 0.84 * math.sin(2 * math.pi * 1.43 * t + 0.5) + 0.38 * math.sin(2 * math.pi * 2.31 * t)
                flex += 0.25 * opening + 0.18 * math.sin(2 * math.pi * 1.73 * t)
            map_x = xx - hand_alpha * dx
            map_y = yy - hand_alpha * dy
            map_x -= finger_alpha * (1.8 * flex)
            map_y += finger_alpha * (3.2 * flex)
            moved = cv2.remap(source, map_x, map_y, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
            if MOTION_PROFILE == "V6_SEMANTIC_MASK_REPAIR":
                moved_clean = cv2.remap(clean_frost, map_x, map_y, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
                moved_frost_alpha = cv2.remap(frost_alpha[:, :, 0], map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)[:, :, None]
                moving_fade = moved_frost_alpha * frost_progress
                moved = moved.astype(np.float32) * (1.0 - moving_fade) + moved_clean.astype(np.float32) * moving_fade
                frame = source.astype(np.float32) * (1.0 - hand_alpha[:, :, None]) + moved * hand_alpha[:, :, None]
            else:
                frame = background.astype(np.float32) * (1.0 - hand_alpha[:, :, None]) + moved.astype(np.float32) * hand_alpha[:, :, None]

            # One-pixel-scale gaze shift within the existing eye geometry.
            eye_x = xx - gaze_alpha * (1.35 * gaze)
            eye_y = yy
            eyes = cv2.remap(source, eye_x, eye_y, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
            frame = frame * (1.0 - gaze_alpha[:, :, None]) + eyes.astype(np.float32) * gaze_alpha[:, :, None]

            # Fade only the admitted single frost trace; never grow or transfer it.
            if MOTION_PROFILE != "V6_SEMANTIC_MASK_REPAIR":
                fade = frost_alpha * frost_progress
                frame = frame * (1.0 - fade) + clean_frost.astype(np.float32) * fade

            # Non-periodic candle breaths keep the background alive without a camera move.
            glow = (
                np.exp(-(((xx - 661) / 75) ** 2 + ((yy - 480) / 125) ** 2))
                + 0.62 * np.exp(-(((xx - 560) / 105) ** 2 + ((yy - 720) / 160) ** 2))
            )
            flicker = 0.85 * math.sin(2 * math.pi * 1.19 * t) + 0.44 * math.sin(2 * math.pi * 1.87 * t + 0.7)
            if MOTION_PROFILE in {"V5_CADENCE_REPAIR", "V6_SEMANTIC_MASK_REPAIR"}:
                flicker += 0.72 * math.sin(2 * math.pi * 2.41 * t + 0.15)
            frame += glow[:, :, None] * flicker
            frame = np.clip(frame, 0, 255).astype(np.uint8)
        assert process.stdin is not None
        process.stdin.write(frame.tobytes())
        if index in {0, 12, 24, 36, 48, 72, 84, 95}:
            samples.append(frame)
    assert process.stdin is not None
    process.stdin.close()
    if process.wait() != 0:
        raise SystemExit("FAIL_CLOSED_FFMPEG_RENDER")

    thumbs = [cv2.resize(frame, (360, 640), interpolation=cv2.INTER_AREA) for frame in samples]
    sheet = np.zeros((1280, 1440, 3), np.uint8)
    for idx, thumb in enumerate(thumbs):
        row, col = divmod(idx, 4)
        sheet[row * 640:(row + 1) * 640, col * 360:(col + 1) * 360] = thumb
    cv2.imwrite(str(CONTACT), sheet)

    spec = {
        "schema": "qingshan.e40.u04.v4.local_authority_motion_spec.v1",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "authority": str(AUTHORITY.relative_to(ROOT)),
        "authority_sha256": AUTHORITY_SHA,
        "failed_provider_video_reused": False,
        "motion_profile": MOTION_PROFILE,
        "motion": {
            "frost": "single admitted trace recedes monotonically by 1.18s",
            "hand": "bounded connected hand/wrist recoil with localized restrained finger flex",
            "gaze": "one-pixel-scale eye-region shift after frost recession",
            "ambient": "two bounded non-periodic candle breaths",
            "camera": "fixed; no global transform",
        },
        "technical": {"width": 720, "height": 1280, "fps": 24, "frames": 96, "duration_seconds": 4.0, "audio_stream_count": 0},
        "provider_posts": 0,
        "transactions": 0,
        "credits": 0,
        "status": "RENDERED_PENDING_EXACT_FRAME_CADENCE_OCR_AND_HUMAN_QA",
    }
    atomic_json(SPEC, spec)
    atomic_json(
        RECEIPT,
        {
            "schema": "qingshan.e40.u04.v4.local_authority_motion_build.v1",
            "status": "PASS_RENDERED_QA_PENDING",
            "created_at": spec["created_at"],
            "video": str(VIDEO.relative_to(ROOT)),
            "video_sha256": sha(VIDEO),
            "contact_sheet": str(CONTACT.relative_to(ROOT)),
            "contact_sheet_sha256": sha(CONTACT),
            "spec": str(SPEC.relative_to(ROOT)),
            "spec_sha256": sha(SPEC),
            "failed_provider_video_reused": False,
            "provider_posts": 0,
            "transactions": 0,
            "credits": 0,
        },
    )
    print(json.dumps({"status": "PASS_RENDERED_QA_PENDING", "video": str(VIDEO), "sha256": sha(VIDEO)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
