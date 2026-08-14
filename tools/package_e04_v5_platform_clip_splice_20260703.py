#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


BASE = Path("/Users/rogerwu/qingshan_short_drama")
FFMPEG = BASE / ".video_deps/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1"
CONFIG = BASE / "configs/e04_v5_continuity_config_actual_v3_20260703.json"
LOGO = BASE / "libraries/brand/nalu_motion_cat_logo_v1.png"


def env_path(name: str, default: Path) -> Path:
    return Path(os.environ.get(name, str(default))).expanduser()


RAW = env_path(
    "E04_RAW",
    BASE / "working_assets/e04_v5_all_shots_qa_repair_v3_20260703/qingshan_E04_v5_repair_v3_platform_concat_reencoded.mp4",
)
OUT_DIR = env_path("E04_OUT_DIR", BASE / "exports/e04/platform_clip_splice_v5_20260703")
QA_DIR = env_path("E04_QA_DIR", BASE / "qa/e04_v5_platform_clip_splice_20260703")
FINAL = env_path(
    "E04_FINAL",
    OUT_DIR / "qingshan_E04_v5_platform_clip_splice_titled_subtitled_nalu_20260703.mp4",
)

TITLE_OVERLAY = OUT_DIR / "qingshan_E04_v5_title_overlay_20260703.png"
TAIL_OVERLAY = OUT_DIR / "qingshan_E04_v5_nalu_tail_overlay_20260703.png"

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
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def draw_center(
    draw: ImageDraw.ImageDraw,
    y: int,
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int, int],
    spacing: int = 8,
) -> int:
    current_y = y
    for line in text.split("\n"):
        width, height = text_size(draw, line, font)
        draw.text(((720 - width) / 2, current_y), line, font=font, fill=fill)
        current_y += height + spacing
    return current_y


def wrap_cn(text: str, max_chars: int = 18) -> str:
    if len(text) <= max_chars:
        return text
    if "：" in text:
        speaker, line = text.split("：", 1)
        prefix = speaker + "："
        if len(prefix + line) <= max_chars:
            return prefix + line
        first_len = max(6, min(max_chars - len(prefix), len(line)))
        return prefix + line[:first_len] + "\n" + line[first_len:]
    return text[:max_chars] + "\n" + text[max_chars:]


def load_shots() -> list[dict]:
    data = json.loads(CONFIG.read_text(encoding="utf-8"))
    shots = data.get("shots") or []
    if not shots:
        raise RuntimeError(f"No shots in {CONFIG}")
    return shots


