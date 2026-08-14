#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import re
import subprocess
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

import edge_tts
from PIL import Image, ImageDraw, ImageFont


BASE = Path("/Users/rogerwu/qingshan_short_drama")
QA_SRC = BASE / "qa/e04_audio_repair_20260630"
FFMPEG = BASE / ".video_deps/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1"
LOGO = BASE / "libraries/brand/nalu_motion_cat_logo_v1.png"
OUT_DIR = BASE / "exports/e04/audio_repair_20260630"
WORK_DIR = OUT_DIR / "work"
FINAL = OUT_DIR / "qingshan_E04_full_redub_candidate_20260630.mp4"
QA_DIR = BASE / "qa/e04_audio_repair_20260630/final_full_redub_candidate"

FONT_REGULAR = "/System/Library/Fonts/STHeiti Light.ttc"
FONT_BOLD = "/System/Library/Fonts/STHeiti Medium.ttc"


JSON_REGEN2 = QA_SRC / "e04_latest_modal_urls_after_regen2_20260630.json"
JSON_SHORT = QA_SRC / "e04_latest_modal_urls_after_shortline_regen_20260630.json"
JSON_ULTRA = QA_SRC / "e04_latest_modal_urls_after_ultrashort_regen_20260630.json"
JSON_0910 = QA_SRC / "e04_latest_modal_urls_after_final_0910_regen_20260630.json"
JSON_VISIBLE = QA_SRC / "e04_latest_modal_urls_after_visible_speaker_0910_20260630.json"


SUBTITLES = {
    1: "",
    2: "王龙：陈家的小孩，还敢来？",
    3: "陈迹：我爸妈出事那晚，也下这种雨。",
    4: "陈迹：老刘给你的证明，我拿到原件了。",
    5: "王龙：我有病历，法院都拿我没办法。",
    6: "李青鸟：六楼的墙，会替人记账。",
    7: "老人：他每天半夜，都给同一个人打电话。",
    8: "陈迹：接。让六楼都听听。",
    9: "老刘：证明好了。",
    10: "王龙：关掉！",
    11: "陈迹：半年前，是不是你开的车？",
    12: "王龙：是我开的。可你能把我怎么样？",
    13: "护士声：六楼三号房，门禁失控！",
    14: "王龙：你二叔，收过我的钱。",
    15: "陈迹：我爸妈没收，你也买不了我。",
    16: "王龙：你就是疯子！",
    17: "老人：这只蝉壳，真的开门了。",
    18: "李青鸟：不是你疯，门选了你。",
    19: "陈迹：门后面，是哪儿？",
    20: "母亲：孩子，往前走。",
    21: "陈迹：我回来之前，他别想逃。",
    22: "李青鸟：北俱芦洲，有人接你。",
}


VOICE_BY_SPEAKER = {
    "陈迹": ("zh-CN-YunxiNeural", "-2%", "-1Hz"),
    "王龙": ("zh-CN-YunyangNeural", "-5%", "-4Hz"),
    "李青鸟": ("zh-CN-XiaoxiaoNeural", "-3%", "+1Hz"),
    "老人": ("zh-CN-YunyangNeural", "-10%", "-8Hz"),
    "老刘": ("zh-CN-YunyangNeural", "-8%", "-5Hz"),
    "护士声": ("zh-CN-XiaoyiNeural", "+0%", "+0Hz"),
    "母亲": ("zh-CN-XiaoxiaoNeural", "-8%", "-2Hz"),
}

TTS_PATCHES = {
    shot: (
        (text.split("：", 1)[1] if "：" in text else text).replace("\n", ""),
        *VOICE_BY_SPEAKER.get(text.split("：", 1)[0], ("zh-CN-YunxiNeural", "-3%", "-1Hz")),
        620,
    )
    for shot, text in SUBTITLES.items()
    if text
}


def run(args: list[str], capture: bool = False) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(map(str, args)))
    return subprocess.run(
        args,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )


def read_url_map(path: Path, key: str) -> dict[int, str]:
    data = json.loads(path.read_text())
    out: dict[int, str] = {}
    for item in data:
        shot = int(item["shot"])
        url = item.get(key) or item.get("top") or item.get("latest")
        if url:
            out[shot] = url
    return out


