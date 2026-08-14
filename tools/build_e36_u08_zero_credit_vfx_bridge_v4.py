#!/usr/bin/env python3
"""Add source-native moving paper fragments to the reversible U08 V3 probe."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

import build_e36_u08_zero_credit_vfx_bridge_v3 as v3


ROOT = v3.ROOT
U05 = ROOT / "working_assets/e36_v2_videos_20260728/E36-CW-U05-VIDEO-V1_592af09e.mp4"
OUT_DIR = ROOT / "working_assets/e36_autonomous_recovery_20260731/u08_zero_credit_vfx_bridge_v4"
OUT = OUT_DIR / "E36_U08_ZERO_CREDIT_SOURCE_NATIVE_PAPER_IMPACT_BRIDGE_V4.mp4"
QA_DIR = v3.QA_DIR
CONTACT = QA_DIR / "E36_U08_V4_8FPS_DIRECT_TEMPORAL_CONTACT.jpg"
MANIFEST = QA_DIR / "E36_U08_V4_SOURCE_NATIVE_PAPER_IMPACT_MANIFEST.json"
SCHEMA = "qingshan.e36.u08_source_native_paper_impact_bridge.v4"
SOURCE_CL2X = "CL2X-923"
METHOD = "SOURCE_NATIVE_MOVING_ROTOSCOPE_PLUS_SOURCE_NATIVE_MOVING_PAPER_FRAGMENT_COMPOSITE; NO_STILL_TO_MOTION; NO_GENERATIVE_PIXELS"
SECOND_AUDIO = v3.U07
U05_ROLE = "moving_white_paper_fragment_layer_present_from_first_frame"


def fragment_mask(frame: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    raw = ((hsv[:, :, 1] < 88) & (hsv[:, :, 2] > 158)).astype(np.uint8) * 255
    raw[:70, :] = 0
    raw[1010:, :] = 0
    count, labels, stats, _ = cv2.connectedComponentsWithStats(raw, connectivity=8)
    kept = np.zeros_like(raw)
    for label in range(1, count):
        x, y, width, height, area = stats[label]
        if 7 <= area <= 1700 and width <= 120 and height <= 150:
            kept[labels == label] = 255
    kept = cv2.dilate(kept, np.ones((3, 3), np.uint8), iterations=1)
    return cv2.GaussianBlur(kept, (0, 0), sigmaX=1.1, sigmaY=1.1)


def render_frames() -> list[np.ndarray]:
    output = v3.render_frames()
    paper = v3.read_all(U05)
    for index in range(30):
        source = paper[min(index, len(paper) - 1)]
        mask = fragment_mask(source).astype(np.float32)[:, :, None] / 255.0
        alpha = np.clip(mask * 0.86, 0.0, 0.86)
        output[index] = np.clip(
            source.astype(np.float32) * alpha
            + output[index].astype(np.float32) * (1.0 - alpha),
            0,
            255,
        ).astype(np.uint8)
    return output


def build_contact(frames: list[np.ndarray]) -> None:
    samples = np.linspace(0, len(frames) - 1, 40).astype(int)
    cells = []
    for index in samples:
        cell = cv2.resize(frames[index], (144, 256), interpolation=cv2.INTER_AREA)
        cv2.putText(cell, f"{index / v3.FPS:.2f}s", (5, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.46, (255, 255, 255), 1, cv2.LINE_AA)
        cells.append(cell)
    rows = [np.hstack(cells[row * 8:(row + 1) * 8]) for row in range(5)]
    if not cv2.imwrite(str(CONTACT), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 94]):
        raise RuntimeError("Could not write contact sheet")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    QA_DIR.mkdir(parents=True, exist_ok=True)
    frames = render_frames()
    build_contact(frames)
    with tempfile.TemporaryDirectory(prefix="e36_u08_v4_", dir=OUT_DIR) as temp_name:
        temp = Path(temp_name)
        silent = temp / "silent.mp4"
        muxed = temp / "muxed.mp4"
        process = subprocess.Popen([
            str(v3.FFMPEG), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{v3.WIDTH}x{v3.HEIGHT}",
            "-r", str(v3.FPS), "-i", "-", "-an", "-c:v", "libx264", "-preset", "medium",
            "-crf", "18", "-pix_fmt", "yuv420p", str(silent),
        ], stdin=subprocess.PIPE)
        assert process.stdin is not None
        for frame in frames:
            process.stdin.write(frame.tobytes())
        process.stdin.close()
        if process.wait() != 0:
            raise RuntimeError("Video encode failed")
        audio_filter = (
            "[1:a]atrim=0:1.25,asetpts=PTS-STARTPTS[a0];"
            "[2:a]atrim=1.25:5.0,asetpts=PTS-STARTPTS[a1];"
            "[a0][a1]concat=n=2:v=0:a=1[a]"
        )
        subprocess.run([
            str(v3.FFMPEG), "-hide_banner", "-loglevel", "error", "-y", "-i", str(silent),
            "-i", str(v3.U04), "-i", str(SECOND_AUDIO), "-filter_complex", audio_filter,
            "-map", "0:v:0", "-map", "[a]", "-t", "5.0", "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", str(muxed),
        ], check=True)
        os.replace(muxed, OUT)

    manifest = {
        "schema": SCHEMA,
        "episode": "E36",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_cl2x": SOURCE_CL2X,
        "canonical_script_sha256": "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6",
        "candidate": str(OUT.relative_to(ROOT)),
        "candidate_sha256": v3.sha256(OUT),
        "sources": [
            {"path": str(v3.U04.relative_to(ROOT)), "sha256": v3.sha256(v3.U04), "role": "moving_executioner_and_downward_blade_layer"},
            {"path": str(v3.U07.relative_to(ROOT)), "sha256": v3.sha256(v3.U07), "role": "moving_empty_paper_substitute_and_withdrawal_base"},
            {"path": str(U05.relative_to(ROOT)), "sha256": v3.sha256(U05), "role": U05_ROLE},
        ],
        "method": METHOD,
        "contact_sheet": str(CONTACT.relative_to(ROOT)),
        "contact_sheet_sha256": v3.sha256(CONTACT),
        "credits": {"pay": 0, "refund": 0, "net": 0},
        "status": "REVERSIBLE_PROBE_REQUIRES_DIRECT_VISUAL_QA",
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"candidate": str(OUT.relative_to(ROOT)), "sha256": v3.sha256(OUT), "contact": str(CONTACT.relative_to(ROOT)), "manifest": str(MANIFEST.relative_to(ROOT))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
