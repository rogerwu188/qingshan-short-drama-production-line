#!/usr/bin/env python3
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


BASE = Path("/Users/rogerwu/qingshan_short_drama")
FFMPEG = BASE / ".video_deps/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1"
RAW = BASE / "exports/e03_rebuild_20260625/qingshan_E03_ad_raw_recut17_20260625.mp4"
SRC_SUBS = BASE / "exports/e03_rebuild_20260624/qingshan_E03_subtitles_short_20260624.srt"
LOGO = BASE / "libraries/brand/nalu_motion_cat_logo_v1.png"
OUT_DIR = BASE / "exports/e03_rebuild_20260625"
QA_DIR = BASE / "qa/e03_recut17_final_20260625"

TITLE_PNG = OUT_DIR / "qingshan_E03_recut17_title_card_20260625.png"
TAIL_PNG = OUT_DIR / "qingshan_E03_recut17_nalu_tail_20260625.png"
TITLE_MP4 = OUT_DIR / "qingshan_E03_recut17_title_card_20260625.mp4"
TAIL_MP4 = OUT_DIR / "qingshan_E03_recut17_nalu_tail_20260625.mp4"
SUBS = OUT_DIR / "qingshan_E03_recut17_smallsubs_20260625.srt"
RAW_SUBBED = OUT_DIR / "qingshan_E03_recut17_subtitled_body_20260625.mp4"
FINAL = OUT_DIR / "qingshan_E03_final_recut17_titled_subtitled_nalu_20260625.mp4"
SUB_TEXT_DIR = OUT_DIR / "subtitle_text_recut17_20260625"

FONT_REGULAR = "/System/Library/Fonts/STHeiti Light.ttc"
FONT_BOLD = "/System/Library/Fonts/STHeiti Medium.ttc"


def run(args: list[str]) -> subprocess.CompletedProcess[bytes]:
    print("+", " ".join(map(str, args)))
    return subprocess.run(args, check=True)


def text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def draw_center(draw: ImageDraw.ImageDraw, y: int, text: str, font: ImageFont.FreeTypeFont, fill, spacing: int = 10) -> int:
    lines = text.split("\n")
    heights = [text_size(draw, line, font)[1] for line in lines]
    total = sum(heights) + spacing * (len(lines) - 1)
    cy = y
    for line, h in zip(lines, heights):
        w, _ = text_size(draw, line, font)
        draw.text(((720 - w) / 2, cy), line, font=font, fill=fill)
        cy += h + spacing
    return y + total


