#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


BASE = Path("/Users/rogerwu/qingshan_short_drama")
FFMPEG = BASE / ".video_deps/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1"
RAW = Path(os.environ.get(
    "E06_RAW",
    BASE / "exports/e06/platform_export_20260704/qingshan_E06_platform_audio_raw_20260704.mp4",
))
LOGO = BASE / "libraries/brand/nalu_motion_cat_logo_v1.png"
OUT_DIR = Path(os.environ.get("E06_OUT_DIR", BASE / "exports/e06/final_package_20260704"))
QA_DIR = Path(os.environ.get("E06_QA_DIR", BASE / "qa/e06_final_20260704/final_package"))

TITLE_OVERLAY = OUT_DIR / "qingshan_E06_title_overlay_20260704.png"
TAIL_OVERLAY = OUT_DIR / "qingshan_E06_nalu_tail_overlay_20260704.png"
FINAL = Path(os.environ.get(
    "E06_FINAL",
    OUT_DIR / "qingshan_E06_final_platform_audio_titled_nalu_20260704.mp4",
))

FONT_REGULAR = "/System/Library/Fonts/STHeiti Light.ttc"
FONT_BOLD = "/System/Library/Fonts/STHeiti Medium.ttc"


def run(args: list[str], capture: bool = False) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(map(str, args)))
    return subprocess.run(
        args,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )


def probe_text(path: Path) -> str:
    proc = subprocess.run(
        [str(FFMPEG), "-hide_banner", "-i", str(path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return proc.stdout or ""


def duration_seconds(path: Path) -> float:
    match = re.search(r"Duration: (\d+):(\d+):([\d.]+)", probe_text(path))
    if not match:
        raise RuntimeError(f"Cannot parse duration for {path}")
    h, m, s = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def draw_center(
    draw: ImageDraw.ImageDraw,
    y: int,
    text: str,
    font: ImageFont.FreeTypeFont,
    fill,
    spacing: int = 8,
) -> int:
    current_y = y
    for line in text.split("\n"):
        width, height = text_size(draw, line, font)
        draw.text(((720 - width) / 2, current_y), line, font=font, fill=fill)
        current_y += height + spacing
    return current_y


def make_overlays() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    QA_DIR.mkdir(parents=True, exist_ok=True)

    title = Image.new("RGBA", (720, 1280), (0, 0, 0, 0))
    draw = ImageDraw.Draw(title)
    draw.rounded_rectangle((54, 188, 666, 556), radius=18, fill=(0, 0, 0, 166))
    draw_center(draw, 244, "青山", ImageFont.truetype(FONT_BOLD, 88), (255, 255, 255, 248))
    draw_center(draw, 372, "第6集：醒来就是灭门现场", ImageFont.truetype(FONT_BOLD, 32), (238, 238, 236, 242))
    draw.line((120, 450, 600, 450), fill=(176, 210, 204, 150), width=2)
    draw_center(draw, 486, "一刻钟内，陈迹必须靠一张空白宣纸活下去。", ImageFont.truetype(FONT_REGULAR, 24), (218, 226, 224, 232))
    draw_center(draw, 724, "NALU MOTION 出品", ImageFont.truetype(FONT_REGULAR, 22), (205, 205, 205, 218))
    title.save(TITLE_OVERLAY)

    tail = Image.new("RGBA", (720, 1280), (0, 0, 0, 218))
    logo = Image.open(LOGO).convert("RGBA")
    logo.thumbnail((270, 152), Image.Resampling.LANCZOS)
    tail.paste(logo, ((720 - logo.width) // 2, 404), logo)
    draw = ImageDraw.Draw(tail)
    draw_center(draw, 610, "NALU MOTION", ImageFont.truetype(FONT_BOLD, 48), (255, 255, 255, 245))
    draw_center(draw, 680, "A Nalu Motion Pictures Production", ImageFont.truetype(FONT_REGULAR, 22), (205, 205, 205, 225))
    draw_center(draw, 805, "下一集：宣纸店", ImageFont.truetype(FONT_BOLD, 34), (238, 238, 238, 235))
    tail.save(TAIL_OVERLAY)


def make_final() -> None:
    duration = duration_seconds(RAW)
    title_end = 4.2
    tail_start = max(0.0, duration - 3.2)
    filter_complex = (
        "[0:v]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1[base];"
        f"[base][1:v]overlay=0:0:enable='between(t,0,{title_end:.3f})'[vtitle];"
        f"[vtitle][2:v]overlay=0:0:enable='between(t,{tail_start:.3f},{duration:.3f})'[vout];"
        "[0:a]volume=1.0[aout]"
    )
    run([
        str(FFMPEG), "-y",
        "-i", str(RAW),
        "-loop", "1", "-i", str(TITLE_OVERLAY),
        "-loop", "1", "-i", str(TAIL_OVERLAY),
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "[aout]",
        "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart",
        str(FINAL),
    ])


def extract_qa() -> None:
    QA_DIR.mkdir(parents=True, exist_ok=True)
    duration = duration_seconds(FINAL)
    times = [0.8, 3.4, 8.0, 18.0, 34.0, 50.0, 68.0, 86.0, 106.0, 126.0, max(0.0, duration - 1.8)]
    frames: list[Path] = []
    for idx, timestamp in enumerate(times):
        frame = QA_DIR / f"frame_{idx:02d}_{int(timestamp):03d}s.jpg"
        run([
            str(FFMPEG), "-y", "-ss", f"{timestamp:.2f}", "-i", str(FINAL),
            "-frames:v", "1", "-update", "1", "-q:v", "2", str(frame),
        ])
        frames.append(frame)

    thumbs = []
    font = ImageFont.truetype(FONT_REGULAR, 15)
    for frame in frames:
        img = Image.open(frame).convert("RGB")
        img.thumbnail((180, 320), Image.Resampling.LANCZOS)
        thumb = Image.new("RGB", (180, 352), (12, 12, 12))
        thumb.paste(img, ((180 - img.width) // 2, 0))
        draw = ImageDraw.Draw(thumb)
        draw.text((8, 324), frame.name, font=font, fill=(230, 230, 230))
        thumbs.append(thumb)

    cols = 3
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 180, rows * 352), (18, 18, 18))
    for i, img in enumerate(thumbs):
        sheet.paste(img, ((i % cols) * 180, (i // cols) * 352))
    sheet.save(QA_DIR / "contact_sheet_e06_final.jpg", quality=92)

    (QA_DIR / "ffmpeg_probe_e06_final.txt").write_text(probe_text(FINAL), encoding="utf-8")
    silence = subprocess.run([
        str(FFMPEG), "-hide_banner", "-i", str(FINAL),
        "-af", "silencedetect=n=-35dB:d=2",
        "-f", "null", "-",
    ], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (QA_DIR / "silencedetect_e06_final.txt").write_text(silence.stdout or "", encoding="utf-8")


def main() -> None:
    for required in [FFMPEG, RAW, LOGO]:
        if not required.exists():
            raise FileNotFoundError(required)
    make_overlays()
    make_final()
    extract_qa()
    print(f"FINAL={FINAL}")
    print(f"QA={QA_DIR / 'contact_sheet_e06_final.jpg'}")
    print(f"DURATION={duration_seconds(FINAL):.2f}")


if __name__ == "__main__":
    main()