def make_overlays() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    QA_DIR.mkdir(parents=True, exist_ok=True)

    title = Image.new("RGBA", (720, 1280), (0, 0, 0, 0))
    draw = ImageDraw.Draw(title)
    draw.rounded_rectangle((52, 206, 668, 548), radius=18, fill=(0, 0, 0, 150))
    draw_center(draw, 254, "青山", ImageFont.truetype(FONT_BOLD, 88), (255, 255, 255, 248))
    draw_center(draw, 382, "第4集：六楼门开，王龙现形", ImageFont.truetype(FONT_BOLD, 33), (238, 238, 236, 242))
    draw.line((122, 458, 598, 458), fill=(170, 202, 198, 150), width=2)
    draw_center(draw, 492, "一个被判疯的少年，把仇人逼到当场自爆。", ImageFont.truetype(FONT_REGULAR, 24), (210, 218, 216, 230))
    title.save(TITLE_OVERLAY)

    tail = Image.new("RGBA", (720, 1280), (0, 0, 0, 218))
    logo = Image.open(LOGO).convert("RGBA")
    logo.thumbnail((270, 152), Image.Resampling.LANCZOS)
    tail.paste(logo, ((720 - logo.width) // 2, 404), logo)
    draw = ImageDraw.Draw(tail)
    draw_center(draw, 604, "NALU MOTION", ImageFont.truetype(FONT_BOLD, 48), (255, 255, 255, 245))
    draw_center(draw, 674, "A Nalu Motion Pictures Production", ImageFont.truetype(FONT_REGULAR, 22), (205, 205, 205, 225))
    draw_center(draw, 798, "下一集：梦门之后", ImageFont.truetype(FONT_BOLD, 34), (238, 238, 238, 235))
    tail.save(TAIL_OVERLAY)


def make_filter(shots: list[dict], duration: float) -> str:
    text_dir = OUT_DIR / "subtitle_text_e04_v5_20260703"
    text_dir.mkdir(parents=True, exist_ok=True)
    draw_filters: list[str] = []
    cursor = 0.0
    for shot in shots:
        shot_duration = float(shot.get("duration", 0) or 0)
        text = str(shot.get("dialogue", "")).strip()
        start = cursor
        end = cursor + shot_duration
        cursor = end
        if not text:
            continue
        text_file = text_dir / f"subtitle_{str(shot.get('shot_id', 'xx')).zfill(2)}.txt"
        text_file.write_text(wrap_cn(text), encoding="utf-8")
        sub_start = min(duration - 0.25, start + 0.45)
        sub_end = min(duration - 0.15, max(sub_start + 0.8, end - 0.28))
        draw_filters.append(
            "drawtext="
            "fontfile=/System/Library/Fonts/STHeiti\\ Medium.ttc:"
            f"textfile={text_file}:"
            "fontsize=21:"
            "fontcolor=white:"
            "borderw=2:"
            "bordercolor=black@0.76:"
            "box=1:"
            "boxcolor=black@0.28:"
            "boxborderw=8:"
            "line_spacing=5:"
            "x=(w-text_w)/2:"
            "y=h-132:"
            f"enable='between(t,{sub_start:.3f},{sub_end:.3f})'"
        )

    subtitle_chain = ",".join(draw_filters) if draw_filters else "null"
    tail_start = max(0.0, duration - 3.2)
    title_end = 4.2
    return (
        "[0:v]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1[base];"
        f"[base][1:v]overlay=0:0:enable='between(t,0,{title_end:.3f})'[vtitle];"
        f"[vtitle][2:v]overlay=0:0:enable='between(t,{tail_start:.3f},{duration:.3f})'[vover];"
        f"[vover]{subtitle_chain}[vout];"
        "[0:a]volume=1.0[aout]"
    )


def make_final() -> None:
    duration = duration_seconds(RAW)
    shots = load_shots()
    filter_complex = make_filter(shots, duration)
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
    duration = duration_seconds(FINAL)
    times = [0.7, 3.2, 8.7, 28.0, 52.0, 76.0, 100.0, 124.0, 148.0, max(0.0, duration - 2.0)]
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

    sheet = Image.new("RGB", (5 * 180, 2 * 352), (18, 18, 18))
    draw = ImageDraw.Draw(sheet)
    label_font = ImageFont.truetype(FONT_REGULAR, 15)
    for i, (label, img) in enumerate(thumbs):
        x = (i % 5) * 180
        y = (i // 5) * 352
        sheet.paste(img, (x, y))
        draw.text((x + 8, y + 323), label, font=label_font, fill=(230, 230, 230))
    sheet.save(QA_DIR / "contact_sheet_e04_final.jpg", quality=92)

    silence = subprocess.run([
        str(FFMPEG), "-hide_banner", "-i", str(FINAL),
        "-af", "silencedetect=n=-35dB:d=2",
        "-f", "null", "-",
    ], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (QA_DIR / "silencedetect_e04_final.txt").write_text(silence.stdout, encoding="utf-8")

    volume = subprocess.run([
        str(FFMPEG), "-hide_banner", "-i", str(FINAL),
        "-af", "volumedetect",
        "-f", "null", "-",
    ], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (QA_DIR / "volumedetect_e04_final.txt").write_text(volume.stdout, encoding="utf-8")


def write_manifest() -> None:
    manifest = {
        "episode": "青山 E04",
        "source_policy": "22 Giggle/Seedance platform-generated video clips. Original platform audio preserved. Local packaging only adds title, subtitles, and Nalu Motion tail overlay.",
        "raw": str(RAW),
        "config": str(CONFIG),
        "final": str(FINAL),
        "qa_dir": str(QA_DIR),
        "duration_seconds": round(duration_seconds(FINAL), 2),
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    for required in [FFMPEG, RAW, CONFIG, LOGO]:
        if not required.exists():
            raise FileNotFoundError(required)
    make_overlays()
    make_final()
    extract_qa()
    write_manifest()
    print(f"FINAL={FINAL}")
    print(f"QA={QA_DIR / 'contact_sheet_e04_final.jpg'}")
    print(f"DURATION={duration_seconds(FINAL):.2f}")


if __name__ == "__main__":
    main()
