#!/usr/bin/env python3
"""Clean burned caption text off a unit's real tail frame before it becomes the next unit's anchor.

MiniMax-H3 sometimes burns the spoken line into the picture as on-screen caption text (K143/K144,
``H3_BURNED_TEXT_COVER_V1``) and the burn often lasts to the clip's last frame.  The engine hands
that last frame to the successor unit as its start-frame reference, so without cleaning the
burned line propagates down a whole tail chain.  Both extraction points call
:func:`clean_tail_frame` after ffmpeg writes the tail frame and before it is finalised:

* ``lines/nalu/runtime/tools/nalu_pipeline.py`` ``extract_real_final_frame``
* ``tools/episode_parallel_batch_supervisor.py`` ``bind_predecessor_tail_frame``

Detection reuses ``burned_text_cover``: the same RapidOCR engine, the policy's scan confidence /
minimum-character thresholds and its cover false-positive filters (centred, horizontal, area
cap).  Only the band y 0.55-0.95 is scanned; a hit is CJK/Latin/kana/hangul text of at least
2 characters with glyph height >= 40 px at 720 px width (H3 burns are 55-80 px; our own
subtitles are never in a raw H3 clip).  Each hit box is expanded by 8 px and inpainted
(cv2 TELEA, radius 5).  Local only, no network, zero credits.

Fail-open: OCR / OpenCV missing or erroring keeps the original frame (warning on stderr); the
pipeline is never blocked.  ``NALU_TAIL_TEXT_CLEAN=0`` turns the cleaning off.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Callable

_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import burned_text_cover as _btc  # noqa: E402

ENV_FLAG = "NALU_TAIL_TEXT_CLEAN"
SCHEMA = "qingshan.tail_frame_text_clean.v1"
BAND_Y0, BAND_Y1 = 0.55, 0.95
MIN_GLYPH_PX_AT_720 = 40.0
BOX_PAD_PX = 8
INPAINT_RADIUS = 5
#: CJK ideographs, kana, hangul, Latin letters
TEXT_CHAR = re.compile(r"[A-Za-z぀-ヿ㐀-䶿一-鿿가-힯ᄀ-ᇿ]")

#: OCR callable: BGR/RGB ndarray -> [(box_points, text, score), ...] (RapidOCR result shape)
OcrFn = Callable[[Any], list]

_ENGINE: Any = None


def enabled(env: dict[str, str] | None = None) -> bool:
    value = str((env if env is not None else os.environ).get(ENV_FLAG, "1")).strip().lower()
    return value not in {"0", "false", "no", "off"}


def _default_ocr(image: Any) -> list:
    """The RapidOCR engine ``burned_text_cover.ocr_frames`` uses, loaded once per process."""
    global _ENGINE
    if _ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR  # noqa: PLC0415
        _ENGINE = RapidOCR()
    return _ENGINE(image)[0] or []


def _thresholds() -> tuple[float, int, dict[str, Any]]:
    try:
        cfg = _btc.policy()
    except Exception:  # noqa: BLE001 - policy file missing: built-in defaults
        cfg = {}
    scan = cfg.get("scan") or {}
    return (float(scan.get("min_confidence", 0.6)), int(scan.get("min_cjk_chars", 2)), _btc._cover_cfg(cfg))


def find_text_boxes(image: Any, ocr: OcrFn) -> list[dict[str, Any]]:
    """OCR hits in the band that read as a burned caption line; boxes in full-frame pixels."""
    h, w = image.shape[:2]
    y0 = int(round(h * BAND_Y0))
    y1 = int(round(h * BAND_Y1))
    crop = image[y0:y1]
    min_conf, min_chars, cover = _thresholds()
    scale = 720.0 / float(w)
    boxes: list[dict[str, Any]] = []
    for box, text, score in ocr(crop) or []:
        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) + y0 for p in box]
        bx0, by0, bx1, by1 = min(xs), min(ys), max(xs), max(ys)
        bw, bh = bx1 - bx0, by1 - by0
        chars = len(TEXT_CHAR.findall(str(text or "")))
        if float(score) < min_conf or chars < min_chars:
            continue
        if bh * scale < MIN_GLYPH_PX_AT_720 or bw < bh:  # small set dressing / vertical scroll
            continue
        if abs((bx0 + bx1) / 2 / w - 0.5) > float(cover["max_centre_offset_x"]):  # H3 burns centred
            continue
        if (bw * bh) / float(w * h) > float(cover["max_area_fraction"]):
            continue
        boxes.append({"text": str(text), "score": round(float(score), 4),
                      "x0": int(bx0), "y0": int(by0), "x1": int(round(bx1)), "y1": int(round(by1)),
                      "glyph_px_at_720": round(bh * scale, 1)})
    return boxes


# ------------------------------------------------------------------ second, whole-frame pass (E24 review 2026-11-23)
# E24: the band pass above (>= 0.6 score, >= 2 characters, horizontal, centred, glyph >= 40 px at 720) missed garbled
# burns 「不姒伴」「揞哓」 and a placard 「樸花美娇」 at 198 px mid-frame.  The S6 detector (h3_burn_retry.detect) adds
# this pass over the WHOLE frame: score >= 0.4, >= 1 character, any orientation / position, area <= 25 % of the
# frame -- and keeps a box only when it is suspicious: it says (part of) the unit's line, or it is garbled (a
# Chinese character outside GB2312 level 1 -- rare / traditional glyphs H3 invents --, or a low-confidence read of
# >= 2 characters).  Ordinary scene text (a sign of common characters read with confidence) is not flagged.  Raw H3
# clips carry no subtitles / title / end cards of ours; ``exclude`` rects (frame fractions) drop any that would.
# The tail cleaner itself keeps using :func:`find_text_boxes` only (it never inpaints a placard).
SUSPECT_MIN_SCORE = 0.4
SUSPECT_LOW_SCORE = 0.6
SUSPECT_MAX_AREA = 0.25
SUSPECT_LINE_MATCH = 0.6
#: a single rare glyph counts only when it is placard-sized (fraction of the frame height)
SUSPECT_SINGLE_GLYPH_MIN_H = 0.06
CJK_CHAR = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def rare_cjk(text: str) -> list[str]:
    """Chinese characters of ``text`` outside GB2312 level 1 (the 3755 common characters): level-2, traditional-only
    or unencodable glyphs -- what a garbled H3 burn is made of (「姒」「揞」「哓」「樸」)."""
    out = []
    for ch in CJK_CHAR.findall(str(text or "")):
        try:
            code = ch.encode("gb2312")
        except UnicodeEncodeError:
            out.append(ch)
            continue
        if not (0xB0 <= code[0] <= 0xD7):
            out.append(ch)
    return out


def suspect_kind(text: str, score: float, *, lines: list[str] | None = None, lang: str = "zh",
                 height_frac: float = 0.0) -> str | None:
    """LINE_MATCH / GARBLED / LOW_SCORE for a whole-frame OCR read, or None when it is ordinary scene text."""
    chars = TEXT_CHAR.findall(str(text or ""))
    if not chars or float(score) < SUSPECT_MIN_SCORE:
        return None
    if lines and len(chars) >= 2:
        rt = str(_TOOLS.parent / "lines" / "nalu" / "runtime" / "tools")
        if rt not in sys.path:
            sys.path.append(rt)
        import subtitle_text_match as _stm  # noqa: PLC0415
        if any(_stm.best_match(line, [text])[0] >= SUSPECT_LINE_MATCH for line in lines):
            return "LINE_MATCH"
    if str(lang or "zh")[:2] == "zh":
        rare = rare_cjk(text)
        if rare and (len(chars) >= 2 or height_frac >= SUSPECT_SINGLE_GLYPH_MIN_H):
            return "GARBLED"
    if float(score) < SUSPECT_LOW_SCORE and len(chars) >= 2:
        return "LOW_SCORE"
    return None


def find_suspect_text_boxes(image: Any, ocr: OcrFn, *, lines: list[str] | None = None, lang: str = "zh",
                            exclude: list[tuple[float, float, float, float]] | None = None,
                            skip: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Whole-frame OCR boxes that look like model-burned text (see the block comment above); boxes in full-frame
    pixels with ``kind``.  ``skip``: boxes already found by :func:`find_text_boxes` (not reported twice)."""
    h, w = image.shape[:2]
    out: list[dict[str, Any]] = []
    for box, text, score in ocr(image) or []:
        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) for p in box]
        bx0, by0, bx1, by1 = min(xs), min(ys), max(xs), max(ys)
        bw, bh = bx1 - bx0, by1 - by0
        if bw <= 0 or bh <= 0 or (bw * bh) / float(w * h) > SUSPECT_MAX_AREA:
            continue
        cx, cy = (bx0 + bx1) / 2.0, (by0 + by1) / 2.0
        if any(x0 * w <= cx <= x1 * w and y0 * h <= cy <= y1 * h for x0, y0, x1, y1 in exclude or []):
            continue
        if any(b["x0"] <= cx <= b["x1"] and b["y0"] <= cy <= b["y1"] for b in skip or []):
            continue
        glyph = min(bw, bh)  # vertical text: the glyph size is the box width
        kind = suspect_kind(str(text), float(score), lines=lines, lang=lang, height_frac=glyph / float(h))
        if not kind:
            continue
        out.append({"text": str(text), "score": round(float(score), 4), "kind": kind,
                    "x0": int(bx0), "y0": int(by0), "x1": int(round(bx1)), "y1": int(round(by1)),
                    "vertical": bh > bw * 1.5, "glyph_px_at_720": round(glyph * 720.0 / float(w), 1)})
    return out


