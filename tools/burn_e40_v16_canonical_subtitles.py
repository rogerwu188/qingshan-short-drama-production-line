#!/usr/bin/env python3
"""Burn the V16 canonical 20-cue SRT without requiring ffmpeg/libass."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
VIDEO = ROOT / "working_assets/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V16_R04_DIALOGUE_ORDER_FIX.mp4"
SRT = ROOT / "working_assets/e40_remake_20260822/final_subtitle_v16/E40_V16_CANONICAL_20_CUE_ZH_CN.srt"
OVERLAYS = ROOT / "working_assets/e40_remake_20260822/final_subtitle_v16/overlays"
OUT = ROOT / "working_assets/e40_remake_20260822/assembly_candidate_v1/E40_RELEASE_CANDIDATE_V16_CAPTIONED.mp4"
FONT = Path("/System/Library/Fonts/STHeiti Medium.ttc")


def seconds(value: str) -> float:
    hours, minutes, rest = value.split(":")
    secs, millis = rest.split(",")
    return int(hours) * 3600 + int(minutes) * 60 + int(secs) + int(millis) / 1000


def cues() -> list[tuple[float, float, str]]:
    blocks = re.split(r"\n\s*\n", SRT.read_text(encoding="utf-8").strip())
    result = []
    for block in blocks:
        lines = block.splitlines()
        start, end = lines[1].split(" --> ")
        result.append((seconds(start), seconds(end), "\n".join(lines[2:])))
    return result


def wrap(text: str, width: int = 16) -> str:
    if "\n" in text or len(text) <= width:
        return text
    split = min(width, max(1, len(text) // 2 + 1))
    return text[:split] + "\n" + text[split:]


def main() -> int:
    OVERLAYS.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype(str(FONT), 42)
    command = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(VIDEO)]
    filters = []
    previous = "0:v"
    for index, (start, end, text) in enumerate(cues(), start=1):
        image = Image.new("RGBA", (720, 1280), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        caption = wrap(text)
        box = draw.multiline_textbbox((0, 0), caption, font=font, stroke_width=3, spacing=8, align="center")
        x = (720 - (box[2] - box[0])) / 2
        y = 1060 - (box[3] - box[1]) / 2
        draw.multiline_text((x, y), caption, font=font, fill="white", stroke_width=3, stroke_fill=(12, 12, 12, 255), spacing=8, align="center")
        overlay = OVERLAYS / f"cue_{index:02d}.png"
        image.save(overlay)
        command += ["-loop", "1", "-i", str(overlay)]
        current = f"v{index}"
        filters.append(f"[{previous}][{index}:v]overlay=0:0:enable='between(t,{start:.3f},{end:.3f})'[{current}]")
        previous = current
    command += [
        "-filter_complex", ";".join(filters), "-map", f"[{previous}]", "-map", "0:a:0",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "copy", "-shortest", "-movflags", "+faststart", str(OUT),
    ]
    subprocess.run(command, check=True)
    print(OUT.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