def build_manifest() -> dict[int, str]:
    urls = read_url_map(JSON_REGEN2, "latest")
    urls.update({k: v for k, v in read_url_map(JSON_SHORT, "top").items() if k in {14, 16, 17}})
    urls.update({k: v for k, v in read_url_map(JSON_ULTRA, "top").items() if k in {18, 20, 22}})
    visible = read_url_map(JSON_VISIBLE, "top")
    final_0910 = read_url_map(JSON_0910, "top")
    if 9 in visible:
        urls[9] = visible[9]
    if 10 in final_0910:
        urls[10] = final_0910[10]
    missing = [i for i in range(1, 23) if i not in urls]
    if missing:
        raise RuntimeError(f"Missing shot URLs: {missing}")
    return urls


def download(url: str, shot: int) -> Path:
    name = Path(urlparse(url).path).name
    out = WORK_DIR / "raw" / f"e04_{shot:02d}_{name}"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and out.stat().st_size > 1000:
        return out
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(out, "wb") as f:
        f.write(resp.read())
    return out


async def make_tts() -> dict[int, Path]:
    tts_dir = WORK_DIR / "tts"
    tts_dir.mkdir(parents=True, exist_ok=True)
    result: dict[int, Path] = {}
    for shot, (text, voice, rate, pitch, _delay) in TTS_PATCHES.items():
        out = tts_dir / f"e04_{shot:02d}_full_redub_tts.mp3"
        communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate, pitch=pitch)
        await communicate.save(str(out))
        result[shot] = out
    return result


def process_clip(shot: int, raw: Path, tts: Path | None) -> Path:
    out = WORK_DIR / "processed" / f"e04_{shot:02d}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    vf = "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1,fps=30"
    if tts is None:
        run([
            str(FFMPEG), "-y", "-i", str(raw),
            "-vf", vf,
            "-af", "volume=0.0",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            str(out),
        ])
        return out

    delay = TTS_PATCHES[shot][4]
    filter_complex = (
        f"[0:v]{vf}[v];"
        "[0:a]volume=0.0[a0];"
        f"[1:a]adelay={delay}|{delay},volume=2.1[a1];"
        "[a0][a1]amix=inputs=2:duration=first:dropout_transition=0,alimiter=limit=0.95[a]"
    )
    run([
        str(FFMPEG), "-y",
        "-i", str(raw),
        "-i", str(tts),
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        str(out),
    ])
    return out


def concat_clips(clips: list[Path]) -> Path:
    concat_file = WORK_DIR / "concat.txt"
    concat_file.write_text("".join(f"file '{clip}'\n" for clip in clips), encoding="utf-8")
    raw_master = WORK_DIR / "e04_audio_repair_raw_concat.mp4"
    run([
        str(FFMPEG), "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-c", "copy",
        str(raw_master),
    ])
    return raw_master


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


