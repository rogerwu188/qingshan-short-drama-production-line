#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


BASE = Path("/Users/rogerwu/qingshan_short_drama")
RUN_DIR = BASE / "working_assets/e06_v2_api_cleanref_20260704"
REPAIR_DIR = BASE / "working_assets/e06_v2_api_cleanref_20260704_repair_22_27"
OUT_DIR = BASE / "exports/e06/final_package_v2_api_cleanref_20260704"
QA_DIR = BASE / "qa/e06_v2_api_cleanref_20260704/final_package"
CONFIG = BASE / "configs/e06_v2_continuity_config_20260704.json"
MANIFEST = BASE / "configs/e06_asset_binding_manifest_20260704.json"
LOGO = BASE / "libraries/brand/nalu_motion_cat_logo_v1.png"
FINAL = OUT_DIR / "qingshan_E06_final_v2_api_cleanref_titled_nalu_20260704.mp4"
RAW_MASTER = OUT_DIR / "qingshan_E06_v2_api_cleanref_raw_concat_20260704.mp4"
TITLE_CARD = OUT_DIR / "qingshan_E06_v2_title_card_20260704.mp4"
TAIL_CARD = OUT_DIR / "qingshan_E06_v2_nalu_tail_20260704.mp4"
CONCAT_LIST = OUT_DIR / "concat_e06_v2.txt"
NORMALIZED_DIR = OUT_DIR / "normalized_segments"

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


def ffmpeg() -> str:
    proc = run([str(BASE / "tools/find_ffmpeg.sh"), str(BASE)], capture=True)
    return proc.stdout.strip().splitlines()[-1]