def make_cards() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    QA_DIR.mkdir(parents=True, exist_ok=True)
    logo = Image.open(LOGO).convert("RGBA")
    logo.thumbnail((250, 140), Image.Resampling.LANCZOS)

    title = Image.new("RGB", (720, 1280), (3, 5, 7))
    layer = Image.new("RGBA", title.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    title.paste(logo, ((720 - logo.width) // 2, 318), logo)
    draw_center(draw, 500, "青山", ImageFont.truetype(FONT_BOLD, 86), (255, 255, 255, 245))
    draw_center(draw, 625, "第3集：真凶就在六楼", ImageFont.truetype(FONT_BOLD, 36), (232, 232, 232, 240))
    draw.line((115, 700, 605, 700), fill=(165, 190, 185, 155), width=2)
    draw_center(draw, 742, "一个被判疯的少年，摸到仇人的床边。", ImageFont.truetype(FONT_REGULAR, 25), (190, 200, 198, 230))
    draw_center(draw, 835, "NALU MOTION 出品", ImageFont.truetype(FONT_REGULAR, 23), (165, 165, 165, 220))
    title = Image.alpha_composite(title.convert("RGBA"), layer).convert("RGB")
    title.save(TITLE_PNG, quality=95)

    tail = Image.new("RGB", (720, 1280), (0, 0, 0))
    layer = Image.new("RGBA", tail.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    logo2 = Image.open(LOGO).convert("RGBA")
    logo2.thumbnail((330, 186), Image.Resampling.LANCZOS)
    tail.paste(logo2, ((720 - logo2.width) // 2, 392), logo2)
    draw_center(draw, 615, "NALU MOTION", ImageFont.truetype(FONT_BOLD, 50), (255, 255, 255, 245))
    draw_center(draw, 688, "A Nalu Motion Pictures Production", ImageFont.truetype(FONT_REGULAR, 23), (205, 205, 205, 225))
    draw_center(draw, 810, "下一集：以命复仇", ImageFont.truetype(FONT_BOLD, 34), (238, 238, 238, 235))
    tail = Image.alpha_composite(tail.convert("RGBA"), layer).convert("RGB")
    tail.save(TAIL_PNG, quality=95)


def make_card_video(image: Path, output: Path, duration: float) -> None:
    run([
        str(FFMPEG), "-y",
        "-loop", "1", "-framerate", "30", "-t", f"{duration:.2f}", "-i", str(image),
        "-f", "lavfi", "-t", f"{duration:.2f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-shortest",
        "-vf", "format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(output),
    ])


def burn_subtitles() -> None:
    shutil.copyfile(SRC_SUBS, SUBS)
    SUB_TEXT_DIR.mkdir(parents=True, exist_ok=True)
    subtitles = parse_srt(SUBS)
    draw_filters = []
    for idx, (start, end, text) in enumerate(subtitles, start=1):
        text_file = SUB_TEXT_DIR / f"subtitle_{idx:03d}.txt"
        text_file.write_text(text, encoding="utf-8")
        draw_filters.append(
            "drawtext="
            "fontfile=/System/Library/Fonts/STHeiti\\ Medium.ttc:"
            f"textfile={text_file}:"
            "fontsize=24:"
            "fontcolor=white:"
            "borderw=2:"
            "bordercolor=black@0.75:"
            "box=1:"
            "boxcolor=black@0.36:"
            "boxborderw=14:"
            "x=(w-text_w)/2:"
            "y=h-150:"
            f"enable='between(t,{start:.3f},{end:.3f})'"
        )
    sub_filter = "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1"
    if draw_filters:
        sub_filter += "," + ",".join(draw_filters)
    run([
        str(FFMPEG), "-y", "-i", str(RAW),
        "-vf", sub_filter,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart",
        str(RAW_SUBBED),
    ])


def parse_timecode(value: str) -> float:
    hms, millis = value.split(",")
    h, m, s = hms.split(":")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(millis) / 1000.0


def parse_srt(path: Path) -> list[tuple[float, float, str]]:
    blocks = re.split(r"\n\s*\n", path.read_text(encoding="utf-8").strip())
    parsed: list[tuple[float, float, str]] = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        start_s, end_s = [part.strip() for part in lines[1].split("-->")]
        text = " ".join(lines[2:])
        parsed.append((parse_timecode(start_s), parse_timecode(end_s), text))
    return parsed


def concat_final() -> None:
    run([
        str(FFMPEG), "-y",
        "-i", str(TITLE_MP4), "-i", str(RAW_SUBBED), "-i", str(TAIL_MP4),
        "-filter_complex",
        "[0:v]setsar=1[v0];[1:v]setsar=1[v1];[2:v]setsar=1[v2];"
        "[v0][0:a][v1][1:a][v2][2:a]concat=n=3:v=1:a=1[v][a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart",
        str(FINAL),
    ])


def duration_seconds(path: Path) -> float:
    proc = subprocess.run([str(FFMPEG), "-hide_banner", "-i", str(path)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    match = re.search(r"Duration: (\d+):(\d+):([\d.]+)", proc.stdout)
    if not match:
        raise RuntimeError(f"Cannot parse duration for {path}")
    h, m, s = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def extract_qa_frames() -> None:
    QA_DIR.mkdir(parents=True, exist_ok=True)
    dur = duration_seconds(FINAL)
    times = [0.5, 3.0, 8.0, 20.0, 45.0, 75.0, 105.0, 135.0, 165.0, max(0.0, dur - 2.0)]
    frames: list[Path] = []
    for idx, t in enumerate(times):
        frame = QA_DIR / f"frame_{idx:02d}_{int(t):03d}s.jpg"
        run([
            str(FFMPEG), "-y", "-ss", f"{t:.2f}", "-i", str(FINAL),
            "-frames:v", "1", "-update", "1", "-q:v", "2", str(frame)
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
    sheet.save(QA_DIR / "contact_sheet_final_recut17.jpg", quality=92)

    silence_log = QA_DIR / "silencedetect_final_recut17.txt"
    proc = subprocess.run([
        str(FFMPEG), "-hide_banner", "-i", str(FINAL),
        "-af", "silencedetect=n=-35dB:d=2",
        "-f", "null", "-"
    ], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    silence_log.write_text(proc.stdout, encoding="utf-8")


def main() -> None:
    for required in [FFMPEG, RAW, SRC_SUBS, LOGO]:
        if not required.exists():
            raise FileNotFoundError(required)
    make_cards()
    make_card_video(TITLE_PNG, TITLE_MP4, 4.2)
    make_card_video(TAIL_PNG, TAIL_MP4, 3.2)
    burn_subtitles()
    concat_final()
    extract_qa_frames()
    print(f"FINAL={FINAL}")
    print(f"QA={QA_DIR / 'contact_sheet_final_recut17.jpg'}")
    print(f"DURATION={duration_seconds(FINAL):.2f}")


if __name__ == "__main__":
    main()
