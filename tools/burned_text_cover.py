#!/usr/bin/env python3
"""H3_BURNED_TEXT_COVER_V1 (line owner 2026-10-31, E12): cover the dialogue line MiniMax-H3 burns into the picture.

H3 writes the line being spoken into the frame (centred, y 0.67-0.80) even with the TEXT-FREE FRAME rule
first (K143).  Under this policy the episode's captions sit on a dark bar over that band, and the bar is
also shown wherever OCR finds burned text, so the burned line is never readable.  Never retroactive: an
episode is covered only when its contract declares h3_burned_text_cover_policy=H3_BURNED_TEXT_COVER_V1 or
configs/H3_BURNED_TEXT_COVER_V1.json lists it.

  scan   <video> --out intervals.json            OCR the band, write [[start, end], ...] of burned text
  verify <video> --captions report.json --out    OCR the finished picture: FAIL on CJK text outside the bar,
                                                 or inside it that does not match the caption on screen
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

POLICY_ID = "H3_BURNED_TEXT_COVER_V1"
FIELD = "h3_burned_text_cover_policy"
POLICY_PATH = Path(__file__).resolve().parents[1] / "configs" / "H3_BURNED_TEXT_COVER_V1.json"
CJK = re.compile(r"[一-鿿]")

#: one OCR hit: (time_s, text, confidence, x0, y0, x1, y1) with coordinates as frame fractions
Hit = tuple[float, str, float, float, float, float, float]


def policy() -> dict[str, Any]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def active(contract: dict[str, Any] | None, *, episode: str | None = None) -> bool:
    declared = str((contract or {}).get(FIELD) or "").strip().upper()
    if declared:
        return declared == POLICY_ID
    match = re.match(r"E\d+", str(episode or (contract or {}).get("episode") or "").strip().upper())
    return bool(match) and match.group(0) in set(policy().get("enabled_episodes") or [])


def cjk_count(text: str) -> int:
    return len(CJK.findall(text or ""))


def merge_intervals(times: list[float], *, step: float, gap: float, pad: float) -> list[list[float]]:
    """Frame times with a hit -> padded [start, end] runs; runs closer than ``gap`` are joined."""
    runs: list[list[float]] = []
    for t in sorted(times):
        if runs and t - runs[-1][1] <= gap + step:
            runs[-1][1] = t
        else:
            runs.append([t, t])
    return [[round(max(0.0, s - pad), 3), round(e + step + pad, 3)] for s, e in runs]


def ocr_frames(video: Path, fps: float) -> list[Hit]:
    """RapidOCR over ``fps`` frames per second of ``video``; boxes as frame fractions."""
    from PIL import Image
    from rapidocr_onnxruntime import RapidOCR
    engine = RapidOCR()
    hits: list[Hit] = []
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(video), "-vf", f"fps={fps}",
                        f"{tmp}/f_%05d.png"], check=True)
        for frame in sorted(Path(tmp).glob("f_*.png")):
            t = (int(frame.stem[2:]) - 1) / fps
            w, h = Image.open(frame).size
            for box, text, conf in engine(str(frame))[0] or []:
                xs, ys = [p[0] for p in box], [p[1] for p in box]
                hits.append((t, str(text), float(conf), min(xs) / w, min(ys) / h, max(xs) / w, max(ys) / h))
    return hits


def scan(hits: list[Hit], cfg: dict[str, Any]) -> list[list[float]]:
    """Intervals of burned dialogue text in the search band (>= min_cjk_chars CJK at min_confidence)."""
    s = cfg["scan"]
    times = sorted({t for t, text, conf, _x0, y0, _x1, y1 in hits
                    if conf >= s["min_confidence"] and cjk_count(text) >= s["min_cjk_chars"]
                    and y1 >= s["search_y0"] and y0 <= s["search_y1"]})
    return merge_intervals(times, step=1.0 / s["fps"], gap=s["merge_gap_s"], pad=s["pad_s"])


def caption_at(captions: list[dict[str, Any]], t: float) -> str:
    return next((str(c.get("text") or "") for c in captions
                 if float(c.get("start", 0)) <= t <= float(c.get("end", 0))), "")


def verify(hits: list[Hit], captions: list[dict[str, Any]], cfg: dict[str, Any]) -> dict[str, Any]:
    """Every CJK hit must sit inside the bar and read as the caption on screen at that moment."""
    v, band = cfg["verify"], cfg["band"]
    outside, mismatched = [], []
    for t, text, conf, x0, y0, x1, y1 in hits:
        if conf < v["min_confidence"] or cjk_count(text) < v["min_cjk_chars"]:
            continue
        cy, cx = (y0 + y1) / 2, (x0 + x1) / 2
        inside = band["y0"] <= cy <= band["y1"] and band["x0"] <= cx <= band["x1"]
        row = {"t": round(t, 2), "text": text, "box": [round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3)]}
        if not inside:
            outside.append(row)
            continue
        expected = caption_at(captions, t)
        ratio = difflib.SequenceMatcher(None, "".join(CJK.findall(expected)), "".join(CJK.findall(text))).ratio()
        if ratio < v["inside_bar_min_similarity"] and not "".join(CJK.findall(text)) in expected:
            mismatched.append({**row, "caption_on_screen": expected, "similarity": round(ratio, 2)})
    status = "PASS" if not outside and not mismatched else "FAIL"
    return {"schema": "qingshan.h3_burned_text_cover_verification.v1", "policy_id": POLICY_ID, "status": status,
            "text_outside_bar": outside, "text_inside_bar_not_the_caption": mismatched,
            "rule": "no CJK text outside the caption bar; text inside the bar must be the caption on screen"}


def main(argv: list[str] | None = None, *, ocr: Callable[[Path, float], list[Hit]] = ocr_frames) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("scan"); sp.add_argument("video", type=Path); sp.add_argument("--out", type=Path, required=True)
    vp = sub.add_parser("verify"); vp.add_argument("video", type=Path)
    vp.add_argument("--captions", type=Path, required=True, help="build_burnin_subtitles report (rows: text/start/end)")
    vp.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    cfg = policy()
    if a.cmd == "scan":
        intervals = scan(ocr(a.video, cfg["scan"]["fps"]), cfg)
        out = {"schema": "qingshan.h3_burned_text_intervals.v1", "policy_id": POLICY_ID, "video": str(a.video),
               "intervals": intervals, "seconds": round(sum(e - s for s, e in intervals), 3)}
    else:
        rows = json.loads(a.captions.read_text(encoding="utf-8")).get("rows") or []
        out = {**verify(ocr(a.video, cfg["verify"]["fps"]), rows, cfg), "video": str(a.video)}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: out[k] for k in out if k in ("status", "intervals", "seconds")}, ensure_ascii=False)[:400])
    return 0 if out.get("status", "PASS") == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
