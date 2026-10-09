#!/usr/bin/env python3
"""Make the 3 s 9:16 studio end card S7 requires: $NALU_RUNTIME_ROOT/brand/NALU_MOTION_endcard_3s_9x16.mp4.

usage: make_endcard.py --runtime-root $NALU_RUNTIME_ROOT --title 青灯巷 --subtitle "第一集 · 买命信" [--font <ttf/ttc>]
Font: first existing of --font, $QINGSHAN_CJK_FONT, Noto CJK (Linux), Hiragino (macOS).
"""
import argparse
import os
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
]

ap = argparse.ArgumentParser()
ap.add_argument("--runtime-root", required=True)
ap.add_argument("--title", required=True)
ap.add_argument("--subtitle", default="")
ap.add_argument("--font", default="")
a = ap.parse_args()
font = next((f for f in [a.font, os.environ.get("QINGSHAN_CJK_FONT", ""), *CANDIDATES] if f and Path(f).is_file()), None)
if not font:
    raise SystemExit("no CJK font found; install fonts-noto-cjk or pass --font")
brand = Path(a.runtime_root).expanduser() / "brand"
brand.mkdir(parents=True, exist_ok=True)
W, H = 720, 1280
im = Image.new("RGB", (W, H), (14, 12, 10))
d = ImageDraw.Draw(im)
for text, size, y, col in ((a.title, 96, 520, (232, 196, 120)), (a.subtitle, 40, 660, (200, 190, 170)),
                           ("未完待续", 40, 740, (150, 140, 120))):
    if text:
        f = ImageFont.truetype(font, size)
        d.text(((W - d.textlength(text, font=f)) / 2, y), text, font=f, fill=col)
png = brand / "endcard_9x16.png"
im.save(png)
out = brand / "NALU_MOTION_endcard_3s_9x16.mp4"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", str(png), "-f", "lavfi", "-i",
                "anullsrc=r=48000:cl=stereo", "-t", "3", "-r", "24", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest", str(out)], check=True)
print(out)
