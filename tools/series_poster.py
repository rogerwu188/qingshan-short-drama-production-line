#!/usr/bin/env python3
"""Per-series poster cover: AI key art (no text) + a programmatically typeset title (owner-approved 2026-11-13).

Why
---
X2C received a frame grabbed 1.5 s into each final cut (often a burned subtitle, rarely the lead) and the
fleet dashboard a still from the latest cut.  A series now gets ONE poster:

1. **Key art (paid, about 1-2 credits, once per series).**  One HopsAPI ``gpt-image-2`` Img2Img, 9:16, with the
   lead's (and the second lead's) S3 identity plates / headshots as references.  The prompt carries the
   series' genre, style and synopsis, asks for a cinematic short-drama poster with the lead's face clearly
   visible, forbids any text / letters / logos / watermarks and reserves a clean, darkening band (bottom
   ~30 %) for the title.  It goes through the same durable discipline as every other image: references are
   uploaded before the intent, the intent is written before the single create POST (never retried), the
   transaction lives in the episode's image store (``workflow/tasks/giggle_submit_transactions/<EP>/``) so
   the budget ledger's HopsAPI leg counts it, a lost response is never resent, and an uncharged failure
   gets exactly one redo (at the probe-verified 1152x2048).  Result: ``<runtime>/series/cover/poster_art.png``
   + ``poster_manifest.json`` (prompt sha, references, cost, task id, transaction).
2. **Title (free, exact text).**  Pillow sets the brief ``title`` with a bundled OFL font chosen by genre /
   language (``assets/fonts/poster/``), with stroke, shadow, gradient fill and glow, auto-fitted (CJK wraps by
   character, Latin by word) into the reserved band, which is darkened until the text clears a 4.5:1
   contrast ratio.  The text must not cover a detected face (InsightFace detector, when installed) and must
   read back through RapidOCR (when installed); otherwise the other band (top) is tried, then a plain bottom
   bar.  Outputs ``cover.jpg`` (full size, <= 5 MB, X2C) and ``cover_thumb.jpg`` (360 px, <= 150 KB, fleet
   dashboard) + ``cover.json``.

When: ``codex_production.publish_next`` calls :func:`ensure_series_cover` right before every X2C publish, so
a new series gets its art before its first publish and a running series at its next episode.  The paid
step runs only when the runtime ``qingshan.json`` has ``generation.paid_requests_enabled`` true, the image
provider is HopsAPI and a HopsAPI key is available (switch off with ``NALU_SERIES_POSTER_ART=off`` or
``generation.series_poster_art: false``).  Any failure falls back to the frame grab; nothing here ever
blocks a publish.  Operators may drop their own ``poster_art.png`` into the cover folder: it is adopted
(no paid call) and typeset.

The HopsAPI key is never printed, logged or written.
"""
from __future__ import annotations

import argparse
import contextlib
import difflib
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import time
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
FONT_DIR = ROOT / "assets" / "fonts" / "poster"

COVER_DIRNAME = Path("series") / "cover"
ART_NAME = "poster_art.png"
ART_MANIFEST = "poster_manifest.json"
COVER_NAME = "cover.jpg"
THUMB_NAME = "cover_thumb.jpg"
COVER_META = "cover.json"
RENDER_VERSION = "series_poster.v1"

COVER_MAX_BYTES = 5 * 1024 * 1024
THUMB_WIDTH = 360
THUMB_MAX_BYTES = 150_000

TASK_KEY = "SERIES-POSTER-ART"
IMAGE_STORE_DIRNAME = "giggle_submit_transactions"
MAX_ATTEMPTS = 2  # the first attempt + the existing one-redo rule
#: probe-verified 1152x2048 (about 1 credit; line owner 2026-11-13 chose it over 1440x2560, about 1.9).
#: Override: env NALU_POSTER_ART_SIZE / generation.series_poster_art_size.
DEFAULT_ART_SIZE = "1152x2048"
REDO_ART_SIZE = "1152x2048"
ART_QUALITY = "high"
PROBE_PIXELS = 1152 * 2048
POLL_SECONDS = 10
DEFAULT_WAIT_SECONDS = 240

OCR_MIN_SIMILARITY = 0.75
CONTRAST_MIN = 4.5


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def atomic_json(path: Path, payload: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def cover_dir(runtime: Path) -> Path:
    return Path(runtime) / COVER_DIRNAME


# --------------------------------------------------------------------------- #
# series identity (title / key / language / genre) from the production brief
# --------------------------------------------------------------------------- #
def _lang_code(value: Any) -> str:
    return str(value or "zh").strip().lower().split("-")[0] or "zh"


def series_key(brief: dict[str, Any]) -> str:
    """The X2C series key publish_x2c_matrix derives (brief series_key, else '<title slug>-<lang>')."""
    if brief.get("series_key"):
        return str(brief["series_key"]).strip()[:150]
    title = str(brief.get("title") or "").strip()[:100]
    lang = _lang_code(brief.get("genre_lang") or brief.get("dialogue_language") or "zh")
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:120]
    base = slug or "series-" + hashlib.sha256(title.encode("utf-8")).hexdigest()[:12]
    return f"{base}-{lang}"


def series_identity(brief: dict[str, Any]) -> dict[str, Any]:
    title = str(brief.get("title") or "").strip()
    language = _lang_code(brief.get("dialogue_language") or brief.get("genre_lang") or "zh")
    return {"title": title, "series_key": series_key(brief) if title else "", "language": language,
            "genre": str(brief.get("genre") or "").strip(), "style": str(brief.get("style") or "").strip(),
            "synopsis": str(brief.get("synopsis") or "").strip(),
            "tagline": str(brief.get("poster_tagline") or brief.get("tagline") or "").strip(),
            "band": str(brief.get("poster_title_band") or "bottom").strip().lower()}


# --------------------------------------------------------------------------- #
# genre / language -> title style
# --------------------------------------------------------------------------- #
#: checked in this order against "<genre> <style>" (lower-cased); first match wins, default "elegant"
STYLE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("brush", ("仙侠", "古装", "古代", "宫廷", "宫斗", "历史", "武侠", "玄幻", "修仙", "王朝", "朝堂", "江湖", "民国",
               "xianxia", "wuxia", "palace", "historical", "dynasty", "imperial", "medieval", "fantasy",
               "werewolf", "lycan", "vampire", "kingdom")),
    ("hard", ("悬疑", "惊悚", "恐怖", "复仇", "犯罪", "刑侦", "末世", "科幻", "谍", "suspense", "thriller", "horror",
              "revenge", "crime", "mystery", "sci-fi", "scifi", "apocalypse", "action", "detective")),
    ("elegant", ("甜宠", "霸总", "言情", "恋爱", "婚", "爱情", "总裁", "romance", "ceo", "sweet", "love", "billionaire",
                 "marriage", "bride")),
)
STYLE_DEFAULT = "elegant"

#: (font file, variable-font weight or None); every chain ends in the plain fallback for its language
FONTS: dict[str, dict[str, list[tuple[str, int | None]]]] = {
    "zh": {"brush": [("MaShanZheng-Regular-GB2312L1.ttf", None)],
           "elegant": [("ZCOOLXiaoWei-Regular-GB2312L1.ttf", None)],
           "hard": [("ZCOOLQingKeHuangYou-Regular-GB2312L1.ttf", None)],
           "plain": [("NotoSansSC-Bold-GB2312.ttf", None)]},
    "en": {"brush": [("Cinzel-wght.ttf", 700)],
           "elegant": [("PlayfairDisplay-wght.ttf", 700)],
           "hard": [("BebasNeue-Regular.ttf", None)],
           "plain": [("PlayfairDisplay-wght.ttf", 800)]},
}
#: colours: fill gradient top -> bottom, stroke, glow (None = no glow)
PALETTES: dict[str, dict[str, Any]] = {
    "brush": {"fill": ((255, 243, 196), (224, 168, 74)), "stroke": (43, 11, 5), "glow": (190, 60, 30)},
    "elegant": {"fill": ((255, 255, 255), (255, 206, 222)), "stroke": (74, 21, 48), "glow": (255, 128, 176)},
    "hard": {"fill": ((255, 255, 255), (214, 214, 214)), "stroke": (0, 0, 0), "glow": (196, 0, 0)},
    "plain": {"fill": ((255, 255, 255), (255, 255, 255)), "stroke": (0, 0, 0), "glow": None},
}
UPPERCASE_EN = {"brush", "hard"}