def _warn(message: str) -> None:
    print(f"[tail_frame_text_clean] WARNING: {message}", file=sys.stderr)


def clean_tail_frame(frame: Path, *, original_copy: Path, sidecar: Path | None = None,
                     ocr: OcrFn | None = None, env: dict[str, str] | None = None) -> dict[str, Any]:
    """Clean ``frame`` in place when burned caption text is found.

    ``original_copy`` receives the untouched frame (``<unit>.orig.png``) only when cleaning
    happened.  ``sidecar`` (optional) gets the JSON report.  Never raises.
    """
    started = time.perf_counter()
    report: dict[str, Any] = {"schema": SCHEMA, "tail_text_cleaned": False, "boxes": []}
    try:  # a re-extracted frame must not inherit a stale original from an earlier clean
        original_copy.unlink(missing_ok=True)
    except OSError:
        pass

    def done(status: str, **extra: Any) -> dict[str, Any]:
        report.update(status=status, elapsed_ms=round((time.perf_counter() - started) * 1000, 1), **extra)
        if sidecar is not None:
            try:
                sidecar.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            except OSError as exc:
                _warn(f"sidecar {sidecar} not written: {exc}")
        return report

    if not enabled(env):
        return done("SKIPPED_OPT_OUT")
    try:
        import cv2  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415
        image = cv2.imread(str(frame), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f"cannot decode {frame}")
        boxes = find_text_boxes(image, ocr or _default_ocr)
        if not boxes:
            return done("CLEAN")
        h, w = image.shape[:2]
        mask = np.zeros((h, w), dtype=np.uint8)
        for b in boxes:
            mask[max(0, b["y0"] - BOX_PAD_PX):min(h, b["y1"] + BOX_PAD_PX + 1),
                 max(0, b["x0"] - BOX_PAD_PX):min(w, b["x1"] + BOX_PAD_PX + 1)] = 255
        cleaned = cv2.inpaint(image, mask, INPAINT_RADIUS, cv2.INPAINT_TELEA)
        shutil.copyfile(frame, original_copy)
        tmp = frame.with_name(frame.stem + ".clean" + frame.suffix)
        if not cv2.imwrite(str(tmp), cleaned):
            tmp.unlink(missing_ok=True)
            raise OSError(f"cannot write {tmp}")
        os.replace(tmp, frame)
    except Exception as exc:  # noqa: BLE001 - fail-open: keep the original frame
        _warn(f"tail-frame text clean skipped for {frame} ({type(exc).__name__}: {exc}); original kept")
        report["boxes"] = []
        return done("FAIL_OPEN", error=f"{type(exc).__name__}: {exc}")
    report["tail_text_cleaned"] = True
    report["boxes"] = boxes
    return done("CLEANED", original=str(original_copy))


def companion_paths(final: Path) -> tuple[Path, Path]:
    """(``<unit>.orig.png``, ``<unit>.tail_text_clean.json``) next to the final tail frame."""
    return final.with_name(f"{final.stem}.orig{final.suffix}"), final.with_name(f"{final.stem}.tail_text_clean.json")


def main(argv: list[str] | None = None) -> int:
    import argparse  # noqa: PLC0415
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("frame", type=Path)
    args = ap.parse_args(argv)
    orig, side = companion_paths(args.frame)
    print(json.dumps(clean_tail_frame(args.frame, original_copy=orig, sidecar=side), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
