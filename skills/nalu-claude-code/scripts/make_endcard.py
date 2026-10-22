#!/usr/bin/env python3
"""Make the 3 s 9:16 studio end card S7 requires: $NALU_RUNTIME_ROOT/brand/NALU_MOTION_endcard_3s_9x16.mp4.

usage: make_endcard.py --runtime-root $NALU_RUNTIME_ROOT --title <剧名> --subtitle "第一集 · <集名>"
                       [--language zh|en] [--font <ttf/ttc>]
--language zh (default): draws 未完待续; font = first existing of --font, $QINGSHAN_CJK_FONT, Noto CJK (Linux),
  Hiragino (macOS); a CJK font is required.
--language en: draws TO BE CONTINUED; font = first existing of --font, $QINGSHAN_LATIN_FONT, DejaVu Sans,
  Liberation Sans, Noto Sans, Arial/Helvetica (macOS), else Pillow's built-in default font. Never needs CJK.
Every line is auto-fitted (font shrunk, subtitle/title wrapped to 2 lines if needed) to <= 88% of the frame width.
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
LATIN_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/liberation-sans/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/noto/NotoSans-Regular.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
]
TAGLINE = {"zh": "未完待续", "en": "TO BE CONTINUED"}
W, H = 720, 1280
MAX_TEXT_WIDTH = int(W * 0.88)


def resolve_font(language, explicit=""):
    if language == "en":
        pool = [explicit, os.environ.get("QINGSHAN_LATIN_FONT", ""), os.environ.get("NALU_LATIN_FONT", ""),
                *LATIN_CANDIDATES]
        return next((f for f in pool if f and Path(f).is_file()), None)  # None = Pillow default font
    pool = [explicit, os.environ.get("QINGSHAN_CJK_FONT", ""), *CANDIDATES]
    font = next((f for f in pool if f and Path(f).is_file()), None)
    if not font:
        raise SystemExit("no CJK font found; install fonts-noto-cjk or pass --font")
    return font


def load_font(font, size):
    if font:
        return ImageFont.truetype(font, size)
    return ImageFont.load_default(size=size)


def _split_two(text, language):
    """Split one line into two balanced halves (prefer ' · ', then spaces for en, else characters)."""
    for sep in (" · ", "·", "｜", " | "):
        if sep in text:
            head, tail = text.split(sep, 1)
            return [head.strip(), tail.strip()]
    words = text.split(" ")
    if len(words) > 1:
        best = min(range(1, len(words)), key=lambda i: abs(len(" ".join(words[:i])) - len(" ".join(words[i:]))))
        return [" ".join(words[:best]), " ".join(words[best:])]
    mid = (len(text) + 1) // 2
    return [text[:mid], text[mid:]]


def fit_lines(draw, text, font, size, min_size, language, max_width=MAX_TEXT_WIDTH):
    """Return (font_obj, size, lines) whose every line fits max_width."""
    def widest(lines, f):
        return max(draw.textlength(line, font=f) for line in lines)

    for size_try in range(size, min_size - 1, -2):
        f = load_font(font, size_try)
        if widest([text], f) <= max_width:
            return f, size_try, [text]
    lines = _split_two(text, language)
    for size_try in range(size, 7, -2):
        f = load_font(font, size_try)
        if widest(lines, f) <= max_width:
            return f, size_try, lines
    f = load_font(font, 8)
    return f, 8, lines


def render_png(title, subtitle, language, font, png):
    im = Image.new("RGB", (W, H), (14, 12, 10))
    d = ImageDraw.Draw(im)
    blocks = ((title, 96, 48, 520, (232, 196, 120)), (subtitle, 40, 28, 660, (200, 190, 170)),
              (TAGLINE[language], 40, 28, 740, (150, 140, 120)))
    shift = 0
    for text, size, min_size, y, col in blocks:
        if not text:
            continue
        f, size_used, lines = fit_lines(d, text, font, size, min_size, language)
        y += shift
        line_h = int(size_used * 1.25)
        for i, line in enumerate(lines):
            d.text(((W - d.textlength(line, font=f)) / 2, y + i * line_h), line, font=f, fill=col)
        shift += (len(lines) - 1) * line_h
    im.save(png)
    return png


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--runtime-root", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--subtitle", default="")
    ap.add_argument("--language", choices=["zh", "en"], default="zh")
    ap.add_argument("--font", default="")
    a = ap.parse_args(argv)
    font = resolve_font(a.language, a.font)
    brand = Path(a.runtime_root).expanduser() / "brand"
    brand.mkdir(parents=True, exist_ok=True)
    png = render_png(a.title, a.subtitle, a.language, font, brand / "endcard_9x16.png")
    out = brand / "NALU_MOTION_endcard_3s_9x16.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", str(png), "-f", "lavfi", "-i",
                    "anullsrc=r=48000:cl=stereo", "-t", "3", "-r", "24", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(out)], check=True)
    print(out)


if __name__ == "__main__":
    main()
