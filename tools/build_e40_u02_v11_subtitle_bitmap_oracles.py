#!/usr/bin/env python3
"""Render exact U02 subtitle style oracles without authoring final timings."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
VIDEO = ROOT / (
    "workflow/claude_writer_agent/production/"
    "e40_claude_writer_v3_140d4b7b_20260808/"
    "u02_v11_agentcut_picture_audio_slot_preassembly_v1/"
    "E40_U02_V11_AGENTCUT_PICTURE_PREASSEMBLY_V1.mp4"
)
VIDEO_SHA = "dc14d06e29b475978d3dea7240ed0463c450d2c01362754c0f330ec98e604847"
FONT = Path("/System/Library/Fonts/STHeiti Medium.ttc")
OUT = ROOT / (
    "workflow/claude_writer_agent/production/"
    "e40_claude_writer_v3_140d4b7b_20260808/"
    "u02_v11_subtitle_bitmap_oracles_v1"
)
LINES = [
    ("E40-DIA-001", "阿栓，在本宫手上。", 1.0),
    ("E40-DIA-002", "拿他，换景朝一个接头人。", 2.5),
]
WIDTH = 720
HEIGHT = 1280
FONT_SIZE = 42
STROKE = 3
BOTTOM_MARGIN = 170


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    if not VIDEO.is_file() or sha256(VIDEO) != VIDEO_SHA:
        raise SystemExit("V11 AgentCut picture source missing or SHA mismatch")
    if not FONT.is_file():
        raise SystemExit("canonical subtitle font missing")
    OUT.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype(str(FONT), FONT_SIZE)
    manifest_lines = []
    preview_images = []

    for line_id, text, preview_time in LINES:
        layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        bbox = draw.textbbox((0, 0), text, font=font, stroke_width=STROKE)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        x = round((WIDTH - text_width) / 2 - bbox[0])
        y = round(HEIGHT - BOTTOM_MARGIN - text_height - bbox[1])
        draw.text(
            (x, y),
            text,
            font=font,
            fill=(255, 255, 255, 255),
            stroke_width=STROKE,
            stroke_fill=(0, 0, 0, 255),
        )
        layer_path = OUT / f"{line_id}_SUBTITLE_LAYER_V1.png"
        layer.save(layer_path)

        frame_path = OUT / f"{line_id}_STYLE_PREVIEW_SOURCE_FRAME.png"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-ss",
                str(preview_time),
                "-i",
                str(VIDEO),
                "-frames:v",
                "1",
                str(frame_path),
            ],
            check=True,
        )
        frame = Image.open(frame_path).convert("RGBA")
        preview = Image.alpha_composite(frame, layer)
        preview_path = OUT / f"{line_id}_SUBTITLE_STYLE_PREVIEW_V1.png"
        preview.convert("RGB").save(preview_path, quality=95)
        preview_images.append(preview.convert("RGB").resize((360, 640), Image.Resampling.LANCZOS))

        manifest_lines.append(
            {
                "line_id": line_id,
                "exact_text": text,
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "layer_path": str(layer_path.relative_to(ROOT)),
                "layer_sha256": sha256(layer_path),
                "style_preview_path": str(preview_path.relative_to(ROOT)),
                "style_preview_sha256": sha256(preview_path),
                "preview_time_seconds_non_authoritative": preview_time,
                "bbox": {"x": x, "y": y, "width": text_width, "height": text_height},
            }
        )

    contact = Image.new("RGB", (720, 640), "black")
    contact.paste(preview_images[0], (0, 0))
    contact.paste(preview_images[1], (360, 0))
    contact_path = OUT / "E40_U02_V11_SUBTITLE_STYLE_CONTACT_SHEET_V1.png"
    contact.save(contact_path, quality=95)

    manifest = {
        "schema": "qingshan.e40.u02.v11.subtitle_bitmap_oracles.v1",
        "episode": "E40",
        "unit_id": "U02",
        "status": "PASS_STYLE_ORACLES_COMPILED_TIMING_NOT_AUTHORIZED",
        "source_video": str(VIDEO.relative_to(ROOT)),
        "source_video_sha256": VIDEO_SHA,
        "canvas": {"width": WIDTH, "height": HEIGHT, "fps": 24},
        "style": {
            "font": str(FONT),
            "size": FONT_SIZE,
            "fill": "#FFFFFF",
            "outline": STROKE,
            "outline_color": "#000000",
            "alignment": "bottom-center",
            "bottom_margin": BOTTOM_MARGIN,
            "background_box": False,
        },
        "lines": manifest_lines,
        "contact_sheet": str(contact_path.relative_to(ROOT)),
        "contact_sheet_sha256": sha256(contact_path),
        "timing_policy": "NO_FINAL_START_OR_DURATION_UNTIL_ACCEPTED_AUDIO_MEASURED_BOUNDARIES_AND_VERIFIED_ASR",
        "release_allowed": False,
        "provider_calls": 0,
        "transactions": 0,
        "credits": 0,
    }
    manifest_path = OUT / "E40_U02_V11_SUBTITLE_BITMAP_ORACLE_MANIFEST_V1.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "manifest": str(manifest_path),
                "manifest_sha256": sha256(manifest_path),
                "contact_sheet": str(contact_path),
                "contact_sheet_sha256": sha256(contact_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
