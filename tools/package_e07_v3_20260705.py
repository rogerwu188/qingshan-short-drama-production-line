#!/usr/bin/env python3
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


BASE = Path("/Users/rogerwu/qingshan_short_drama")
FFMPEG = BASE / ".video_deps/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1"
RAW = BASE / "exports/e07_v3_20260705/qingshan_E07_v3_export_20260705.mp4"
LOGO = BASE / "libraries/brand/nalu_motion_cat_logo_v1.png"
OUT_DIR = BASE / "exports/e07/final_package_v3_20260705"
QA_DIR = BASE / "qa/e07_v3_final_package_20260705"

TITLE_OVERLAY = OUT_DIR / "qingshan_E07_v3_title_overlay_20260705.png"
TAIL_OVERLAY = OUT_DIR / "qingshan_E07_v3_nalu_tail_overlay_20260705.png"
FINAL = OUT_DIR / "qingshan_E07_v3_final_platform_sound_smallsubs_nalu_20260705.mp4"

FONT_REGULAR = "/System/Library/Fonts/STHeiti Light.ttc"
FONT_BOLD = "/System/Library/Fonts/STHeiti Medium.ttc"

PLANNED_DURATIONS = [5, 6, 6, 6, 6, 6, 6, 6, 5, 6, 7, 6, 6, 7, 6, 7, 7, 6, 7, 6, 6, 6, 7, 6, 7, 4]

SUBTITLES = [
    "洛城卖宣纸的店，少说二十家。",
    "看纹路。每个匠人的纸，都不一样。",
    "你是说，能找到那家店？",
    "找到同样纹路，就能找到写字的人。",
    "按纹路找，连夜查。",
    "他死了。",
    "毒囊我摘了。他哪来的毒？",
    "他刚才不是想杀我，是想取毒。",
    "陈迹，在里面吗？",
    "来的是谁？别动。",
    "姚太医，许久没见。我不是来见你的。",
    "陈迹，药送到了。也该回去了。",
    "快跟你师父回去吧。",
    "别乱说。我们还会找你。",
    "师父，谢谢您来接我。",
    "早知道是密谍司，我就不来了。",
    "走左边，右边会让我破财。",
    "这是哪儿？太平医馆。",
    "进来。把手里的东西扔了。",
    "我得先活下来。",
    "送个药，怎么去了这么久？",
    "明天再说。",
    "人已经跟姚太医走了。",
    "他若是谍探，杀他的人会自己来。",
    "那我们就等。",
    "",
]


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


def draw_center(draw: ImageDraw.ImageDraw, y: int, text: str, font: ImageFont.FreeTypeFont, fill, spacing: int = 8) -> int:
    current_y = y
    for line in text.split("\n"):
        width, height = text_size(draw, line, font)
        draw.text(((720 - width) / 2, current_y), line, font=font, fill=fill)
        current_y += height + spacing
    return current_y


def wrap_cn(text: str, max_chars: int = 17) -> str:
    if len(text) <= max_chars:
        return text
    for mark in ["。", "？", "！", "，"]:
        if mark in text and len(text) <= max_chars * 2:
            left, right = text.split(mark, 1)
            if right:
                return left + mark + "\n" + right
    return text[:max_chars] + "\n" + text[max_chars:]


