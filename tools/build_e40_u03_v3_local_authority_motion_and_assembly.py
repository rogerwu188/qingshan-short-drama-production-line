#!/usr/bin/env python3
"""Build a zero-cost U03 motion plate and exact-dialogue assembly.

This is a new local visual derived from the admitted 720x1280 authority raster.
It does not prepend, replace, bridge, or otherwise reuse either failed provider
video. Frame zero is the authority image; later frames add bounded foreground
pressure motion and candle micro-flicker.
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
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
AUTHORITY = ROOT / "qa/e40_preproduction_20260808/u03_exact_frame_transport_repair_v1/E40_U03_EXACT_START_FRAME_720X1280_AUTHORITY_V1.png"
AUTHORITY_SHA = "dd89c40b86f69df4b66b93ed5250816532a0b4738bbbc6ded2f69d22cdd00781"
SOURCE_AUTHORITY = ROOT / "working_assets/e40_production_20260809/u03_exact_start_frame_v1/E40-U03-EXACT-START-FRAME-STATE-ISOLATED-CROP-V1_c5939a94-3ed8-4e10-99d5-243daa85fc18.png"
SOURCE_AUTHORITY_SHA = "5aff02d92874bc2da9856e51534fecd06716c36d0a4d5a719c6064794c519888"
AUDIO = ROOT / "working_assets/e40_production_20260814/u03_v1_kokoro_rights_cleared_exact_audio_v1/E40-DIA-003_zf_001_normalized48k.wav"
AUDIO_QA = ROOT / "qa/e40_production_20260814/u03_v1_kokoro_rights_cleared_exact_audio_v1/E40_U03_DIA003_EXACT_AUDIO_MACHINE_QA_V1.json"
RIGHTS = ROOT / "qa/e40_preproduction_20260814/u02_v12_kokoro_rights_clearance_v1/E40_U02_V12_KOKORO_COMMERCIAL_RIGHTS_EVIDENCE_V1.json"
OUT_DIR = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u03_v3_local_authority_motion_assembly_v1"
MOTION = OUT_DIR / "E40_U03_V3_LOCAL_AUTHORITY_MOTION_PLATE_V1.mp4"
SUBTITLE = OUT_DIR / "E40_DIA_003_SUBTITLE_LAYER_V1.png"
FINAL = OUT_DIR / "E40_U03_V3_LOCAL_AUTHORITY_MOTION_ASSEMBLY_NOT_FINAL.mp4"
CONTACT = OUT_DIR / "E40_U03_V3_LOCAL_AUTHORITY_MOTION_CONTACT_SHEET_V1.jpg"
PROJECT = OUT_DIR / "E40_U03_V3_AGENTCUT_EQUIVALENT_PROJECT_V1.json"
RECEIPT = ROOT / "workflow/tasks/E40_U03_V3_LOCAL_AUTHORITY_MOTION_ASSEMBLY_BUILD_20260814.json"
CANON_SCRIPT_SHA = "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b"
CANON_MANIFEST_SHA = "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1"
MOTION_PROFILE = "V3"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def smoothstep(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def build_foreground_mask(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    region = np.zeros(gray.shape, np.uint8)
    cv2.ellipse(region, (270, 780), (310, 665), 0, 0, 360, 255, -1)
    cv2.rectangle(region, (395, 500), (680, 1240), 255, -1)
    dark = cv2.inRange(gray, 0, 124)
    mask = cv2.bitwise_and(dark, region)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8), iterations=2)
    mask = cv2.dilate(mask, np.ones((5, 5), np.uint8), iterations=1)
    return mask


def motion_frame(source: np.ndarray, background: np.ndarray, mask: np.ndarray, frame_index: int, fps: int) -> np.ndarray:
    if frame_index == 0:
        return source.copy()
    t = frame_index / fps
    lead = smoothstep(min(t / 0.55, 1.0))
    sustain = smoothstep(max(0.0, min((t - 0.55) / 2.0, 1.0)))
    settle = smoothstep(max(0.0, min((t - 2.55) / 1.45, 1.0)))
    dx = 3.2 * lead + 1.8 * sustain - 0.7 * settle + 0.45 * math.sin(2 * math.pi * 0.72 * t)
    dy = -0.9 * lead + 0.35 * math.sin(2 * math.pi * 0.52 * t + 0.4)
    scale = 1.0 + 0.0013 * math.sin(2 * math.pi * 0.48 * t)
    if MOTION_PROFILE == "V4_CADENCE_REPAIR":
        after = smoothstep(max(0.0, min((t - 1.65) / 0.65, 1.0)))
        dx += after * (1.15 * math.sin(2 * math.pi * 0.91 * t + 0.25) + 0.65 * math.sin(2 * math.pi * 1.47 * t))
        dy += after * (0.55 * math.sin(2 * math.pi * 1.19 * t + 0.7))
        scale += after * 0.0017 * math.sin(2 * math.pi * 0.83 * t + 0.35)
    matrix = cv2.getRotationMatrix2D((320, 790), 0.0, scale)
    matrix[0, 2] += dx
    matrix[1, 2] += dy
    moved = cv2.warpAffine(source, matrix, (720, 1280), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
    moved_mask = cv2.warpAffine(mask, matrix, (720, 1280), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    alpha = cv2.GaussianBlur(moved_mask, (0, 0), 2.2).astype(np.float32)[:, :, None] / 255.0
    result = background.astype(np.float32) * (1.0 - alpha) + moved.astype(np.float32) * alpha

    # Two tiny, non-periodic candle breaths keep the curtain alive without
    # altering frame zero or introducing a flash transition.
    yy, xx = np.mgrid[0:1280, 0:720]
    glow = (
        np.exp(-(((xx - 410) / 105) ** 2 + ((yy - 842) / 150) ** 2))
        + 0.85 * np.exp(-(((xx - 628) / 92) ** 2 + ((yy - 910) / 138) ** 2))
    )
    flicker = 0.75 * math.sin(2 * math.pi * 1.13 * t) + 0.35 * math.sin(2 * math.pi * 1.71 * t + 0.8)
    if MOTION_PROFILE == "V4_CADENCE_REPAIR":
        flicker += 0.85 * smoothstep(max(0.0, min((t - 1.65) / 0.65, 1.0))) * math.sin(2 * math.pi * 2.07 * t + 0.2)
    result += glow[:, :, None] * flicker
    return np.clip(result, 0, 255).astype(np.uint8)


def render_motion() -> list[np.ndarray]:
    source = cv2.imread(str(AUTHORITY), cv2.IMREAD_COLOR)
    if source is None or source.shape[:2] != (1280, 720):
        raise SystemExit("FAIL_CLOSED_AUTHORITY_DECODE_OR_DIMENSIONS")
    mask = build_foreground_mask(source)
    background = cv2.inpaint(source, cv2.dilate(mask, np.ones((9, 9), np.uint8)), 5, cv2.INPAINT_TELEA)
    fps, frame_count = 24, 96
    command = [
        "ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
        "-s", "720x1280", "-r", str(fps), "-i", "-", "-an", "-c:v", "libx264",
        "-preset", "slow", "-crf", "8", "-pix_fmt", "yuv420p", "-r", str(fps),
        "-g", "48", "-movflags", "+faststart", str(MOTION),
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    samples = []
    for index in range(frame_count):
        frame = motion_frame(source, background, mask, index, fps)
        assert process.stdin is not None
        process.stdin.write(frame.tobytes())
        if index in {0, 12, 24, 48, 72, 95}:
            samples.append(frame)
    assert process.stdin is not None
    process.stdin.close()
    if process.wait() != 0:
        raise SystemExit("FAIL_CLOSED_FFMPEG_MOTION_RENDER")
    return samples


def build_subtitle() -> None:
    canvas = Image.new("RGBA", (720, 1280), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    font_path = "/System/Library/Fonts/STHeiti Medium.ttc"
    font = ImageFont.truetype(font_path, 42)
    text = "换，还是不换？"
    box = draw.textbbox((0, 0), text, font=font, stroke_width=3)
    width = box[2] - box[0]
    x, y = (720 - width) // 2, 1060
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0, 255))
    canvas.save(SUBTITLE)


def build_contact(samples: list[np.ndarray]) -> None:
    thumbs = [cv2.resize(frame, (180, 320), interpolation=cv2.INTER_AREA) for frame in samples]
    sheet = np.full((640, 540, 3), 18, np.uint8)
    for index, frame in enumerate(thumbs):
        row, col = divmod(index, 3)
        sheet[row * 320:(row + 1) * 320, col * 180:(col + 1) * 180] = frame
    cv2.imwrite(str(CONTACT), sheet, [cv2.IMWRITE_JPEG_QUALITY, 94])


def render_assembly() -> None:
    graph = (
        "[0:v][2:v]overlay=0:0:enable='between(t,0.22,2.02)'[vout];"
        "[1:a]adelay=220:all=1,alimiter=limit=0.89[aout]"
    )
    command = [
        "ffmpeg", "-y", "-v", "error", "-i", str(MOTION), "-i", str(AUDIO),
        "-loop", "1", "-framerate", "24", "-i", str(SUBTITLE),
        "-filter_complex", graph, "-map", "[vout]", "-map", "[aout]", "-t", "4.0",
        "-r", "24", "-c:v", "libx264", "-preset", "slow", "-crf", "10",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(FINAL),
    ]
    subprocess.run(command, check=True)


def main() -> int:
    global OUT_DIR, MOTION, SUBTITLE, FINAL, CONTACT, PROJECT, RECEIPT, MOTION_PROFILE
    parser = argparse.ArgumentParser()
    parser.add_argument("--cadence-repair-v4", action="store_true")
    args = parser.parse_args()
    if args.cadence_repair_v4:
        MOTION_PROFILE = "V4_CADENCE_REPAIR"
        OUT_DIR = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u03_v4_local_authority_motion_cadence_repair_v1"
        MOTION = OUT_DIR / "E40_U03_V4_LOCAL_AUTHORITY_MOTION_CADENCE_REPAIR_V1.mp4"
        SUBTITLE = OUT_DIR / "E40_DIA_003_SUBTITLE_LAYER_V1.png"
        FINAL = OUT_DIR / "E40_U03_V4_LOCAL_AUTHORITY_MOTION_ASSEMBLY_NOT_FINAL.mp4"
        CONTACT = OUT_DIR / "E40_U03_V4_LOCAL_AUTHORITY_MOTION_CONTACT_SHEET_V1.jpg"
        PROJECT = OUT_DIR / "E40_U03_V4_AGENTCUT_EQUIVALENT_PROJECT_V1.json"
        RECEIPT = ROOT / "workflow/tasks/E40_U03_V4_LOCAL_AUTHORITY_MOTION_CADENCE_REPAIR_BUILD_20260814.json"
    for path, expected in ((AUTHORITY, AUTHORITY_SHA), (SOURCE_AUTHORITY, SOURCE_AUTHORITY_SHA)):
        if not path.exists() or sha256(path) != expected:
            raise SystemExit(f"FAIL_CLOSED_AUTHORITY_PIN:{path}")
    qa = json.loads(AUDIO_QA.read_text(encoding="utf-8"))
    rights = json.loads(RIGHTS.read_text(encoding="utf-8"))
    if qa.get("status") != "PASS_EXACT_AUDIO_ADMITTED" or qa.get("asr_similarity") != 1.0:
        raise SystemExit("FAIL_CLOSED_AUDIO_NOT_ADMITTED")
    if sha256(AUDIO) != qa.get("output_sha256") or rights.get("releaseBlocked") is not False:
        raise SystemExit("FAIL_CLOSED_AUDIO_BINDING_OR_RIGHTS")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    samples = render_motion()
    build_subtitle()
    build_contact(samples)
    render_assembly()
    project = {
        "version": "1.0",
        "metadata": {
            "episode": "E40", "unit_id": "U03", "status": "LOCAL_AUTHORITY_MOTION_ASSEMBLY_QA_PENDING",
            "releaseAllowed": False, "platformUploadAllowed": False, "finalAssembly": False,
            "canonical_script_sha256": CANON_SCRIPT_SHA, "canonical_manifest_sha256": CANON_MANIFEST_SHA,
            "failed_provider_assets_reused": False, "provider_post_count": 0, "credits": 0,
        },
        "output": {"path": str(FINAL), "width": 720, "height": 1280, "fps": 24},
        "timeline": {
            "video": {"source": str(MOTION), "start": 0.0, "duration": 4.0, "authority_sha256": AUTHORITY_SHA},
            "audio": {"source": str(AUDIO), "start": 0.22, "duration": 1.8, "dialogue_id": "E40-DIA-003"},
            "subtitle": {"bitmap": str(SUBTITLE), "start": 0.22, "duration": 1.8, "text": "换，还是不换？"},
        },
    }
    atomic_json(PROJECT, project)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_name,codec_type,width,height,sample_rate,channels", "-of", "json", str(FINAL)],
        capture_output=True, text=True, check=True,
    )
    atomic_json(RECEIPT, {
        "schema": "qingshan.e40.u03.v3.local_authority_motion_assembly_build.v1",
        "status": "PASS_RENDERED_UNIT_QA_PENDING",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "decision": "ZERO_COST_LOCAL_AUTHORITY_MOTION_SELECTED_OVER_BLIND_PROVIDER_RETRY",
        "motion_profile": MOTION_PROFILE,
        "motion_plate": str(MOTION.relative_to(ROOT)), "motion_plate_sha256": sha256(MOTION),
        "assembly": str(FINAL.relative_to(ROOT)), "assembly_sha256": sha256(FINAL),
        "subtitle_bitmap": str(SUBTITLE.relative_to(ROOT)), "subtitle_bitmap_sha256": sha256(SUBTITLE),
        "contact_sheet": str(CONTACT.relative_to(ROOT)), "contact_sheet_sha256": sha256(CONTACT),
        "project": str(PROJECT.relative_to(ROOT)), "project_sha256": sha256(PROJECT),
        "authority_raster": str(AUTHORITY.relative_to(ROOT)), "authority_raster_sha256": AUTHORITY_SHA,
        "source_authority_sha256": SOURCE_AUTHORITY_SHA,
        "failed_provider_assets_reused": False,
        "audio": str(AUDIO.relative_to(ROOT)), "audio_sha256": sha256(AUDIO),
        "probe": json.loads(probe.stdout), "provider_post_count": 0, "credits": 0,
    })
    print(json.dumps({"status": "PASS_RENDERED_UNIT_QA_PENDING", "assembly": str(FINAL), "sha256": sha256(FINAL)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
