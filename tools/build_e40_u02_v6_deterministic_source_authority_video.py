#!/usr/bin/env python3
"""Build a silent, exact-frame U02 V6 candidate from the admitted V3 authority only."""
from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
AUTHORITY = ROOT / "working_assets/e40_production_20260814/u02_v3_low_hem_authority_exact_start_frame_retry1/E40_E40-U02-EXACT-START-FRAME-V3-LOW-HEM-AUTHORITY-RETRY1_52180a09-d3ef-47d0-afc1-44d30147c8a2.png"
OUT_DIR = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u02_v6_deterministic_source_authority_v1"
VIDEO = OUT_DIR / "E40_U02_V6_DETERMINISTIC_SOURCE_AUTHORITY_CANDIDATE_V1.mp4"
SPEC = OUT_DIR / "E40_U02_V6_DETERMINISTIC_SOURCE_AUTHORITY_SPEC_V1.json"
CONTACT = ROOT / "qa/e40_production_20260814/u02_v6_deterministic_source_authority_v1/E40_U02_V6_CONTACT_SHEET_V1.png"
FPS = 24
FRAMES = 96
WIDTH = 720
HEIGHT = 1280


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def atomic_json(path: Path, payload: object) -> None:
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


def ease(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x * x * (3.0 - 2.0 * x)


def frame_at(base: np.ndarray, index: int, xx: np.ndarray, yy: np.ndarray) -> np.ndarray:
    if index == 0:
        return base.copy()
    t = index / FPS

    # Beat 1 (0-0.5s): the already half-closed fan compresses a little more.
    close = ease(t / 0.5)
    fan_weight = np.exp(-(((xx - 518.0) / 77.0) ** 2 + ((yy - 770.0) / 210.0) ** 2) * 2.1)
    # Inverse mapping stretches the sampled x distance, visually narrowing the fan bundle.
    compress = 0.052 * close
    map_x = xx + fan_weight * (xx - 493.0) * compress
    map_y = yy.copy()

    # Beat 2 (0.5-1.8s): the same wrist/fan/sleeve settle down and slightly inward.
    settle = ease((t - 0.5) / 1.3)
    hand_weight = np.exp(-(((xx - 553.0) / 190.0) ** 2 + ((yy - 1015.0) / 330.0) ** 2) * 1.35)
    map_x -= hand_weight * (-7.0 * settle)
    map_y -= hand_weight * (13.0 * settle)

    # Beat 3 (1.8-3.0s): a small irreversible inward wrist turn.
    turn = ease((t - 1.8) / 1.2)
    angle = math.radians(-1.6 * turn)
    px, py = 520.0, 950.0
    dx, dy = xx - px, yy - py
    src_x = math.cos(angle) * dx + math.sin(angle) * dy + px
    src_y = -math.sin(angle) * dx + math.cos(angle) * dy + py
    turn_weight = np.exp(-(((xx - 525.0) / 145.0) ** 2 + ((yy - 910.0) / 300.0) ** 2) * 1.6)
    map_x = map_x * (1.0 - turn_weight) + src_x * turn_weight
    map_y = map_y * (1.0 - turn_weight) + src_y * turn_weight

    # Beat 4 (3.0-4.0s): one non-looping, sub-pixel curtain breath above the fixed hem.
    breath = ease((t - 3.0) / 0.55) - 0.55 * ease((t - 3.55) / 0.45)
    curtain_weight = np.exp(-(((xx - 320.0) / 250.0) ** 2 + ((yy - 650.0) / 420.0) ** 2) * 1.1)
    curtain_weight *= np.clip((1160.0 - yy) / 260.0, 0.0, 1.0)
    map_x += curtain_weight * (2.2 * breath) * np.sin((yy / 105.0) + 0.7)

    return cv2.remap(
        base,
        map_x.astype(np.float32),
        map_y.astype(np.float32),
        interpolation=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_REFLECT_101,
    )


def main() -> None:
    if sha(AUTHORITY) != "2f8841136030bd4f691ddb9faa77badfe52e7caf207f6f6975030703894fe725":
        raise SystemExit("authority SHA drift")
    source = cv2.imread(str(AUTHORITY), cv2.IMREAD_COLOR)
    if source is None:
        raise SystemExit("authority decode failed")
    base = cv2.resize(source, (WIDTH, HEIGHT), interpolation=cv2.INTER_LANCZOS4)
    yy, xx = np.mgrid[0:HEIGHT, 0:WIDTH].astype(np.float32)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CONTACT.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS), "-i", "-",
        "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "0", "-pix_fmt", "yuv444p",
        "-movflags", "+faststart", str(VIDEO),
    ]
    proc = subprocess.Popen(command, stdin=subprocess.PIPE)
    samples: list[np.ndarray] = []
    sample_indices = {0, 11, 23, 35, 47, 59, 71, 95}
    assert proc.stdin is not None
    for index in range(FRAMES):
        frame = frame_at(base, index, xx, yy)
        proc.stdin.write(frame.tobytes())
        if index in sample_indices:
            samples.append(frame.copy())
    proc.stdin.close()
    code = proc.wait()
    if code != 0:
        raise SystemExit(f"ffmpeg failed: {code}")

    thumbs = [cv2.resize(frame, (180, 320), interpolation=cv2.INTER_AREA) for frame in samples]
    sheet = np.zeros((640, 720, 3), dtype=np.uint8)
    for i, thumb in enumerate(thumbs):
        row, col = divmod(i, 4)
        sheet[row * 320:(row + 1) * 320, col * 180:(col + 1) * 180] = thumb
        cv2.putText(sheet, f"f{sorted(sample_indices)[i]}", (col * 180 + 7, row * 320 + 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
    if not cv2.imwrite(str(CONTACT), sheet):
        raise SystemExit("contact sheet write failed")

    spec = {
        "schema": "qingshan.e40.u02.v6.deterministic_source_authority_spec.v1",
        "episode": "E40", "unit_id": "U02", "variant": "V6", "created_at": "2026-08-14T07:02:00Z",
        "canonical_script_sha256": "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b",
        "canonical_manifest_sha256": "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1",
        "source_authority": {"path": rel(AUTHORITY), "sha256": sha(AUTHORITY)},
        "failed_v5_pixels_used": False,
        "method": "SMOOTH_LOCAL_INVERSE_WARP_OF_SINGLE_ADMITTED_SOURCE_AUTHORITY",
        "beats": [
            {"window": "0.00-0.50", "action": "fan bundle narrows by 5.2 percent"},
            {"window": "0.50-1.80", "action": "same wrist/fan/sleeve settles 13px down and 7px inward"},
            {"window": "1.80-3.00", "action": "same wrist turns inward 1.6 degrees"},
            {"window": "3.00-4.00", "action": "single non-looping curtain breath, hem weight pinned to zero"},
        ],
        "output_contract": {"width": WIDTH, "height": HEIGHT, "fps": FPS, "frames": FRAMES, "duration_seconds": 4.0, "audio_streams": 0, "codec": "H.264", "pixel_format": "yuv444p", "lossless_crf": 0},
        "output": {"path": rel(VIDEO), "sha256": sha(VIDEO)},
        "contact_sheet": {"path": rel(CONTACT), "sha256": sha(CONTACT)},
        "provider_calls": 0, "transactions": 0, "credits": 0,
        "status": "CANDIDATE_RENDERED_REQUIRES_EXACT_FRAME_CADENCE_OCR_AND_HUMAN_QA",
    }
    atomic_json(SPEC, spec)
    print(json.dumps({"status": "PASS_RENDERED", "video": rel(VIDEO), "video_sha256": sha(VIDEO), "spec_sha256": sha(SPEC), "contact_sheet_sha256": sha(CONTACT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
