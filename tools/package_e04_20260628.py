#!/usr/bin/env python3
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


BASE = Path("/Users/rogerwu/qingshan_short_drama")
FFMPEG = BASE / ".video_deps/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1"
RAW = BASE / "exports/e04/qingshan_E04_ad_master_20260628.mp4"
LOGO = BASE / "libraries/brand/nalu_motion_cat_logo_v1.png"
OUT_DIR = BASE / "exports/e04/final_package"
QA_DIR = BASE / "qa/e04_20260628/final_package"

TITLE_OVERLAY = OUT_DIR / "qingshan_E04_title_overlay_20260628.png"
TAIL_OVERLAY = OUT_DIR / "qingshan_E04_nalu_tail_overlay_20260628.png"
FINAL = OUT_DIR / "qingshan_E04_final_titled_subtitled_nalu_20260628.mp4"

FONT_REGULAR = "/System/Library/Fonts/STHeiti Light.ttc"
FONT_BOLD = "/System/Library/Fonts/STHeiti Medium.ttc"


SUBTITLES = [
    "",
    "王龙：陈家的小孩，还敢来？",
    "陈迹：我爸妈出事那晚，也下这种雨。",
    "陈迹：老刘给你的证明，我拿到原件了。",
    "王龙：我有病历，法院都拿我没办法。",
    "李青鸟：六楼的墙，会替人记账。",
    "老人：他每天半夜，都给同一个人打电话。",
    "陈迹：接。让六楼都听听。",
    "老刘：王老板，诊断书我补好了，车祸案没人会翻。",
    "王龙：关了！谁让你们录的！",
    "陈迹：半年前，是不是你开的车？",
    "王龙：是我开的。可你能把我怎么样？",
    "护士声：六楼三号房，门禁失控！",
    "王龙：你二叔收过我的钱，你也可以。",
    "陈迹：我爸妈没收，你也买不了我。",
    "王龙：你就是个疯子！",
    "老人：十二岁的蝉，原来真会开门。",
    "李青鸟：不是你疯，是门在选人。",
    "陈迹：门后面，是哪儿？",
    "母亲：陈迹，往前走。",
    "陈迹：我回来之前，他别想逃。",
    "李青鸟：北俱芦洲的人，会负责偷渡。",
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
    if "：" in text:
        speaker, line = text.split("：", 1)
        prefix = speaker + "："
        if len(prefix + line) <= max_chars:
            return prefix + line
        cut = max(8, min(max_chars - len(prefix), len(line)))
        return prefix + line[:cut] + "\n" + line[cut:]
    return text[:max_chars] + "\n" + text[max_chars:]


def make_overlays() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    QA_DIR.mkdir(parents=True, exist_ok=True)

    title = Image.new("RGBA", (720, 1280), (0, 0, 0, 0))
    draw = ImageDraw.Draw(title)
    draw.rounded_rectangle((52, 210, 668, 540), radius=18, fill=(0, 0, 0, 150))
    draw_center(draw, 258, "青山", ImageFont.truetype(FONT_BOLD, 88), (255, 255, 255, 248))
    draw_center(draw, 382, "第4集：六楼门开，王龙现形", ImageFont.truetype(FONT_BOLD, 34), (238, 238, 236, 242))
    draw.line((120, 455, 600, 455), fill=(175, 205, 200, 150), width=2)
    draw_center(draw, 486, "一个被判疯的少年，把仇人逼到当场自爆。", ImageFont.truetype(FONT_REGULAR, 24), (210, 218, 216, 230))
    title.save(TITLE_OVERLAY)

    tail = Image.new("RGBA", (720, 1280), (0, 0, 0, 215))
    logo = Image.open(LOGO).convert("RGBA")
    logo.thumbnail((270, 152), Image.Resampling.LANCZOS)
    tail.paste(logo, ((720 - logo.width) // 2, 410), logo)
    draw = ImageDraw.Draw(tail)
    draw_center(draw, 610, "NALU MOTION", ImageFont.truetype(FONT_BOLD, 48), (255, 255, 255, 245))
    draw_center(draw, 680, "A Nalu Motion Pictures Production", ImageFont.truetype(FONT_REGULAR, 22), (205, 205, 205, 225))
    draw_center(draw, 805, "下一集：梦门之后", ImageFont.truetype(FONT_BOLD, 34), (238, 238, 238, 235))
    tail.save(TAIL_OVERLAY)


def make_final() -> None:
    duration = duration_seconds(RAW)
    shot_len = duration / len(SUBTITLES)
    text_dir = OUT_DIR / "subtitle_text_e04_20260628"
    text_dir.mkdir(parents=True, exist_ok=True)

    draw_filters: list[str] = []
    for idx, text in enumerate(SUBTITLES, start=1):
        if not text:
            continue
        start = (idx - 1) * shot_len + 0.85
        end = min(idx * shot_len - 0.55, duration - 0.2)
        text_file = text_dir / f"subtitle_{idx:03d}.txt"
        text_file.write_text(wrap_cn(text), encoding="utf-8")
        draw_filters.append(
            "drawtext="
            "fontfile=/System/Library/Fonts/STHeiti\\ Medium.ttc:"
            f"textfile={text_file}:"
            "fontsize=22:"
            "fontcolor=white:"
            "borderw=2:"
            "bordercolor=black@0.78:"
            "box=1:"
            "boxcolor=black@0.34:"
            "boxborderw=10:"
            "line_spacing=5:"
            "x=(w-text_w)/2:"
            "y=h-138:"
            f"enable='between(t,{start:.3f},{end:.3f})'"
        )

    tail_start = max(0.0, duration - 3.3)
    title_end = 4.4
    subtitle_chain = ",".join(draw_filters)
    filter_complex = (
        "[0:v]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1[base];"
        f"[base][1:v]overlay=0:0:enable='between(t,0,{title_end:.3f})'[vtitle];"
        f"[vtitle][2:v]overlay=0:0:enable='between(t,{tail_start:.3f},{duration:.3f})'[vover];"
        f"[vover]{subtitle_chain if subtitle_chain else 'null'}[vout];"
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
    times = [0.7, 3.0, 8.8, 28.0, 52.0, 76.0, 100.0, 124.0, 148.0, max(0.0, duration - 2.0)]
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

    silence_log = QA_DIR / "silencedetect_e04_final.txt"
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
    make_overlays()
    make_final()
    extract_qa()
    print(f"FINAL={FINAL}")
    print(f"QA={QA_DIR / 'contact_sheet_e04_final.jpg'}")
    print(f"DURATION={duration_seconds(FINAL):.2f}")


if __name__ == "__main__":
    main()