def make_overlays() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    QA_DIR.mkdir(parents=True, exist_ok=True)

    title = Image.new("RGBA", (720, 1280), (0, 0, 0, 0))
    draw = ImageDraw.Draw(title)
    draw.rounded_rectangle((52, 190, 668, 552), radius=18, fill=(0, 0, 0, 160))
    draw_center(draw, 246, "青山", ImageFont.truetype(FONT_BOLD, 88), (255, 255, 255, 248))
    draw_center(draw, 372, "第7集：同僚盯上我", ImageFont.truetype(FONT_BOLD, 34), (238, 238, 236, 242))
    draw.line((120, 448, 600, 448), fill=(176, 210, 204, 150), width=2)
    draw_center(draw, 482, "一张宣纸，把陈迹推到密谍司眼前。", ImageFont.truetype(FONT_REGULAR, 25), (218, 226, 224, 232))
    draw_center(draw, 720, "NALU MOTION 出品", ImageFont.truetype(FONT_REGULAR, 22), (205, 205, 205, 218))
    title.save(TITLE_OVERLAY)

    tail = Image.new("RGBA", (720, 1280), (0, 0, 0, 214))
    logo = Image.open(LOGO).convert("RGBA")
    logo.thumbnail((270, 152), Image.Resampling.LANCZOS)
    tail.paste(logo, ((720 - logo.width) // 2, 405), logo)
    draw = ImageDraw.Draw(tail)
    draw_center(draw, 610, "NALU MOTION", ImageFont.truetype(FONT_BOLD, 48), (255, 255, 255, 245))
    draw_center(draw, 680, "A Nalu Motion Pictures Production", ImageFont.truetype(FONT_REGULAR, 22), (205, 205, 205, 225))
    draw_center(draw, 805, "下一集：宣纸店", ImageFont.truetype(FONT_BOLD, 34), (238, 238, 238, 235))
    tail.save(TAIL_OVERLAY)


def make_final() -> None:
    duration = duration_seconds(RAW)
    planned_total = sum(PLANNED_DURATIONS)
    scale = duration / planned_total
    text_dir = OUT_DIR / "subtitle_text_e07_v3_20260705"
    text_dir.mkdir(parents=True, exist_ok=True)

    draw_filters: list[str] = []
    cursor = 0.0
    for idx, (planned, text) in enumerate(zip(PLANNED_DURATIONS, SUBTITLES), start=1):
        start = cursor * scale + 0.40
        end = min((cursor + planned) * scale - 0.30, duration - 0.2)
        cursor += planned
        if not text or end <= start:
            continue
        text_file = text_dir / f"subtitle_{idx:03d}.txt"
        text_file.write_text(wrap_cn(text), encoding="utf-8")
        draw_filters.append(
            "drawtext="
            "fontfile=/System/Library/Fonts/STHeiti\\ Medium.ttc:"
            f"textfile={text_file}:"
            "fontsize=22:"
            "fontcolor=white:"
            "borderw=2:"
            "bordercolor=black@0.82:"
            "box=1:"
            "boxcolor=black@0.34:"
            "boxborderw=9:"
            "line_spacing=5:"
            "x=(w-text_w)/2:"
            "y=h-132:"
            f"enable='between(t,{start:.3f},{end:.3f})'"
        )

    title_end = 4.2
    tail_start = max(0.0, duration - 3.2)
    subtitle_chain = ",".join(draw_filters) if draw_filters else "null"
    filter_complex = (
        "[0:v]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1[base];"
        f"[base][1:v]overlay=0:0:enable='between(t,0,{title_end:.3f})'[vtitle];"
        f"[vtitle][2:v]overlay=0:0:enable='between(t,{tail_start:.3f},{duration:.3f})'[vover];"
        f"[vover]{subtitle_chain}[vout];"
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
    times = [0.7, 3.2, 8.0, 20.0, 38.0, 56.0, 74.0, 92.0, 112.0, 132.0, 150.0, max(0.0, duration - 1.8)]
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
    sheet.save(QA_DIR / "contact_sheet_e07_v3_final.jpg", quality=92)

    (QA_DIR / "ffmpeg_probe_e07_v3_final.txt").write_text(probe_text(FINAL), encoding="utf-8")
    silence = subprocess.run([
        str(FFMPEG), "-hide_banner", "-i", str(FINAL),
        "-af", "silencedetect=n=-35dB:d=2",
        "-f", "null", "-",
    ], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (QA_DIR / "silencedetect_e07_v3_final.txt").write_text(silence.stdout or "", encoding="utf-8")


def main() -> None:
    for required in [FFMPEG, RAW, LOGO]:
        if not required.exists():
            raise FileNotFoundError(required)
    make_overlays()
    make_final()
    extract_qa()
    print(f"FINAL={FINAL}")
    print(f"QA={QA_DIR / 'contact_sheet_e07_v3_final.jpg'}")
    print(f"DURATION={duration_seconds(FINAL):.2f}")


if __name__ == "__main__":
    main()