def style_for(genre: str = "", style_text: str = "", language: str = "zh") -> dict[str, Any]:
    """{slot, language, fonts, palette, uppercase} for the series' genre + style + language."""
    lang = "en" if _lang_code(language) == "en" else "zh"
    haystack = f"{genre} {style_text}".lower()
    slot = STYLE_DEFAULT
    for name, words in STYLE_RULES:
        if any(word in haystack for word in words):
            slot = name
            break
    return {"slot": slot, "language": lang, "fonts": list(FONTS[lang][slot]), "palette": PALETTES[slot],
            "uppercase": lang == "en" and slot in UPPERCASE_EN}


def _system_cjk_fonts() -> list[tuple[str, int | None]]:
    out: list[tuple[str, int | None]] = []
    for name in ("QINGSHAN_CJK_FONT", "NALU_CJK_FONT"):
        if os.environ.get(name):
            out.append((os.environ[name], None))
    for path in ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                 "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc", "/System/Library/Fonts/PingFang.ttc",
                 "/System/Library/Fonts/STHeiti Medium.ttc", "/Library/Fonts/Arial Unicode.ttf"):
        if Path(path).is_file():
            out.append((path, None))
    return out


def _font_path(spec: tuple[str, int | None]) -> Path:
    path = Path(spec[0])
    return path if path.is_absolute() else FONT_DIR / path


def load_font(spec: tuple[str, int | None], size: int):
    from PIL import ImageFont  # noqa: PLC0415
    font = ImageFont.truetype(str(_font_path(spec)), max(1, int(size)))
    if spec[1]:
        try:
            font.set_variation_by_axes([spec[1]])
        except (OSError, AttributeError, ValueError):
            pass
    return font


_COVERAGE: dict[tuple[str, str], bool] = {}


def font_covers(spec: tuple[str, int | None], text: str) -> bool:
    """True when every non-space character has a real glyph (its bitmap differs from .notdef)."""
    path = str(_font_path(spec))
    if not Path(path).is_file():
        return False
    font = load_font(spec, 48)
    notdef = font.getmask(chr(0x10FFFD))
    blank = (bytes(notdef), notdef.size)
    for ch in text:
        if ch.isspace():
            continue
        key = (path, ch)
        if key not in _COVERAGE:
            mask = font.getmask(ch)
            _COVERAGE[key] = (bytes(mask), mask.size) != blank and mask.getbbox() is not None
        if not _COVERAGE[key]:
            return False
    return True


def pick_font(style: dict[str, Any], text: str, *, plain: bool = False) -> tuple[str, int | None]:
    """The first font in the chain (style -> bundled plain -> host CJK) that covers every character."""
    lang = style["language"]
    chain = ([] if plain else list(style["fonts"])) + list(FONTS[lang]["plain"])
    if lang == "en":
        chain += list(FONTS["zh"]["plain"])  # an English title with CJK characters
    chain += _system_cjk_fonts()
    for spec in chain:
        if font_covers(spec, text):
            return spec
    raise RuntimeError(f"NO_FONT_COVERS_TITLE:{text!r}")


# --------------------------------------------------------------------------- #
# layout: wrap + fit
# --------------------------------------------------------------------------- #
_CJK = re.compile(r"[　-〿㐀-鿿豈-﫿＀-￯]")
_BREAK_AFTER = set("·•:：,，、!！?？;；—-")


def is_cjk_text(text: str) -> bool:
    return bool(_CJK.search(text))


def _tokens(text: str) -> tuple[list[str], str]:
    """(units to wrap on, joiner): CJK by character, Latin by word."""
    if is_cjk_text(text):
        return [ch for ch in text if not ch.isspace()], ""
    return text.split(), " "


def candidate_splits(text: str, max_lines: int) -> list[list[str]]:
    units, joiner = _tokens(text)
    n = len(units)
    out: list[list[str]] = [[joiner.join(units).strip()]]
    if n >= 2 and max_lines >= 2:
        for i in range(1, n):
            out.append([joiner.join(units[:i]).strip(), joiner.join(units[i:]).strip()])
    if n >= 3 and max_lines >= 3:
        for i in range(1, n - 1):
            for j in range(i + 1, n):
                out.append([joiner.join(units[:i]).strip(), joiner.join(units[i:j]).strip(),
                            joiner.join(units[j:]).strip()])
    return [lines for lines in out if all(lines)]


def _split_penalty(lines: list[str]) -> float:
    """Prefer breaks after punctuation, avoid a lone character / word on a line."""
    penalty = 0.0
    for line in lines[:-1]:
        if line[-1] in _BREAK_AFTER:
            penalty -= 0.15
    for line in lines:
        units, _ = _tokens(line)
        if len(units) == 1 and len(lines) > 1:
            penalty += 0.35
    return penalty