def make_overlays() -> tuple[Path, Path]:
    title = WORK_DIR / "e04_title_overlay.png"
    tail = WORK_DIR / "e04_nalu_tail_overlay.png"
    title_img = Image.new("RGBA", (720, 1280), (0, 0, 0, 0))
    draw = ImageDraw.Draw(title_img)
    draw.rounded_rectangle((52, 210, 668, 540), radius=18, fill=(0, 0, 0, 150))
    draw_center(draw, 258, "青山", ImageFont.truetype(FONT_BOLD, 88), (255, 255, 255, 248))
    draw_center(draw, 382, "第4集：六楼门开，王龙现形", ImageFont.truetype(FONT_BOLD, 34), (238, 238, 236, 242))
    draw.line((120, 455, 600, 455), fill=(175, 205, 200, 150), width=2)
    draw_center(draw, 486, "一个被判疯的少年，把仇人逼到当场自爆。", ImageFont.truetype(FONT_REGULAR, 24), (210, 218, 216, 230))
    title_img.save(title)

    tail_img = Image.new("RGBA", (720, 1280), (0, 0, 0, 215))
    logo = Image.open(LOGO).convert("RGBA")
    logo.thumbnail((270, 152), Image.Resampling.LANCZOS)
    tail_img.paste(logo, ((720 - logo.width) // 2, 410), logo)
    draw = ImageDraw.Draw(tail_img)
    draw_center(draw, 610, "NALU MOTION", ImageFont.truetype(FONT_BOLD, 48), (255, 255, 255, 245))
    draw_center(draw, 680, "A Nalu Motion Pictures Production", ImageFont.truetype(FONT_REGULAR, 22), (205, 205, 205, 225))
    draw_center(draw, 805, "下一集：梦门之后", ImageFont.truetype(FONT_BOLD, 34), (238, 238, 238, 235))
    tail_img.save(tail)
    return title, tail


def wrap_cn(text: str, max_chars: int = 16) -> str:
    if len(text) <= max_chars:
        return text
    if "：" in text:
        speaker, line = text.split("：", 1)
        prefix = speaker + "："
        if len(prefix + line) <= max_chars:
            return prefix + line
        cut = max(7, min(max_chars - len(prefix), len(line)))
        return prefix + line[:cut] + "\n" + line[cut:]
    return text[:max_chars] + "\n" + text[max_chars:]


def apply_titles_and_subtitles(raw_master: Path) -> None:
    title, tail = make_overlays()
    duration = duration_seconds(raw_master)
    shot_len = duration / 22
    text_dir = WORK_DIR / "subtitle_text"
    text_dir.mkdir(parents=True, exist_ok=True)
    draw_filters: list[str] = []
    for shot in range(1, 23):
        text = SUBTITLES.get(shot, "")
        if not text:
            continue
        start = (shot - 1) * shot_len + 0.55
        end = min(shot * shot_len - 0.35, duration - 0.2)
        text_file = text_dir / f"subtitle_{shot:03d}.txt"
        text_file.write_text(wrap_cn(text), encoding="utf-8")
        draw_filters.append(
            "drawtext="
            "fontfile=/System/Library/Fonts/STHeiti\\ Medium.ttc:"
            f"textfile={text_file}:"
            "fontsize=20:"
            "fontcolor=white:"
            "borderw=2:"
            "bordercolor=black@0.80:"
            "box=1:"
            "boxcolor=black@0.32:"
            "boxborderw=8:"
            "line_spacing=4:"
            "x=(w-text_w)/2:"
            "y=h-126:"
            f"enable='between(t,{start:.3f},{end:.3f})'"
        )
    subtitle_chain = ",".join(draw_filters) if draw_filters else "null"
    tail_start = max(0.0, duration - 3.4)
    filter_complex = (
        "[0:v]scale=720:1280,setsar=1[base];"
        "[base][1:v]overlay=0:0:enable='between(t,0,4.4)'[vtitle];"
        f"[vtitle][2:v]overlay=0:0:enable='between(t,{tail_start:.3f},{duration:.3f})'[vover];"
        f"[vover]{subtitle_chain}[vout];"
        "[0:a]volume=1.0[aout]"
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    run([
        str(FFMPEG), "-y",
        "-i", str(raw_master),
        "-loop", "1", "-i", str(title),
        "-loop", "1", "-i", str(tail),
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
    times = [0.7, 3.0, 9.0, 32.0, 64.0, 88.0, 112.0, 136.0, 160.0, max(0.0, duration - 2.0)]
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
    sheet.save(QA_DIR / "contact_sheet_e04_audio_repair_candidate.jpg", quality=92)


def main() -> None:
    for required in [FFMPEG, LOGO, JSON_REGEN2, JSON_SHORT, JSON_ULTRA]:
        if not required.exists():
            raise FileNotFoundError(required)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest()
    (OUT_DIR / "e04_audio_repair_manifest_20260630.json").write_text(
        json.dumps({str(k): v for k, v in manifest.items()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tts_files = asyncio.run(make_tts())
    processed: list[Path] = []
    for shot in range(1, 23):
        raw = download(manifest[shot], shot)
        processed.append(process_clip(shot, raw, tts_files.get(shot)))
    raw_master = concat_clips(processed)
    apply_titles_and_subtitles(raw_master)
    extract_qa()
    print(f"FINAL={FINAL}")
    print(f"QA={QA_DIR / 'contact_sheet_e04_audio_repair_candidate.jpg'}")
    print(f"DURATION={duration_seconds(FINAL):.2f}")


if __name__ == "__main__":
    main()
