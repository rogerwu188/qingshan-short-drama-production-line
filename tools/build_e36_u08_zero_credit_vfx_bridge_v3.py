#!/usr/bin/env python3
"""Build a reversible U08 motion probe from source-native moving footage."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
FFMPEG = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffmpeg"
U04 = ROOT / "working_assets/e36_recovery_10000_20260730/u04_video_repair/E36_E36-CW-U04-VIDEO-R2-CHANGED-INPUT-REPAIR_1b104216-0f34-4b6b-88b8-bb5ca6364d22.mp4"
U07 = ROOT / "working_assets/e36_v2_stills_20260728/local_fight_fallbacks/E36-CW-U07-LOCAL-ACTION-DETAIL-V1.mp4"
OUT_DIR = ROOT / "working_assets/e36_autonomous_recovery_20260731/u08_zero_credit_vfx_bridge_v3"
OUT = OUT_DIR / "E36_U08_ZERO_CREDIT_SOURCE_NATIVE_ROTOSCOPE_BRIDGE_V3.mp4"
QA_DIR = ROOT / "qa/e36_agentcut_20260730/u08_zero_credit_rotoscope_probe_20260801"
CONTACT = QA_DIR / "E36_U08_V3_5FPS_DIRECT_TEMPORAL_CONTACT.jpg"
MANIFEST = QA_DIR / "E36_U08_V3_SOURCE_NATIVE_ROTOSCOPE_MANIFEST.json"
FPS = 24.0
FRAME_COUNT = 120
WIDTH, HEIGHT = 720, 1280


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_all(path: Path) -> list[np.ndarray]:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open {path}")
    frames: list[np.ndarray] = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frames.append(cv2.resize(frame, (WIDTH, HEIGHT), interpolation=cv2.INTER_AREA))
    cap.release()
    if not frames:
        raise RuntimeError(f"No decoded frames in {path}")
    return frames


def color_match(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    src = source.astype(np.float32)
    dst = target.astype(np.float32)
    src_mean = src.reshape(-1, 3).mean(axis=0)
    dst_mean = dst.reshape(-1, 3).mean(axis=0)
    gain = np.clip(dst_mean / np.maximum(src_mean, 1.0), 0.72, 1.35)
    return np.clip(src * gain, 0, 255).astype(np.uint8)


def overlay_mask() -> np.ndarray:
    mask = np.zeros((HEIGHT, WIDTH), np.uint8)
    # Executioner's upper body and arms; excludes the prone captive below.
    cv2.fillPoly(mask, [np.array([(0, 0), (475, 0), (520, 230), (475, 500), (360, 590), (230, 560), (0, 500)], np.int32)], 255)
    # Preserve the source-native curved blade down to its moving contact direction.
    cv2.fillPoly(mask, [np.array([(310, 120), (500, 90), (500, 360), (440, 760), (300, 790), (340, 430)], np.int32)], 255)
    return cv2.GaussianBlur(mask, (0, 0), sigmaX=13, sigmaY=13)


def render_frames() -> list[np.ndarray]:
    u04 = read_all(U04)
    u07 = read_all(U07)
    base_mask = overlay_mask()
    output: list[np.ndarray] = []
    for index in range(FRAME_COUNT):
        if index < 30:
            base_index = min(index, len(u07) - 1)
            source_index = min(index, len(u04) - 1)
            base = u07[base_index].copy()
            source = color_match(u04[source_index], base)
            progress = index / 29.0
            offset_y = int(round(-42 + 126 * (progress * progress * (3 - 2 * progress))))
            matrix = np.float32([[1, 0, 0], [0, 1, offset_y]])
            moved = cv2.warpAffine(source, matrix, (WIDTH, HEIGHT), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
            moved_mask = cv2.warpAffine(base_mask, matrix, (WIDTH, HEIGHT), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
            alpha = moved_mask.astype(np.float32)[:, :, None] / 255.0
            frame = np.clip(moved.astype(np.float32) * alpha + base.astype(np.float32) * (1.0 - alpha), 0, 255).astype(np.uint8)
        elif index < 38:
            # Source-native impact transition: dissolve into U07's fastest paper-substitute motion.
            left = output[-1]
            target_index = min(62 + (index - 30) * 2, len(u07) - 1)
            right = u07[target_index]
            mix = (index - 29) / 9.0
            frame = cv2.addWeighted(left, 1.0 - mix, right, mix, 0)
            frame = cv2.GaussianBlur(frame, (0, 0), sigmaX=max(0.0, 2.8 * (1.0 - abs(mix - 0.5) * 2.0)))
        else:
            source_index = min(62 + (index - 38), len(u07) - 1)
            frame = u07[source_index].copy()
        output.append(frame)
    return output


def build_contact(frames: list[np.ndarray]) -> None:
    samples = np.linspace(0, len(frames) - 1, 25).astype(int)
    cells = []
    for index in samples:
        cell = cv2.resize(frames[index], (144, 256), interpolation=cv2.INTER_AREA)
        cv2.putText(cell, f"{index / FPS:.2f}s", (5, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.46, (255, 255, 255), 1, cv2.LINE_AA)
        cells.append(cell)
    rows = [np.hstack(cells[row * 5:(row + 1) * 5]) for row in range(5)]
    sheet = np.vstack(rows)
    if not cv2.imwrite(str(CONTACT), sheet, [cv2.IMWRITE_JPEG_QUALITY, 93]):
        raise RuntimeError("Could not write contact sheet")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    QA_DIR.mkdir(parents=True, exist_ok=True)
    frames = render_frames()
    build_contact(frames)
    with tempfile.TemporaryDirectory(prefix="e36_u08_v3_", dir=OUT_DIR) as temp_name:
        temp = Path(temp_name)
        silent = temp / "silent.mp4"
        muxed = temp / "muxed.mp4"
        command = [
            str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{WIDTH}x{HEIGHT}",
            "-r", str(FPS), "-i", "-", "-an", "-c:v", "libx264", "-preset", "medium",
            "-crf", "18", "-pix_fmt", "yuv420p", str(silent),
        ]
        process = subprocess.Popen(command, stdin=subprocess.PIPE)
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
            str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", "-i", str(silent),
            "-i", str(U04), "-i", str(U07), "-filter_complex", audio_filter,
            "-map", "0:v:0", "-map", "[a]", "-t", "5.0", "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", str(muxed),
        ], check=True)
        os.replace(muxed, OUT)

    manifest = {
        "schema": "qingshan.e36.u08_source_native_rotoscope_bridge.v3",
        "episode": "E36",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_cl2x": "CL2X-921",
        "canonical_script_sha256": "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6",
        "candidate": str(OUT.relative_to(ROOT)),
        "candidate_sha256": sha256(OUT),
        "sources": [
            {"path": str(U04.relative_to(ROOT)), "sha256": sha256(U04), "role": "moving_executioner_and_downward_blade_layer"},
            {"path": str(U07.relative_to(ROOT)), "sha256": sha256(U07), "role": "moving_empty_paper_substitute_and_withdrawal_base"},
        ],
        "method": "SOURCE_NATIVE_MOVING_LAYER_ROTOSCOPE_PLUS_SOURCE_NATIVE_IMPACT_DISSOLVE; NO_STILL_TO_MOTION; NO_GENERATIVE_PIXELS",
        "contact_sheet": str(CONTACT.relative_to(ROOT)),
        "contact_sheet_sha256": sha256(CONTACT),
        "credits": {"pay": 0, "refund": 0, "net": 0},
        "status": "REVERSIBLE_PROBE_REQUIRES_DIRECT_VISUAL_QA",
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"candidate": str(OUT.relative_to(ROOT)), "sha256": sha256(OUT), "contact": str(CONTACT.relative_to(ROOT)), "manifest": str(MANIFEST.relative_to(ROOT))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