def fit_title(text: str, spec: tuple[str, int | None], *, max_width: float, max_height: float,
              start_size: int, min_size: int, max_lines: int = 3, line_gap: float = 0.12) -> dict[str, Any]:
    """Choose the wrap and the font size: the largest size whose lines fit ``max_width`` and whose block fits
    ``max_height`` (fewer lines preferred when nearly as large).  ``fits`` False when even ``min_size`` does
    not fit (the caller then moves on to another placement)."""
    probe = 100
    font = load_font(spec, probe)
    ascent, descent = font.getmetrics()
    line_h = (ascent + descent) / probe
    best: dict[str, Any] | None = None
    for lines in candidate_splits(text, max_lines):
        widest = max(font.getlength(line) for line in lines) / probe
        if widest <= 0:
            continue
        rows = len(lines)
        block_h = rows * line_h + (rows - 1) * line_gap * line_h
        size = min(start_size, max_width / widest, max_height / block_h)
        score = size * (1 - 0.10 * (rows - 1)) - _split_penalty(lines) * size * 0.25
        if best is None or score > best["score"]:
            best = {"lines": lines, "size": int(size), "score": score}
    if best is None:
        return {"fits": False, "lines": [text], "size": min_size, "reason": "NO_SPLIT"}
    size = max(min_size, best["size"])
    # confirm with the real font at the chosen size (hinting makes widths non-linear)
    while size > min_size:
        real = load_font(spec, size)
        if max(real.getlength(line) for line in best["lines"]) <= max_width:
            break
        size -= 1
    real = load_font(spec, size)
    widest = max(real.getlength(line) for line in best["lines"])
    asc, desc = real.getmetrics()
    block_h = len(best["lines"]) * (asc + desc) + (len(best["lines"]) - 1) * line_gap * (asc + desc)
    fits = widest <= max_width + 1 and block_h <= max_height + 1 and best["size"] >= min_size
    return {"fits": fits, "lines": best["lines"], "size": size, "line_height": asc + desc,
            "line_gap": int(line_gap * (asc + desc)), "block_width": widest, "block_height": block_h}


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #
def _luminance(rgb: tuple[float, float, float]) -> float:
    def channel(c: float) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_ratio(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _mean_rgb(image, box: tuple[int, int, int, int]) -> tuple[float, float, float]:
    from PIL import ImageStat  # noqa: PLC0415
    region = image.crop(box).convert("RGB")
    return tuple(ImageStat.Stat(region).mean[:3])  # type: ignore[return-value]


def _band_box(width: int, height: int, band: str, frac: float) -> tuple[int, int, int, int]:
    band_h = int(height * frac)
    return (0, height - band_h, width, height) if band == "bottom" else (0, 0, width, band_h)


def darken_band(image, band: str, frac: float, strength: float):
    """A gradient that fades in toward the band's outer edge (bottom band: darker toward the bottom)."""
    from PIL import Image  # noqa: PLC0415
    width, height = image.size
    band_h = int(height * frac)
    ramp = int(height * 0.10)
    mask = Image.new("L", (1, height), 0)
    for y in range(height):
        if band == "bottom":
            start = height - band_h - ramp
            t = 0.0 if y < start else min(1.0, (y - start) / (ramp + band_h * 0.35))
        else:
            end = band_h + ramp
            t = 0.0 if y > end else min(1.0, (end - y) / (ramp + band_h * 0.35))
        mask.putpixel((0, y), int(255 * strength * t))
    mask = mask.resize((width, height))
    black = Image.new("RGB", (width, height), (0, 0, 0))
    return Image.composite(black, image.convert("RGB"), mask)


def _gradient(size: tuple[int, int], top: tuple[int, int, int], bottom: tuple[int, int, int]):
    from PIL import Image  # noqa: PLC0415
    width, height = size
    column = Image.new("RGB", (1, max(1, height)))
    for y in range(max(1, height)):
        t = y / max(1, height - 1)
        column.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return column.resize((width, max(1, height)))


def draw_text_block(canvas, lines: list[str], spec: tuple[str, int | None], size: int, *, center_x: float,
                    top_y: float, palette: dict[str, Any], line_gap: int, effects: bool = True,
                    tag: str = "", tag_spec: tuple[str, int | None] | None = None) -> dict[str, Any]:
    """Draw centred lines with glow, drop shadow, stroke and gradient fill; returns the text bbox."""
    from PIL import Image, ImageDraw, ImageFilter  # noqa: PLC0415
    width, height = canvas.size
    font = load_font(spec, size)
    asc, desc = font.getmetrics()
    line_h = asc + desc
    stroke = max(2, int(size * (0.06 if effects else 0.04)))
    fill_mask = Image.new("L", canvas.size, 0)
    stroke_mask = Image.new("L", canvas.size, 0)
    fd, sd = ImageDraw.Draw(fill_mask), ImageDraw.Draw(stroke_mask)
    y = top_y
    boxes = []
    for line in lines:
        x = center_x - font.getlength(line) / 2
        fd.text((x, y), line, font=font, fill=255)
        sd.text((x, y), line, font=font, fill=255, stroke_width=stroke, stroke_fill=255)
        boxes.append(sd.textbbox((x, y), line, font=font, stroke_width=stroke))
        y += line_h + line_gap
    title_bbox = (int(min(b[0] for b in boxes)), int(min(b[1] for b in boxes)),
                  int(max(b[2] for b in boxes)) + 1, int(max(b[3] for b in boxes)) + 1)
    if tag and tag_spec:
        tag_size = max(12, int(size * 0.30))
        tag_font = load_font(tag_spec, tag_size)
        while tag_font.getlength(tag) > width * 0.86 and tag_size > 12:
            tag_size -= 2
            tag_font = load_font(tag_spec, tag_size)
        x = center_x - tag_font.getlength(tag) / 2
        y += int(line_h * 0.15)
        fd.text((x, y), tag, font=tag_font, fill=255)
        sd.text((x, y), tag, font=tag_font, fill=255, stroke_width=max(1, stroke // 2), stroke_fill=255)
        boxes.append(sd.textbbox((x, y), tag, font=tag_font, stroke_width=max(1, stroke // 2)))
    bbox = (int(min(b[0] for b in boxes)), int(min(b[1] for b in boxes)),
            int(max(b[2] for b in boxes)) + 1, int(max(b[3] for b in boxes)) + 1)
    out = canvas.convert("RGB")
    if effects and palette.get("glow"):
        glow = stroke_mask.filter(ImageFilter.GaussianBlur(max(2, size * 0.18)))
        glow = glow.point(lambda v: int(v * 0.75))
        out = Image.composite(Image.new("RGB", canvas.size, palette["glow"]), out, glow)
    shadow_offset = max(2, int(size * 0.05))
    shadow = Image.new("L", canvas.size, 0)
    shadow.paste(stroke_mask, (shadow_offset, shadow_offset))
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(1, size * 0.06))).point(lambda v: int(v * 0.8))
    out = Image.composite(Image.new("RGB", canvas.size, (0, 0, 0)), out, shadow)
    out = Image.composite(Image.new("RGB", canvas.size, palette["stroke"]), out, stroke_mask)
    top, bottom = palette["fill"]
    fill = Image.new("RGB", canvas.size, top)
    gradient = _gradient((bbox[2] - bbox[0] or 1, bbox[3] - bbox[1] or 1), top, bottom if effects else top)
    fill.paste(gradient, (bbox[0], bbox[1]))
    out = Image.composite(fill, out, fill_mask)
    return {"image": out, "bbox": bbox, "title_bbox": title_bbox, "stroke": stroke}


# --------------------------------------------------------------------------- #
# detectors (optional, reuse the engine's InsightFace / RapidOCR installs)
# --------------------------------------------------------------------------- #
_FACE_APP: Any = None


def detect_faces(image) -> list[tuple[int, int, int, int]] | None:
    """Face boxes (pixels) with InsightFace's detector, or None when it is not installed."""
    global _FACE_APP
    try:
        import numpy as np  # noqa: PLC0415
        if _FACE_APP is None:
            from insightface.app import FaceAnalysis  # noqa: PLC0415
            with contextlib.redirect_stdout(io.StringIO()):
                app = FaceAnalysis(name="buffalo_l", allowed_modules=["detection"], providers=["CPUExecutionProvider"])
                app.prepare(ctx_id=-1, det_size=(640, 640))
            _FACE_APP = app
        rgb = np.asarray(image.convert("RGB"))
        faces = _FACE_APP.get(rgb[:, :, ::-1].copy())
    except Exception:  # noqa: BLE001 -- optional detector
        return None
    return [tuple(int(v) for v in face.bbox[:4]) for face in faces if float(getattr(face, "det_score", 1.0)) >= 0.5]


_OCR: Any = None


def ocr_text(image) -> str | None:
    """Concatenated RapidOCR read-back of ``image``, or None when RapidOCR is not installed."""
    global _OCR
    try:
        import numpy as np  # noqa: PLC0415
        if _OCR is None:
            from rapidocr_onnxruntime import RapidOCR  # noqa: PLC0415
            _OCR = RapidOCR()
        result, _ = _OCR(np.asarray(image.convert("RGB")))
    except Exception:  # noqa: BLE001 -- optional verifier
        return None
    rows = sorted(result or [], key=lambda row: (min(p[1] for p in row[0]), min(p[0] for p in row[0])))
    return "".join(str(row[1]) for row in rows)


def normalise_for_ocr(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text or "")).casefold()
    return "".join(ch for ch in text if ch.isalnum())


def ocr_similarity(expected: str, heard: str) -> float:
    """Share of the title's characters found, in order, in the read-back (extra read-back text is ignored)."""
    a, b = normalise_for_ocr(expected), normalise_for_ocr(heard)
    if not a:
        return 0.0
    if a in b:
        return 1.0
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return sum(block.size for block in matcher.get_matching_blocks()) / len(a)


def ocr_readback_ok(expected: str, heard: str) -> bool:
    """The rendered text is exact by construction; OCR guards against unreadable results (missing glyphs,
    text lost in the art).  Calligraphic glyphs are often misread one at a time, so up to a quarter of the
    characters (at least one) may be missed, and at least two must be read."""
    a = normalise_for_ocr(expected)
    if not a:
        return False
    found = round(ocr_similarity(expected, heard) * len(a))
    allowed = max(1, int(len(a) * (1 - OCR_MIN_SIMILARITY)))
    return found >= min(len(a), 2) and len(a) - found <= allowed


def _overlaps(box: tuple[int, int, int, int], faces: list[tuple[int, int, int, int]], pad: int) -> bool:
    x0, y0, x1, y1 = box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad
    return any(not (fx1 < x0 or fx0 > x1 or fy1 < y0 or fy0 > y1) for fx0, fy0, fx1, fy1 in faces)


# --------------------------------------------------------------------------- #
# typesetting with verification + fallbacks
# --------------------------------------------------------------------------- #
def _place(art, title: str, tagline: str, style: dict[str, Any], placement: str, *, band_frac: float) -> dict[str, Any]:
    width, height = art.size
    text = title.upper() if style["uppercase"] else title
    plain = placement == "bar"
    spec = pick_font(style, text, plain=plain)
    palette = PALETTES["plain"] if plain else style["palette"]
    tag_spec = pick_font(style, tagline, plain=True) if tagline else None
    if plain:
        bar_frac = 0.20
        band = "bottom"
        max_w, max_h = width * 0.88, height * bar_frac * (0.62 if tagline else 0.75)
        fit = fit_title(text, spec, max_width=max_w, max_height=max_h, start_size=int(width * 0.12),
                        min_size=max(10, int(width * 0.035)))
    else:
        band = placement
        max_w = width * 0.88
        max_h = height * band_frac * (0.62 if tagline else 0.78)
        fit = fit_title(text, spec, max_width=max_w, max_height=max_h, start_size=int(width * 0.22),
                        min_size=max(10, int(width * 0.06)))
    block_h = fit["block_height"] + (fit["size"] * 0.45 if tagline else 0)
    if plain:
        from PIL import Image, ImageDraw  # noqa: PLC0415
        base = art.convert("RGB").copy()
        bar_box = (0, int(height * (1 - bar_frac)), width, height)
        overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
        ImageDraw.Draw(overlay).rectangle(bar_box, fill=(0, 0, 0, 215))
        base = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")
        top_y = bar_box[1] + (bar_box[3] - bar_box[1] - block_h) / 2
        strength = 0.84
        bg_box = bar_box
    else:
        strength = 0.55
        box = _band_box(width, height, band, band_frac)
        margin = height * 0.045
        top_y = (box[3] - margin - block_h - (box[3] - box[1] - margin - block_h) * 0.35) if band == "bottom" \
            else (box[1] + margin + (box[3] - box[1] - margin - block_h) * 0.35)
        bg_box = (int(width * 0.06), int(max(0, top_y)), int(width * 0.94), int(min(height, top_y + block_h)))
        base = darken_band(art, band, band_frac, strength)
        fill_mid = tuple((a + b) / 2 for a, b in zip(*palette["fill"]))
        while contrast_ratio(fill_mid, _mean_rgb(base, bg_box)) < CONTRAST_MIN and strength < 0.95:
            strength = min(0.95, strength + 0.1)
            base = darken_band(art, band, band_frac, strength)
    fill_mid = tuple((a + b) / 2 for a, b in zip(*palette["fill"]))
    contrast = contrast_ratio(fill_mid, _mean_rgb(base, bg_box))
    drawn = draw_text_block(base, fit["lines"], spec, fit["size"], center_x=width / 2, top_y=top_y,
                            palette=palette, line_gap=fit["line_gap"], effects=not plain,
                            tag=tagline, tag_spec=tag_spec)
    return {"image": drawn["image"], "bbox": drawn["bbox"], "title_bbox": drawn["title_bbox"], "placement": placement, "band": band,
            "font": _font_path(spec).name, "font_weight": spec[1], "size": fit["size"], "lines": fit["lines"],
            "fits": fit["fits"], "rendered_text": "".join(fit["lines"]) if is_cjk_text(text) else " ".join(fit["lines"]),
            "band_darkening": round(strength, 2), "contrast_ratio": round(contrast, 2), "tagline": tagline or None}


def typeset(art, title: str, *, genre: str = "", style_text: str = "", language: str = "zh", tagline: str = "",
            band: str = "bottom", band_frac: float = 0.30,
            face_detector: Callable[[Any], Any] | None = detect_faces,
            ocr: Callable[[Any], Any] | None = ocr_text) -> dict[str, Any]:
    """Set ``title`` on ``art`` (a PIL image).  Tries the preferred band, the other band, then a plain bar;
    a placement is accepted when the title fits, clears the contrast floor, covers no detected face and
    (when OCR is available) reads back as the title.  Returns the image and every attempt's evidence."""
    title = str(title or "").strip()
    if not title:
        raise ValueError("POSTER_TITLE_EMPTY")
    style = style_for(genre, style_text, language)
    faces = face_detector(art) if face_detector else None
    first = "top" if band == "top" else "bottom"
    order = [first, "bottom" if first == "top" else "top", "bar"]
    attempts: list[dict[str, Any]] = []
    chosen: dict[str, Any] | None = None
    for placement in order:
        result = _place(art, title, tagline, style, placement, band_frac=band_frac)
        problems: list[str] = []
        if not result["fits"]:
            problems.append("TITLE_DOES_NOT_FIT")
        if placement != "bar" and result["contrast_ratio"] < CONTRAST_MIN:
            problems.append("CONTRAST_BELOW_4_5")
        if faces and placement != "bar" and _overlaps(result["bbox"], faces, pad=int(art.size[0] * 0.01)):
            problems.append("TEXT_OVERLAPS_FACE")
        expected = title.upper() if style["uppercase"] else title
        if normalise_for_ocr(result["rendered_text"]) != normalise_for_ocr(expected):
            problems.append("RENDERED_TEXT_MISMATCH")
        heard = None
        similarity = None
        if ocr and not problems:
            box = result["title_bbox"]
            pad = int(art.size[0] * 0.04)
            crop = result["image"].crop((max(0, box[0] - pad), max(0, box[1] - pad),
                                         min(art.size[0], box[2] + pad), min(art.size[1], box[3] + pad)))
            heard = ocr(crop)
            if heard is not None:
                similarity = round(ocr_similarity(title, heard), 3)
                if not ocr_readback_ok(title, heard):
                    problems.append("OCR_READBACK_MISMATCH")
        record = {k: v for k, v in result.items() if k != "image"}
        record.update({"problems": problems, "ocr_text": heard, "ocr_similarity": similarity,
                       "ocr": "UNAVAILABLE" if ocr is None or (heard is None and not problems) else "RUN"})
        attempts.append(record)
        if not problems or placement == "bar":
            chosen = {**result, **record, "accepted_with_problems": bool(problems)}
            break
    assert chosen is not None
    return {"image": chosen["image"], "style": style["slot"], "language": style["language"], "chosen": chosen["placement"],
            "attempts": attempts, "faces": faces, "face_detector": "UNAVAILABLE" if faces is None else "INSIGHTFACE",
            "accepted_with_problems": chosen["accepted_with_problems"]}


def save_jpeg(image, path: Path, *, max_bytes: int, width: int | None = None, quality: int = 92) -> dict[str, Any]:
    from PIL import Image  # noqa: PLC0415
    img = image.convert("RGB")
    if width and img.size[0] != width:
        img = img.resize((width, max(1, round(img.size[1] * width / img.size[0]))), Image.LANCZOS)
    data = b""
    for q in range(quality, 29, -6):
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=q, optimize=True, progressive=True)
        data = buffer.getvalue()
        if len(data) <= max_bytes:
            break
    if len(data) > max_bytes:
        raise RuntimeError(f"JPEG_OVER_LIMIT:{path.name}:{len(data)}>{max_bytes}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    temporary.write_bytes(data)
    os.replace(temporary, path)
    return {"path": str(path), "bytes": len(data), "sha256": sha256_bytes(data), "size": list(img.size), "quality": q}


def render_cover_files(art_path: Path, out_dir: Path, ident: dict[str, Any], **detectors: Any) -> dict[str, Any]:
    """Typeset ``art_path`` into ``out_dir/cover.jpg`` + ``cover_thumb.jpg`` + ``cover.json``."""
    from PIL import Image  # noqa: PLC0415
    with Image.open(art_path) as opened:
        art = opened.convert("RGB")
    result = typeset(art, ident["title"], genre=ident.get("genre", ""), style_text=ident.get("style", ""),
                     language=ident.get("language", "zh"), tagline=ident.get("tagline", ""),
                     band=ident.get("band", "bottom"), **detectors)
    out_dir = Path(out_dir)
    cover = save_jpeg(result["image"], out_dir / COVER_NAME, max_bytes=COVER_MAX_BYTES)
    thumb = save_jpeg(result["image"], out_dir / THUMB_NAME, max_bytes=THUMB_MAX_BYTES, width=THUMB_WIDTH, quality=85)
    meta = {"schema": "nalu.series_cover.v1", "render_version": RENDER_VERSION, "rendered_at": utc_now(),
            "title": ident["title"], "series_key": ident.get("series_key"), "tagline": ident.get("tagline") or None,
            "art": str(art_path), "art_sha256": sha256_file(art_path), "art_size": list(art.size),
            "style": result["style"], "language": result["language"], "placement": result["chosen"],
            "accepted_with_problems": result["accepted_with_problems"], "face_detector": result["face_detector"],
            "faces": result["faces"], "attempts": result["attempts"], "cover": cover, "thumb": thumb}
    atomic_json(out_dir / COVER_META, meta)
    return meta


# --------------------------------------------------------------------------- #
# key art: references, prompt, paid durable request
# --------------------------------------------------------------------------- #
GENRE_MOODS = (
    (("仙侠", "修仙", "玄幻", "xianxia", "fantasy"), "epic eastern fantasy, ethereal mist, mystical light"),
    (("古装", "宫", "历史", "王朝", "historical", "palace", "dynasty"), "lavish historical drama, period costume, candlelight and silk"),
    (("悬疑", "惊悚", "恐怖", "suspense", "thriller", "horror", "mystery"), "tense suspense thriller, low-key lighting, deep shadows, ominous atmosphere"),
    (("复仇", "revenge"), "cold, defiant revenge drama, hard contrast"),
    (("甜宠", "霸总", "言情", "恋爱", "婚", "romance", "ceo", "sweet", "love", "billionaire"), "glamorous romantic drama, warm intimate glow, longing"),
    (("末世", "科幻", "sci", "apocalypse"), "gritty sci-fi spectacle, cold neon and dust"),
    (("werewolf", "lycan", "vampire"), "dark romantic fantasy, moonlight, forest, wolf-pack menace"),
)


def genre_mood(ident: dict[str, Any]) -> str:
    haystack = f"{ident.get('genre', '')} {ident.get('style', '')} {ident.get('title', '')}".lower()
    moods = [mood for words, mood in GENRE_MOODS if any(w in haystack for w in words)]
    return "; ".join(moods[:2]) or "high-stakes cinematic drama"


def registry_path(runtime: Path, episode: str) -> Path:
    """The series scope's character registry (runtime/series_scopes.json), else the default one."""
    runtime = Path(runtime)
    config = read_json(runtime / "runtime" / "series_scopes.json", {}) or {}
    sid = str((config.get("episodes") or {}).get(episode) or config.get("default_scope") or "")
    declared = ((config.get("scopes") or {}).get(sid) or {}) if sid else {}
    value = declared.get("character_registry") if isinstance(declared, dict) else None
    if value:
        path = Path(str(value)).expanduser()
        return path if path.is_absolute() else runtime / path
    return runtime / "runtime" / "nalu_character_asset_registry.json"


def _names(row: dict[str, Any]) -> list[str]:
    names = [row.get("canonical_name"), row.get("name"), row.get("display_name")] + list(row.get("aliases") or [])
    return [str(n) for n in names if n]


def rank_leads(brief: dict[str, Any]) -> list[dict[str, Any]]:
    """Brief characters, lead first: brief ``poster_characters`` / ``lead_character_id`` win; otherwise the
    character named most in the synopsis, ties by the brief's own order."""
    chars = [c for c in brief.get("characters") or [] if isinstance(c, dict) and c.get("character_id")]
    explicit = [str(x) for x in (brief.get("poster_characters") or [])] or \
        ([str(brief["lead_character_id"])] if brief.get("lead_character_id") else [])
    synopsis = str(brief.get("synopsis") or "")

    def score(item: tuple[int, dict[str, Any]]) -> tuple[int, int, int]:
        index, row = item
        pinned = explicit.index(row["character_id"]) if row["character_id"] in explicit else 99
        mentions = sum(synopsis.count(name) for name in _names(row))
        return (pinned, -mentions, index)
    return [row for _, row in sorted(enumerate(chars), key=score)]


def _plate_paths(row: dict[str, Any]) -> list[str]:
    paths = [str(p) for p in row.get("canonical_reference_paths") or []]
    head = [p for p in paths if "FRONT_NEUTRAL_HEADSHOT" in Path(p).name]
    primary = str(row.get("generation_reference_image") or (paths[0] if paths else ""))
    return [p for p in dict.fromkeys(head + [primary]) if p]


def find_lead_references(engine: Path, runtime: Path, episode: str, brief: dict[str, Any],
                         *, max_characters: int = 2) -> list[dict[str, Any]]:
    """[{character_id, name, role, path, sha256}] -- the lead's headshot + plate, the second lead's headshot.
    Sources: the series' LOCKED character registry, else the newest S3 plates under workflow/nalu/*/identity."""
    registry = read_json(registry_path(runtime, episode), {}) or {}
    rows = registry.get("characters") or {}
    by_id = {str(k): v for k, v in rows.items()} if isinstance(rows, dict) else \
        {str(r.get("registry_id")): r for r in rows if isinstance(r, dict)}
    by_name = {name: row for row in by_id.values() if isinstance(row, dict) for name in _names(row)}
    out: list[dict[str, Any]] = []
    chosen = 0
    for character in rank_leads(brief):
        if chosen >= max_characters:
            break
        cid = str(character["character_id"])
        row = by_id.get(cid) or next((by_name[n] for n in _names(character) if n in by_name), None)
        paths = _plate_paths(row) if isinstance(row, dict) else []
        if not paths:
            plates = sorted(Path(engine).glob(f"workflow/nalu/*/identity/plates/*_{cid}__FRONT_NEUTRAL_HEADSHOT_*.png"),
                            key=lambda p: p.stat().st_mtime, reverse=True)
            plates += sorted(Path(engine).glob(f"workflow/nalu/*/identity/plates/*_{cid}_*.png"),
                             key=lambda p: p.stat().st_mtime, reverse=True)
            paths = [str(p) for p in plates if "__" not in p.name or "FRONT_NEUTRAL_HEADSHOT" in p.name][:2]
        paths = [p for p in paths if Path(p).is_file()]
        if not paths:
            continue
        keep = paths[:2] if chosen == 0 else paths[:1]
        role = "LEAD" if chosen == 0 else "SECOND_LEAD"
        name = (_names(character) or [cid])[0]
        out += [{"character_id": cid, "name": name, "role": role, "path": p, "sha256": sha256_file(Path(p))} for p in keep]
        chosen += 1
    return out


def build_art_prompt(ident: dict[str, Any], references: list[dict[str, Any]], *, band: str = "bottom") -> str:
    lead = [r for r in references if r["role"] == "LEAD"]
    second = [r for r in references if r["role"] == "SECOND_LEAD"]
    lead_refs = " and ".join(f"reference image {references.index(r) + 1}" for r in lead)
    cast = (f"The hero of the poster is the person in {lead_refs}: keep that exact face, age, hairstyle and "
            "costume; the face is large, sharp, well lit and clearly visible (a dramatic close-up or "
            "three-quarter portrait), the emotional centre of the image.")
    if second:
        cast += (f" The person in reference image {references.index(second[0]) + 1} (same exact identity) appears "
                 "smaller, behind or beside the hero, face recognisable.")
    zone = "bottom 30%" if band != "top" else "top 30%"
    synopsis = ident.get("synopsis", "")[:420]
    return (
        "Cinematic vertical 9:16 key-art poster for a short drama series. "
        f"Genre and mood: {genre_mood(ident)}. "
        + (f"Visual style: {ident['style']}. " if ident.get("style") else "")
        + (f"Story: {synopsis} " if synopsis else "")
        + cast + " "
        "Composition: premium streaming-series poster, film-still quality, dramatic rim light, rich colour "
        "grade, shallow depth of field, the faces in the upper two thirds of the frame. "
        f"Leave the {zone} of the image as a clean, low-detail area that fades smoothly into deep shadow (a "
        "dark gradient zone) with no faces, no hands, no bright objects and no busy detail, so a title can be "
        "added there later. "
        "ABSOLUTELY NO TEXT anywhere: no title, no letters, no words, no Chinese characters, no numbers, no "
        "captions, no credits block, no logos, no watermarks, no signatures, no subtitles, no typography."
    )


def art_size(config_path: Path | None, attempt: int, environ: dict[str, str] | None = None) -> str:
    if attempt >= 2:
        return REDO_ART_SIZE
    env = os.environ if environ is None else environ
    gen = (read_json(config_path, {}) or {}).get("generation") or {} if config_path else {}
    return str(env.get("NALU_POSTER_ART_SIZE") or gen.get("series_poster_art_size") or DEFAULT_ART_SIZE)


def estimated_art_credits(size: str, per_image: float) -> float:
    width, height = (int(v) for v in size.split("x"))
    return round(max(1.0, width * height / PROBE_PIXELS) * per_image + 0.049, 1)


def _image_client():
    try:
        from tools import hopsapi_image_client as client  # noqa: PLC0415
    except ModuleNotFoundError:  # flat tools/ on sys.path
        import hopsapi_image_client as client  # type: ignore[no-redef]  # noqa: PLC0415
    return client


def _env_file_value(path: Path, name: str) -> str:
    try:
        match = re.search(rf"^\s*(?:export\s+)?{re.escape(name)}=(.*)$", Path(path).read_text(encoding="utf-8"), re.M)
    except OSError:
        return ""
    return match.group(1).strip().strip("'\"") if match else ""


@contextlib.contextmanager
def hopsapi_key_env(engine: Path, runtime: Path):
    """HOPSAPI_API_KEY (and base URLs) for this process only, the way paid_stage.sh finds them: the
    environment, else the engine .env, else the Codex provider key when that provider is HopsAPI.
    Restored afterwards; never printed."""
    saved = {k: os.environ.get(k) for k in ("HOPSAPI_API_KEY", "HOPSAPI_BASE_URL", "HOPSAPI_CONSOLE_URL")}
    try:
        if not str(os.environ.get("HOPSAPI_API_KEY") or "").strip():
            key = _env_file_value(Path(engine) / ".env", "HOPSAPI_API_KEY")
            if not key:
                provider = read_json(Path(runtime) / "credentials" / "llm_provider.json", {}) or {}
                if "hopsapi" in str(provider.get("base_url") or "").lower():
                    key = str(provider.get("api_key") or "").strip()
            if key:
                os.environ["HOPSAPI_API_KEY"] = key
            for name in ("HOPSAPI_BASE_URL", "HOPSAPI_CONSOLE_URL"):
                value = _env_file_value(Path(engine) / ".env", name)
                if value and not os.environ.get(name):
                    os.environ[name] = value
        yield bool(str(os.environ.get("HOPSAPI_API_KEY") or "").strip())
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def paid_art_permission(runtime: Path, environ: dict[str, str] | None = None) -> dict[str, Any]:
    """{allowed, reason}: the owner's switch, the runtime's paid lock and the image provider (key checked later)."""
    env = os.environ if environ is None else environ
    if str(env.get("NALU_SERIES_POSTER_ART") or "").strip().lower() in ("0", "off", "false", "no"):
        return {"allowed": False, "reason": "DISABLED_BY_ENV"}
    config = Path(runtime) / "qingshan.json"
    gen = (read_json(config, {}) or {}).get("generation") or {}
    if gen.get("series_poster_art") is False:
        return {"allowed": False, "reason": "DISABLED_BY_QINGSHAN_JSON"}
    if not gen.get("paid_requests_enabled"):
        return {"allowed": False, "reason": "PAID_REQUESTS_DISABLED"}
    try:
        provider = _image_client().resolve_image_provider(config, {**env, "HOPSAPI_API_KEY": "present"})
    except ValueError as exc:
        return {"allowed": False, "reason": f"IMAGE_PROVIDER_INVALID:{exc}"}
    if provider["provider"] != "hopsapi":
        return {"allowed": False, "reason": f"IMAGE_PROVIDER_NOT_HOPSAPI:{provider['provider']}"}
    return {"allowed": True, "reason": "OK"}


def _attempt_finished(tx: dict[str, Any]) -> str | None:
    """FAILED_UNCHARGED (a redo may follow), LOST (never resend) or None (bound / in progress)."""
    state = str(tx.get("state") or "")
    if state == "NOT_CHARGED_RETRYABLE":
        return "FAILED_UNCHARGED"
    if state == "SUBMITTED_TASK_ID_BOUND":
        remote = str(tx.get("remote_terminal_state") or tx.get("provider_remote_status") or "").lower()
        if remote in ("failed", "cancelled") and not tx.get("provider_cost_credits"):
            return "FAILED_UNCHARGED"
        return None
    return "LOST"


def _poll_and_harvest(client, tx_path: Path, art_path: Path, manifest: dict[str, Any], manifest_path: Path, *,
                      wait_seconds: float, sleep: Callable[[float], None], clock: Callable[[], float]) -> dict[str, Any]:
    tx = read_json(tx_path, {}) or {}
    task_id = str(tx.get("task_id") or "")
    deadline = clock() + max(0.0, wait_seconds)
    while True:
        try:
            status = client.query_task(task_id)
        except Exception as exc:  # noqa: BLE001 -- a GET; try again on the next call
            return {"status": "ART_PENDING", "task_id": task_id, "error": f"{type(exc).__name__}"[:120]}
        remote = str(status.get("remote_status") or "unknown")
        if remote == "completed" and status.get("urls"):
            client.record_settlement(tx_path, task_id, status, now=utc_now())
            try:
                landed = client.download_image(status["urls"][0], art_path)
            except Exception as exc:  # noqa: BLE001 -- the task is paid: retry the download next call
                return {"status": "ART_DOWNLOAD_PENDING", "task_id": task_id, "error": str(exc)[:200]}
            tx = read_json(tx_path, {}) or {}
            manifest.update({"status": "READY", "art": str(art_path), "art_sha256": landed["sha256"],
                             "art_size": landed.get("size"), "task_id": task_id, "transaction": str(tx_path),
                             "cost_credits": tx.get("provider_cost_credits"), "generated_at": utc_now()})
            atomic_json(manifest_path, manifest)
            return {"status": "ART_GENERATED", "task_id": task_id, "cost_credits": tx.get("provider_cost_credits")}
        if remote in ("failed", "cancelled"):
            client.record_settlement(tx_path, task_id, status, now=utc_now())
            return {"status": "ART_TASK_FAILED", "task_id": task_id, "error": str(status.get("error") or "")[:200]}
        if clock() >= deadline:
            return {"status": "ART_PENDING", "task_id": task_id, "remote_status": remote}
        sleep(POLL_SECONDS)


def ensure_art(engine: Path, runtime: Path, episode: str, brief: dict[str, Any], *, allow_paid: bool | None = None,
               client: Any = None, wait_seconds: float = DEFAULT_WAIT_SECONDS,
               sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> dict[str, Any]:
    """Make sure the series has key art; at most MAX_ATTEMPTS create POSTs per series, ever.  Free when cached."""
    engine, runtime = Path(engine), Path(runtime)
    ident = series_identity(brief)
    out = cover_dir(runtime)
    art_path, manifest_path = out / ART_NAME, out / ART_MANIFEST
    manifest = read_json(manifest_path, {}) or {}
    if art_path.is_file():
        digest = sha256_file(art_path)
        if manifest.get("art_sha256") == digest:
            return {"status": "ART_CACHED", "art": str(art_path)}
        manifest.update({"schema": "nalu.series_poster_art.v1", "status": "READY", "source": "OPERATOR_PROVIDED",
                         "art": str(art_path), "art_sha256": digest, "adopted_at": utc_now(),
                         "series_key": ident["series_key"], "title": ident["title"]})
        atomic_json(manifest_path, manifest)
        return {"status": "ART_ADOPTED", "art": str(art_path)}
    client = client or _image_client()
    manifest.setdefault("schema", "nalu.series_poster_art.v1")
    manifest.setdefault("series_key", ident["series_key"])
    manifest.setdefault("title", ident["title"])
    attempts = manifest.setdefault("attempts", [])
    with hopsapi_key_env(engine, runtime) as have_key:
        if attempts:
            tx_path = Path(attempts[-1]["transaction"])
            tx = read_json(tx_path, {}) or {}
            finished = _attempt_finished(tx)
            if finished is None:
                if not have_key:
                    return {"status": "ART_PENDING_NO_KEY", "task_id": tx.get("task_id")}
                result = _poll_and_harvest(client, tx_path, art_path, manifest, manifest_path,
                                           wait_seconds=wait_seconds, sleep=sleep, clock=clock)
                if result["status"] != "ART_TASK_FAILED":
                    return result
                finished = "FAILED_UNCHARGED"
            attempts[-1]["outcome"] = finished
            atomic_json(manifest_path, manifest)
            if finished == "LOST":
                manifest["status"] = "RESPONSE_LOST"
                atomic_json(manifest_path, manifest)
                return {"status": "ART_RESPONSE_LOST", "transaction": str(tx_path),
                        "note": "no idempotency key: never resent; reconcile on the HopsAPI console"}
            if len(attempts) >= MAX_ATTEMPTS:
                manifest["status"] = "FAILED"
                atomic_json(manifest_path, manifest)
                return {"status": "ART_FAILED", "attempts": len(attempts)}
        permission = paid_art_permission(runtime) if allow_paid is None else \
            {"allowed": bool(allow_paid), "reason": "CALLER"}
        if not permission["allowed"]:
            return {"status": "ART_NOT_AUTHORIZED", "reason": permission["reason"]}
        if not have_key:
            return {"status": "ART_NOT_AUTHORIZED", "reason": "HOPSAPI_API_KEY_MISSING"}
        if not ident["title"]:
            return {"status": "ART_SKIPPED", "reason": "BRIEF_TITLE_MISSING"}
        references = find_lead_references(engine, runtime, episode, brief)
        if not references:
            return {"status": "ART_SKIPPED", "reason": "NO_IDENTITY_REFERENCES"}
        store_root = engine / "workflow" / "tasks" / IMAGE_STORE_DIRNAME
        outage = client.recent_provider_outage(store_root)
        if outage and client.recent_successful_task(store_root) is None:
            return {"status": "ART_DEFERRED_PROVIDER_OUTAGE", "retry_after_utc": outage.get("retry_after_utc")}
        attempt_no = len(attempts) + 1
        size = art_size(runtime / "qingshan.json", attempt_no)
        prompt = build_art_prompt(ident, references, band=ident["band"])
        prompt_sha = sha256_bytes(prompt.encode("utf-8"))
        try:
            prepared = client.prepare_request(prompt=prompt, reference_paths=[r["path"] for r in references],
                                              aspect_ratio="9:16", resolution=size, task_key=TASK_KEY,
                                              quality=ART_QUALITY)
        except Exception as exc:  # noqa: BLE001 -- pre-intent: nothing POSTed, nothing charged
            return {"status": "ART_PREPARE_FAILED", "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
        fingerprint = sha256_bytes(json.dumps({"task": TASK_KEY, "series_key": ident["series_key"],
                                               "prompt_sha256": prompt_sha, "attempt": attempt_no,
                                               "reference_sha256": [r["sha256"] for r in references],
                                               "model": client.MODEL, "resolution": prepared["resolution"]},
                                              sort_keys=True).encode("utf-8"))
        tx_path = store_root / episode / f"{TASK_KEY}__{fingerprint[:16]}.json"
        estimate = estimated_art_credits(prepared["resolution"], float(client.estimated_task_credits()))
        intent = {
            "schema": "qingshan.giggle_submit_transaction.v1", "episode": episode, "task_key": TASK_KEY,
            "attempt_id": str(uuid.uuid4()), "submission_fingerprint": fingerprint, "state": "INTENT_RECORDED",
            "intent_recorded_at": utc_now(), "model": client.LOGICAL_MODEL, "prompt_sha256": prompt_sha,
            "reference_image_sha256s": [r["sha256"] for r in references], "endpoint": "hopsapi:/router/task/create",
            "retry_guard": "DO_NOT_RESUBMIT_UNTIL_LEDGER_RECONCILED", "series_poster": True,
            "series_key": ident["series_key"], "poster_attempt": attempt_no,
            **client.intent_fields(prepared, estimated_credits=estimate),
        }
        atomic_json(tx_path, intent)
        attempts.append({"attempt": attempt_no, "transaction": str(tx_path), "resolution": prepared["resolution"],
                         "intent_recorded_at": intent["intent_recorded_at"], "estimated_credits": estimate})
        manifest.update({"status": "SUBMITTING", "episode": episode, "prompt": prompt, "prompt_sha256": prompt_sha,
                         "references": references, "quality": ART_QUALITY})
        atomic_json(manifest_path, manifest)  # durable before the POST
        previous = os.environ.get("QINGSHAN_DURABLE_SUBMITTER_CONTEXT")
        os.environ["QINGSHAN_DURABLE_SUBMITTER_CONTEXT"] = "1"
        try:
            response = client.create_image_task(prepared["payload"])
        except client.hops.HopsapiNotCharged as exc:
            intent.update({"state": "NOT_CHARGED_RETRYABLE", "credit_status": "NOT_CHARGED_RETRYABLE",
                           "response_received_at": utc_now(), "error": str(exc)[:500],
                           "retry_guard": "RETRY_ALLOWED_NEW_ATTEMPT"})
            atomic_json(tx_path, intent)
            attempts[-1]["outcome"] = "FAILED_UNCHARGED"
            atomic_json(manifest_path, manifest)
            return {"status": "ART_SUBMIT_DECLINED", "error": str(exc)[:200]}
        except (Exception, SystemExit) as exc:  # noqa: BLE001 -- may have been charged: never resend
            intent.update({"state": "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION", "error": str(exc)[:500],
                           "response_lost_at": utc_now(),
                           "operator_note": "HopsAPI has no idempotency key: check the console before any new POST"})
            atomic_json(tx_path, intent)
            attempts[-1]["outcome"] = "LOST"
            manifest["status"] = "RESPONSE_LOST"
            atomic_json(manifest_path, manifest)
            return {"status": "ART_RESPONSE_LOST", "transaction": str(tx_path)}
        finally:
            if previous is None:
                os.environ.pop("QINGSHAN_DURABLE_SUBMITTER_CONTEXT", None)
            else:
                os.environ["QINGSHAN_DURABLE_SUBMITTER_CONTEXT"] = previous
        intent.update({"state": "SUBMITTED_TASK_ID_BOUND", "task_id": str(response["task_id"]),
                       "provider_response": response, "response_recorded_at": utc_now()})
        atomic_json(tx_path, intent)
        manifest["status"] = "SUBMITTED"
        atomic_json(manifest_path, manifest)
        return _poll_and_harvest(client, tx_path, art_path, manifest, manifest_path,
                                 wait_seconds=wait_seconds, sleep=sleep, clock=clock)


# --------------------------------------------------------------------------- #
# the one entry point the publisher / tick uses
# --------------------------------------------------------------------------- #
def _archive_other_series(runtime: Path, ident: dict[str, Any]) -> str | None:
    out = cover_dir(runtime)
    manifest = read_json(out / ART_MANIFEST, {}) or read_json(out / COVER_META, {}) or {}
    old = manifest.get("series_key")
    if not out.is_dir() or not old or old == ident["series_key"]:
        return None
    target = Path(runtime) / "series" / "cover_archive" / f"{re.sub(r'[^A-Za-z0-9._-]+', '-', old)}-{int(time.time())}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(out), str(target))
    return str(target)


def cover_is_current(runtime: Path, ident: dict[str, Any]) -> bool:
    out = cover_dir(runtime)
    meta = read_json(out / COVER_META, {}) or {}
    art = out / ART_NAME
    return (art.is_file() and (out / COVER_NAME).is_file() and (out / THUMB_NAME).is_file()
            and meta.get("render_version") == RENDER_VERSION and meta.get("title") == ident["title"]
            and (meta.get("tagline") or None) == (ident.get("tagline") or None)
            and meta.get("art_sha256") == sha256_file(art))


def ensure_series_cover(engine: Path, runtime: Path, episode: str, brief: dict[str, Any], *,
                        allow_paid: bool | None = None, client: Any = None,
                        wait_seconds: float = DEFAULT_WAIT_SECONDS, **detectors: Any) -> dict[str, Any]:
    """Art (cached / adopted / generated) then title typesetting when the cover is missing or stale.
    Never raises: the publisher falls back to its frame grab whenever ``cover`` is absent."""
    try:
        ident = series_identity(brief)
        if not ident["title"]:
            return {"status": "SKIPPED", "reason": "BRIEF_TITLE_MISSING"}
        archived = _archive_other_series(runtime, ident)
        if cover_is_current(runtime, ident):
            return {"status": "CURRENT", "cover": str(cover_dir(runtime) / COVER_NAME)}
        art = ensure_art(engine, runtime, episode, brief, allow_paid=allow_paid, client=client, wait_seconds=wait_seconds)
        art_path = cover_dir(runtime) / ART_NAME
        result: dict[str, Any] = {"art": art, **({"archived_previous_series": archived} if archived else {})}
        if not art_path.is_file():
            return {"status": "NO_ART", **result}
        meta = render_cover_files(art_path, cover_dir(runtime), ident, **detectors)
        return {"status": "RENDERED", "cover": meta["cover"]["path"], "thumb": meta["thumb"]["path"],
                "placement": meta["placement"], "style": meta["style"], **result}
    except Exception as exc:  # noqa: BLE001 -- a cover must never block a publish
        return {"status": "ERROR", "error": f"{type(exc).__name__}: {str(exc)[:300]}"}


def published_cover(runtime: Path, title: str | None = None) -> Path | None:
    """``cover.jpg`` when it exists and belongs to ``title`` (when given); else None (frame-grab fallback)."""
    out = cover_dir(runtime)
    cover = out / COVER_NAME
    if not cover.is_file() or cover.stat().st_size == 0 or cover.stat().st_size > COVER_MAX_BYTES:
        return None
    meta = read_json(out / COVER_META, {}) or {}
    if title and str(meta.get("title") or "").strip()[:100] != str(title).strip()[:100]:
        return None
    return cover


def dashboard_thumb(runtime: Path) -> Path | None:
    thumb = cover_dir(runtime) / THUMB_NAME
    if thumb.is_file() and 0 < thumb.stat().st_size <= THUMB_MAX_BYTES:
        return thumb
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Series poster cover (key art + typeset title).")
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render", help="free: typeset a title onto local art (no paid call)")
    r.add_argument("--art", required=True)
    r.add_argument("--title", required=True)
    r.add_argument("--out", required=True, help="output directory (cover.jpg, cover_thumb.jpg, cover.json)")
    r.add_argument("--genre", default="")
    r.add_argument("--style", default="")
    r.add_argument("--language", default="zh")
    r.add_argument("--tagline", default="")
    r.add_argument("--band", default="bottom", choices=("bottom", "top"))
    e = sub.add_parser("ensure", help="art (paid only when the runtime allows it) + cover for an episode's brief")
    e.add_argument("--episode", required=True)
    e.add_argument("--engine-root", default=os.environ.get("NALU_ENGINE_ROOT") or str(ROOT))
    e.add_argument("--runtime-root", default=os.environ.get("NALU_RUNTIME_ROOT") or "~/nalu_runtime")
    e.add_argument("--no-paid", action="store_true")
    s = sub.add_parser("status")
    s.add_argument("--runtime-root", default=os.environ.get("NALU_RUNTIME_ROOT") or "~/nalu_runtime")
    args = parser.parse_args(argv)
    if args.cmd == "render":
        ident = {"title": args.title, "series_key": None, "genre": args.genre, "style": args.style,
                 "language": args.language, "tagline": args.tagline, "band": args.band}
        meta = render_cover_files(Path(args.art), Path(args.out), ident)
        print(json.dumps({k: meta[k] for k in ("style", "placement", "accepted_with_problems", "cover", "thumb")},
                         ensure_ascii=False, indent=2))
        return 0
    runtime = Path(args.runtime_root).expanduser()
    if args.cmd == "status":
        out = cover_dir(runtime)
        print(json.dumps({"art_manifest": read_json(out / ART_MANIFEST), "cover": read_json(out / COVER_META)},
                         ensure_ascii=False, indent=2)[:6000])
        return 0
    brief = read_json(runtime / "briefs" / f"{args.episode}_PRODUCTION_BRIEF.json", {}) or {}
    result = ensure_series_cover(Path(args.engine_root), runtime, args.episode, brief,
                                 allow_paid=False if args.no_paid else None)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") != "ERROR" else 3


if __name__ == "__main__":
    raise SystemExit(main())
