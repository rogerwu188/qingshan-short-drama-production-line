#!/usr/bin/env python3
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


BASE = Path("/Users/rogerwu/qingshan_short_drama")
FFMPEG = BASE / ".video_deps/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1"
RAW = BASE / "exports/e03_v4_20260627/qingshan_E03_v4_ad_raw_20260627.mp4"
LOGO = BASE / "libraries/brand/nalu_motion_cat_logo_v1.png"
OUT_DIR = BASE / "exports/e03_v4_20260627/final_package"
QA_DIR = BASE / "qa/e03_v4_20260627/final_package"

TITLE_PNG = OUT_DIR / "qingshan_E03_v4_title_card_20260627.png"
TAIL_PNG = OUT_DIR / "qingshan_E03_v4_nalu_tail_20260627.png"
TITLE_MP4 = OUT_DIR / "qingshan_E03_v4_title_card_20260627.mp4"
TAIL_MP4 = OUT_DIR / "qingshan_E03_v4_nalu_tail_20260627.mp4"
BODY_AUDIO_FIXED = OUT_DIR / "qingshan_E03_v4_body_audio_fixed_20260627.mp4"
FINAL = OUT_DIR / "qingshan_E03_final_v4_titled_nalu_audiofixed_20260627.mp4"

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


def duration_seconds(path: Path) -> float:
    proc = subprocess.run(
        [str(FFMPEG), "-hide_banner", "-i", str(path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    match = re.search(r"Duration: (\d+):(\d+):([\d.]+)", proc.stdout or "")
    if not match:
        raise RuntimeError(f"Cannot parse duration for {path}")
    h, m, s = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def draw_center(draw: ImageDraw.ImageDraw, y: int, text: str, font: ImageFont.FreeTypeFont, fill, spacing: int = 10) -> int:
    lines = text.split("\n")
    heights = [text_size(draw, line, font)[1] for line in lines]
    current_y = y
    for line, height in zip(lines, heights):
        width, _ = text_size(draw, line, font)
        draw.text(((720 - width) / 2, current_y), line, font=font, fill=fill)
        current_y += height + spacing
    return current_y


def make_cards() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    QA_DIR.mkdir(parents=True, exist_ok=True)
    logo = Image.open(LOGO).convert("RGBA")
    logo.thumbnail((236, 132), Image.Resampling.LANCZOS)

    title = Image.new("RGB", (720, 1280), (5, 7, 10))
    layer = Image.new("RGBA", title.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    title.paste(logo, ((720 - logo.width) // 2, 300), logo)
    draw_center(draw, 488, "青山", ImageFont.truetype(FONT_BOLD, 90), (255, 255, 255, 245))
    draw_center(draw, 620, "第3集：真凶就在六楼", ImageFont.truetype(FONT_BOLD, 36), (235, 238, 236, 238))
    draw.line((110, 697, 610, 697), fill=(150, 182, 182, 150), width=2)
    draw_center(draw, 740, "一个被判疯的少年，把所有人引到真凶面前。", ImageFont.truetype(FONT_REGULAR, 25), (196, 205, 204, 225))
    draw_center(draw, 836, "NALU MOTION 出品", ImageFont.truetype(FONT_REGULAR, 23), (170, 174, 174, 215))
    Image.alpha_composite(title.convert("RGBA"), layer).convert("RGB").save(TITLE_PNG, quality=95)

    tail = Image.new("RGB", (720, 1280), (0, 0, 0))
    layer = Image.new("RGBA", tail.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    logo2 = Image.open(LOGO).convert("RGBA")
    logo2.thumbnail((330, 186), Image.Resampling.LANCZOS)
    tail.paste(logo2, ((720 - logo2.width) // 2, 388), logo2)
    draw_center(draw, 620, "NALU MOTION", ImageFont.truetype(FONT_BOLD, 50), (255, 255, 255, 245))
    draw_center(draw, 692, "A Nalu Motion Pictures Production", ImageFont.truetype(FONT_REGULAR, 23), (205, 205, 205, 225))
    draw_center(draw, 810, "下一集：以命复仇", ImageFont.truetype(FONT_BOLD, 34), (238, 238, 238, 235))
    Image.alpha_composite(tail.convert("RGBA"), layer).convert("RGB").save(TAIL_PNG, quality=95)


def make_card_video(image: Path, output: Path, duration: float) -> None:
    run([
        str(FFMPEG), "-y",
        "-loop", "1", "-framerate", "30", "-t", f"{duration:.2f}", "-i", str(image),
        "-f", "lavfi", "-t", f"{duration:.2f}", "-i",
        "anoisesrc=color=pink:sample_rate=48000,lowpass=f=620,highpass=f=90,volume=0.075",
        "-shortest",
        "-vf", "format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
        "-movflags", "+faststart",
        str(output),
    ])


def fix_body_audio() -> None:
    dur = duration_seconds(RAW)
    # Quiet room tone only; this is not music and should not compete with dialogue.
    filter_complex = (
        f"anoisesrc=color=pink:sample_rate=48000:duration={dur:.3f},"
        "lowpass=f=850,highpass=f=80,volume=0.125[amb];"
        "[0:a]volume=1.0[orig];"
        "[orig][amb]amix=inputs=2:normalize=0:duration=first[aout]"
    )
    run([
        str(FFMPEG), "-y", "-i", str(RAW),
        "-filter_complex", filter_complex,
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart",
        str(BODY_AUDIO_FIXED),
    ])


def concat_final() -> None:
    run([
        str(FFMPEG), "-y",
        "-i", str(TITLE_MP4), "-i", str(BODY_AUDIO_FIXED), "-i", str(TAIL_MP4),
        "-filter_complex",
        "[0:v]setsar=1[v0];[1:v]setsar=1[v1];[2:v]setsar=1[v2];"
        "[v0][0:a][v1][1:a][v2][2:a]concat=n=3:v=1:a=1[v][a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart",
        str(FINAL),
    ])


def extract_qa_frames() -> None:
    QA_DIR.mkdir(parents=True, exist_ok=True)
    dur = duration_seconds(FINAL)
    times = [0.5, 3.5, 7.0, 18.0, 35.0, 55.0, 80.0, 105.0, 130.0, 153.0, max(0.0, dur - 2.0)]
    frames: list[Path] = []
    for idx, timestamp in enumerate(times):
        frame = QA_DIR / f"frame_{idx:02d}_{int(timestamp):03d}s.jpg"
        run([
            str(FFMPEG), "-y", "-ss", f"{timestamp:.2f}", "-i", str(FINAL),
            "-frames:v", "1", "-update", "1", "-q:v", "2", str(frame),
        ])
        frames.append(frame)

    thumbs = []
    for frame in frames:
        img = Image.open(frame).convert("RGB")
        img.thumbnail((180, 320), Image.Resampling.LANCZOS)
        thumb = Image.new("RGB", (180, 320), (10, 10, 10))
        thumb.paste(img, ((180 - img.width) // 2, (320 - img.height) // 2))
        thumbs.append((frame.name, thumb))

    sheet = Image.new("RGB", (4 * 180, 3 * 360), (18, 18, 18))
    draw = ImageDraw.Draw(sheet)
    label_font = ImageFont.truetype(FONT_REGULAR, 16)
    for i, (label, img) in enumerate(thumbs):
        x = (i % 4) * 180
        y = (i // 4) * 360
        sheet.paste(img, (x, y))
        draw.text((x + 8, y + 323), label, font=label_font, fill=(230, 230, 230))
    sheet.save(QA_DIR / "contact_sheet_final_v4.jpg", quality=92)

    silence_log = QA_DIR / "silencedetect_final_v4.txt"
    proc = subprocess.run([
        str(FFMPEG), "-hide_banner", "-i", str(FINAL),
        "-af", "silencedetect=n=-35dB:d=2",
        "-f", "null", "-",
    ], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    silence_log.write_text(proc.stdout, encoding="utf-8")


def main() -> None:
    for required in [FFMPEG, RAW, LOGO]:
        if not required.exists():
            raise FileNotFoundError(required)
    make_cards()
    make_card_video(TITLE_PNG, TITLE_MP4, 3.8)
    make_card_video(TAIL_PNG, TAIL_MP4, 3.0)
    fix_body_audio()
    concat_final()
    extract_qa_frames()
    print(f"FINAL={FINAL}")
    print(f"QA={QA_DIR / 'contact_sheet_final_v4.jpg'}")
    print(f"DURATION={duration_seconds(FINAL):.2f}")


if __name__ == "__main__":
    main()