def probe_text(ff: str, path: Path) -> str:
    proc = subprocess.run(
        [ff, "-hide_banner", "-i", str(path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return proc.stdout or ""


def duration_seconds(ff: str, path: Path) -> float:
    match = re.search(r"Duration: (\d+):(\d+):([\d.]+)", probe_text(ff, path))
    if not match:
        raise RuntimeError(f"Cannot parse duration: {path}")
    h, m, s = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> int:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0]


def draw_center(draw: ImageDraw.ImageDraw, y: int, text: str, font: ImageFont.FreeTypeFont, fill) -> None:
    for offset, line in enumerate(text.split("\n")):
        draw.text(((720 - text_width(draw, line, font)) / 2, y + offset * (font.size + 16)), line, font=font, fill=fill)


def make_card_image(kind: str, path: Path) -> None:
    img = Image.new("RGB", (720, 1280), (5, 7, 10))
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    if kind == "title":
        draw.rounded_rectangle((60, 260, 660, 790), radius=10, fill=(0, 0, 0, 170))
        draw_center(draw, 338, "青山", ImageFont.truetype(FONT_BOLD, 90), (255, 255, 255, 245))
        draw_center(draw, 472, "第6集：醒来就是灭门现场", ImageFont.truetype(FONT_BOLD, 34), (236, 236, 232, 240))
        draw.line((130, 565, 590, 565), fill=(183, 210, 201, 155), width=2)
        draw_center(draw, 610, "一刻钟内，他必须用一张空白宣纸活下去。", ImageFont.truetype(FONT_REGULAR, 25), (220, 226, 224, 230))
        draw_center(draw, 720, "NALU MOTION 出品", ImageFont.truetype(FONT_REGULAR, 22), (205, 205, 205, 215))
    else:
        draw.rectangle((0, 0, 720, 1280), fill=(0, 0, 0, 218))
        logo = Image.open(LOGO).convert("RGBA")
        logo.thumbnail((280, 160), Image.Resampling.LANCZOS)
        layer.alpha_composite(logo, ((720 - logo.width) // 2, 382))
        draw_center(draw, 610, "NALU MOTION", ImageFont.truetype(FONT_BOLD, 48), (255, 255, 255, 245))
        draw_center(draw, 678, "A Nalu Motion Pictures Production", ImageFont.truetype(FONT_REGULAR, 22), (205, 205, 205, 225))
        draw_center(draw, 804, "下一集：同僚盯上我", ImageFont.truetype(FONT_BOLD, 34), (238, 238, 238, 235))
    Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB").save(path, quality=95)


def make_video_card(ff: str, image_path: Path, out_path: Path, duration: float) -> None:
    silent = "anullsrc=channel_layout=stereo:sample_rate=48000"
    run([
        ff, "-y",
        "-loop", "1", "-framerate", "30", "-i", str(image_path),
        "-f", "lavfi", "-i", silent,
        "-t", f"{duration:.3f}",
        "-vf", "scale=720:1280,format=yuv420p",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
        "-movflags", "+faststart",
        str(out_path),
    ])


def shot_paths() -> list[Path]:
    paths = []
    for i in range(1, 28):
        repaired = REPAIR_DIR / f"videos/shot_{i:02d}/result_01.mp4"
        path = repaired if repaired.exists() else RUN_DIR / f"videos/shot_{i:02d}/result_01.mp4"
        if not path.exists():
            raise FileNotFoundError(path)
        paths.append(path)
    return paths


def make_continuity_config(ff: str, shots: list[Path]) -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    titles = [
        "周成义暴起", "一刻钟开始", "翻找宣纸", "线索不在书房", "冲过夜院",
        "银针倒计时", "推开厨房", "打开白粉陶罐", "陈迹察觉不对", "两罐白粉",
        "为什么两罐盐", "揉搓粉末", "明矾追问", "醋坛判断", "醋擦宣纸",
        "周成义强撑", "红字显现", "找到了", "周成义二次暴起", "皎兔制敌",
        "冰流入袖", "你们看不见", "黑衣汉子出门", "宣纸店误导", "碎瓷片底牌",
        "真正线索", "皎兔收钩"
    ]
    scene_map = {
        "01": ("SCENE-古装-周府书房-软剑暴起", "ROOM-周府书房", "ZONE-书桌到门口动线"),
        "02": ("SCENE-古装-周府夜院-梧桐书房门口", "ROOM-周府夜院", "ZONE-梧桐树到书房门"),
        "03": ("SCENE-古装-周府书房-书桌宣纸区", "ROOM-周府书房", "ZONE-红木书桌与宣纸"),
        "04": ("SCENE-古装-周府夜院-书房到厨房动线", "ROOM-周府夜院", "ZONE-书房门到厨房门"),
        "05": ("SCENE-古装-周府夜院-红漆门出马", "ROOM-周府夜院", "ZONE-书房门到厨房门"),
        "06": ("SCENE-古装-周府夜院-梧桐树下", "ROOM-周府夜院", "ZONE-梧桐树下"),
        "07": ("SCENE-古装-周府厨房-灶台陶罐区", "ROOM-周府厨房", "ZONE-青砖灶台与陶罐"),
        "08": ("SCENE-古装-周府厨房-灶台陶罐区", "ROOM-周府厨房", "ZONE-青砖灶台与陶罐"),
        "09": ("SCENE-古装-周府书房-药罐上桌", "ROOM-周府书房", "ZONE-红木书桌药罐区"),
        "10": ("SCENE-古装-周府书房-药罐上桌", "ROOM-周府书房", "ZONE-红木书桌药罐区"),
        "11": ("SCENE-古装-周府书房-药罐上桌", "ROOM-周府书房", "ZONE-红木书桌药罐区"),
        "12": ("SCENE-古装-周府书房-药罐上桌", "ROOM-周府书房", "ZONE-红木书桌药罐区"),
        "13": ("SCENE-古装-周府书房-药罐审问", "ROOM-周府书房", "ZONE-红木书桌药罐区"),
        "14": ("SCENE-古装-周府书房-书桌宣纸区", "ROOM-周府书房", "ZONE-红木书桌宣纸醋坛"),
        "15": ("SCENE-古装-周府书房-书桌宣纸区", "ROOM-周府书房", "ZONE-红木书桌宣纸醋坛"),
        "16": ("SCENE-古装-周府书房-周成义站位", "ROOM-周府书房", "ZONE-书桌对面周成义站位"),
        "17": ("SCENE-古装-周府书房-红字宣纸", "ROOM-周府书房", "ZONE-红木书桌宣纸醋坛"),
        "18": ("SCENE-古装-周府书房-红字宣纸", "ROOM-周府书房", "ZONE-红木书桌宣纸醋坛"),
        "19": ("SCENE-古装-周府书房-软剑暴起", "ROOM-周府书房", "ZONE-书桌到门口动线"),
        "20": ("SCENE-古装-周府书房-软剑被制", "ROOM-周府书房", "ZONE-书桌到门口动线"),
        "21": ("SCENE-古装-周府书房-冰流异象", "ROOM-周府书房", "ZONE-书桌到陈迹袖口"),
        "22": ("SCENE-古装-周府书房-冰流异象", "ROOM-周府书房", "ZONE-书桌到陈迹袖口"),
        "23": ("SCENE-古装-周府夜院-红漆门出马", "ROOM-周府夜院", "ZONE-红漆大门到院外"),
        "24": ("SCENE-古装-周府书房-红字宣纸", "ROOM-周府书房", "ZONE-红木书桌宣纸醋坛"),
        "25": ("SCENE-古装-周府书房-碎瓷片交易", "ROOM-周府书房", "ZONE-红木书桌到陈迹手腕"),
        "26": ("SCENE-古装-周府书房-碎瓷片交易", "ROOM-周府书房", "ZONE-红木书桌到陈迹手腕"),
        "27": ("SCENE-古装-周府书房-碎瓷片交易", "ROOM-周府书房", "ZONE-红木书桌到陈迹手腕"),
    }
    b_char_extras = {
        "01": ["CHAR-周成义-古装"],
        "16": ["CHAR-周成义-古装"],
        "19": ["CHAR-周成义-古装"],
        "20": ["CHAR-周成义-古装"],
        "23": ["CHAR-黑衣汉子"],
    }
    exact_characters = {
        "01": ["CHAR-陈迹-古装", "CHAR-云羊-古装", "CHAR-皎兔-古装", "CHAR-周成义-古装"],
        "02": ["CHAR-陈迹-古装", "CHAR-云羊-古装", "CHAR-皎兔-古装"],
        "03": ["CHAR-陈迹-古装"],
        "04": ["CHAR-陈迹-古装"],
        "05": ["CHAR-陈迹-古装"],
        "06": ["CHAR-陈迹-古装"],
        "07": ["CHAR-陈迹-古装"],
        "08": [],
        "09": ["CHAR-陈迹-古装", "CHAR-云羊-古装"],
        "10": ["CHAR-云羊-古装"],
        "11": ["CHAR-陈迹-古装"],
        "12": ["CHAR-陈迹-古装"],
        "13": ["CHAR-周成义-古装"],
        "14": ["CHAR-陈迹-古装", "CHAR-云羊-古装"],
        "15": ["CHAR-周成义-古装"],
        "16": ["CHAR-陈迹-古装", "CHAR-皎兔-古装", "CHAR-周成义-古装"],
        "17": [],
        "18": [],
        "19": ["CHAR-陈迹-古装", "CHAR-云羊-古装", "CHAR-周成义-古装"],
        "20": ["CHAR-陈迹-古装", "CHAR-云羊-古装", "CHAR-皎兔-古装", "CHAR-周成义-古装"],
        "21": ["CHAR-陈迹-古装"],
        "22": ["CHAR-陈迹-古装"],
        "23": ["CHAR-云羊-古装", "CHAR-黑衣汉子"],
        "24": ["CHAR-陈迹-古装", "CHAR-云羊-古装"],
        "25": ["CHAR-陈迹-古装", "CHAR-云羊-古装"],
        "26": ["CHAR-陈迹-古装", "CHAR-云羊-古装", "CHAR-皎兔-古装"],
        "27": ["CHAR-皎兔-古装"],
    }
    starts = []
    current = 3.4
    for path in shots:
        starts.append(current)
        current += duration_seconds(ff, path)
    config_shots = []
    for idx, (path, start) in enumerate(zip(shots, starts), start=1):
        shot_id = f"{idx:02d}"
        scene_id, room_id, zone_id = scene_map[shot_id]
        shot_binding = (manifest.get("shot_bindings") or {}).get(shot_id) or {}
        allowed_for_preflight = set((shot_binding.get("characters") or {}).keys())
        characters = [char_id for char_id in exact_characters[shot_id] if char_id in allowed_for_preflight or char_id.startswith("CHAR-周成义") or char_id == "CHAR-黑衣汉子"]
        for char_id in b_char_extras.get(shot_id, []):
            if char_id not in characters:
                characters.append(char_id)
        config_shots.append({
            "shot_id": shot_id,
            "start": round(start, 3),
            "end": round(start + duration_seconds(ff, path), 3),
            "title": titles[idx - 1],
            "scene_id": scene_id,
            "scene_group_id": "SCENEGROUP-E06-周府",
            "room_id": room_id,
            "zone_id": zone_id,
            "characters": characters,
            "props": ["PROP-宣纸", "PROP-银针", "PROP-两罐白粉", "PROP-醋坛", "PROP-碎瓷片"],
            "dialogue": "",
        })
    CONFIG.write_text(json.dumps({
        "episode": "qingshan_E06_v2_api_cleanref",
        "thresholds": {
            "scene_warn": 0.50,
            "scene_fail": 0.72,
            "character_warn": 0.56,
            "character_fail": 0.76,
            "prop_warn": 0.56,
            "prop_fail": 0.76,
        },
        "shots": config_shots,
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def concat_all(ff: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
    title_png = OUT_DIR / "title.png"
    tail_png = OUT_DIR / "tail.png"
    make_card_image("title", title_png)
    make_card_image("tail", tail_png)
    make_video_card(ff, title_png, TITLE_CARD, 3.4)
    make_video_card(ff, tail_png, TAIL_CARD, 3.4)

    source_segments = [TITLE_CARD] + shot_paths() + [TAIL_CARD]
    normalized_segments: list[Path] = []
    for idx, src in enumerate(source_segments):
        dst = NORMALIZED_DIR / f"seg_{idx:02d}_{src.stem}.mp4"
        run([
            ff, "-y",
            "-fflags", "+genpts",
            "-i", str(src),
            "-vf", "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1,fps=30,setpts=PTS-STARTPTS,format=yuv420p",
            "-af", "aresample=48000,asetpts=PTS-STARTPTS,volume=1.0",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-movflags", "+faststart",
            str(dst),
        ])
        normalized_segments.append(dst)

    lines = [f"file '{path}'\n" for path in normalized_segments]
    CONCAT_LIST.write_text("".join(lines), encoding="utf-8")
    run([
        ff, "-y",
        "-fflags", "+genpts",
        "-f", "concat", "-safe", "0", "-i", str(CONCAT_LIST),
        "-vf", "setpts=PTS-STARTPTS,fps=30,format=yuv420p",
        "-af", "aresample=48000,asetpts=PTS-STARTPTS,volume=1.0",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart",
        str(RAW_MASTER),
    ])
    RAW_MASTER.replace(FINAL)


def extract_qa(ff: str) -> None:
    QA_DIR.mkdir(parents=True, exist_ok=True)
    duration = duration_seconds(ff, FINAL)
    times = [0.7, 3.8, 8.0, 16.0, 28.0, 40.0, 52.0, 64.0, 76.0, 88.0, 100.0, 112.0]
    times = [t for t in times if t < duration - 0.5] + [max(0.0, duration - 1.2)]
    frames = []
    for idx, t in enumerate(times):
        out = QA_DIR / f"frame_{idx:02d}_{int(t):03d}s.jpg"
        run([ff, "-y", "-i", str(FINAL), "-ss", f"{t:.2f}", "-frames:v", "1", "-update", "1", "-q:v", "2", str(out)])
        frames.append(out)
    font = ImageFont.truetype(FONT_REGULAR, 14)
    thumbs = []
    for frame in frames:
        img = Image.open(frame).convert("RGB")
        img.thumbnail((180, 320), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (180, 346), (14, 14, 14))
        canvas.paste(img, ((180 - img.width) // 2, 0))
        ImageDraw.Draw(canvas).text((6, 322), frame.name, font=font, fill=(230, 230, 230))
        thumbs.append(canvas)
    cols = 4
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 180, rows * 346), (18, 18, 18))
    for i, thumb in enumerate(thumbs):
        sheet.paste(thumb, ((i % cols) * 180, (i // cols) * 346))
    sheet.save(QA_DIR / "contact_sheet_e06_v2_final.jpg", quality=92)
    (QA_DIR / "ffmpeg_probe_e06_v2_final.txt").write_text(probe_text(ff, FINAL), encoding="utf-8")
    silence = subprocess.run([ff, "-hide_banner", "-i", str(FINAL), "-af", "silencedetect=n=-35dB:d=1.5", "-f", "null", "-"], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (QA_DIR / "silencedetect_e06_v2_final.txt").write_text(silence.stdout or "", encoding="utf-8")


def main() -> None:
    ff = ffmpeg()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    shots = shot_paths()
    make_continuity_config(ff, shots)
    concat_all(ff)
    extract_qa(ff)
    print(f"FINAL={FINAL}")
    print(f"CONFIG={CONFIG}")
    print(f"MANIFEST={MANIFEST}")
    print(f"QA={QA_DIR}")
    print(f"DURATION={duration_seconds(ff, FINAL):.2f}")


if __name__ == "__main__":
    main()
