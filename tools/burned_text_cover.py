#!/usr/bin/env python3
"""H3_BURNED_TEXT_COVER_V1 (line owner 2026-10-31, E12): cover the dialogue line MiniMax-H3 burns into the picture.

H3 writes the line being spoken into the frame (centred, y 0.67-0.80) even with the TEXT-FREE FRAME rule
first (K143).  Under this policy the episode's captions sit on a dark bar over that band, and the bar is
also shown wherever OCR finds burned text, so the burned line is never readable.  Off by default (line owner
2026-11-19): an episode is covered only when its contract (or the runtime config) explicitly declares
h3_burned_text_cover_policy=H3_BURNED_TEXT_COVER_V1; no episode-number list.

  scan   <video> --out intervals.json            OCR the band, write [[start, end], ...] of burned text and,
                                                 per run, the tight boxes to blur (or flagged for review)
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


def band_for(episode: str | None, cfg: dict[str, Any] | None = None) -> dict[str, float]:
    """The burn band of ONE episode: ``band_by_episode`` when the episode measured its own, else ``band``.

    Where H3 burns the spoken line is a property of the model build and the prompt, not a constant:
    E12/E13 put it at y 0.66-0.81, E14 at y 0.82-0.95 (measured 2026-11-04 on E14_picture_native;
    the E13 band left 9 hits visible at 89.0-90.5 s under the caption bar, and the S7 verify refused
    the episode).  The scan search window stays the policy's own, so a wider band never hides a hit.
    """
    cfg = cfg or policy()
    per = cfg.get("band_by_episode") or {}
    match = re.match(r"E\d+", str(episode or "").strip().upper())
    return dict((per.get(match.group(0)) if match else None) or cfg["band"])


def active(contract: dict[str, Any] | None, *, episode: str | None = None,
           config: dict[str, Any] | None = None) -> bool:
    """Explicit opt-in only (line owner 2026-11-19: the blur cover is ugly; burned text is now retried in S6).

    Active when the episode's generation contract declares ``h3_burned_text_cover_policy`` =
    H3_BURNED_TEXT_COVER_V1, or (contract silent) the runtime config does.  The former episode-number list
    (E12-E14) is gone: it switched the cover on for every series' E12-E14.  ``episode`` is kept for callers."""
    declared = str((contract or {}).get(FIELD) or "").strip().upper()
    if declared:
        return declared == POLICY_ID
    return str((config or {}).get(FIELD) or "").strip().upper() == POLICY_ID


def cjk_count(text: str) -> int:
    return len(CJK.findall(text or ""))


def _cover_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    base = {"margin": 0.012, "min_text_height": 0.02, "max_centre_offset_x": 0.25, "max_area_fraction": 0.12,
            "face_pad": 0.01, "single_glyph_min_height": 0.04, "caption_gap_px": 8}
    return {**base, **(cfg.get("cover") or {})}


def dialogue_like(hit: Hit, section: dict[str, Any], cfg: dict[str, Any],
                  dialogue_chars: set[str] | None = None) -> bool:
    """The OCR hit looks like a burned spoken line, not set dressing.

    Confidence at least ``section.min_confidence``; at least ``section.min_cjk_chars`` CJK characters, or ONE
    large glyph (``cover.single_glyph_min_height``) that is a character of the episode's dialogue when that is
    known; glyph height at least ``cover.min_text_height`` (embroidery, distant signage are smaller); a
    horizontal box (a calligraphy scroll / door couplet reads as a vertical column); centred within
    ``cover.max_centre_offset_x`` of the frame centre (H3 burns the line centred, K143).
    """
    t, text, conf, x0, y0, x1, y1 = hit
    cov = _cover_cfg(cfg)
    n = cjk_count(text)
    h, w = y1 - y0, x1 - x0
    if conf < section["min_confidence"] or h < float(cov["min_text_height"]):
        return False
    if abs((x0 + x1) / 2 - 0.5) > float(cov["max_centre_offset_x"]):
        return False
    if n >= int(section["min_cjk_chars"]):
        return w >= h
    if n == 1 and h >= float(cov["single_glyph_min_height"]):
        glyph = CJK.findall(text)[0]
        return dialogue_chars is None or glyph in dialogue_chars
    return False


def _in_search(hit: Hit, cfg: dict[str, Any]) -> bool:
    s = cfg["scan"]
    return hit[6] >= s["search_y0"] and hit[4] <= s["search_y1"]


def _overlaps(a: tuple[float, float, float, float], b: tuple[float, float, float, float], pad: float = 0.0) -> bool:
    return not (a[2] + pad < b[0] or b[2] + pad < a[0] or a[3] + pad < b[1] or b[3] + pad < a[1])


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


def scan(hits: list[Hit], cfg: dict[str, Any], dialogue_chars: set[str] | None = None) -> list[list[float]]:
    """Intervals of burned dialogue text in the search window (see :func:`dialogue_like`)."""
    s = cfg["scan"]
    times = sorted({h[0] for h in hits if _in_search(h, cfg) and dialogue_like(h, s, cfg, dialogue_chars)})
    return merge_intervals(times, step=1.0 / s["fps"], gap=s["merge_gap_s"], pad=s["pad_s"])


def interval_boxes(hits: list[Hit], cfg: dict[str, Any], intervals: list[list[float]],
                   dialogue_chars: set[str] | None = None,
                   faces: dict[float, list[tuple[float, float, float, float]]] | None = None
                   ) -> list[list[dict[str, Any]]]:
    """Per burned-text run, the boxes to cover: the text OCR read in that run, ``cover.margin`` around it.

    Hits of one run whose boxes touch are one box (one burned line read in several frames / rows); text in two
    places stays two boxes, so a stray hit never grows the cover across the frame.  Each box is
    ``{"x0","y0","x1","y1","action","reason"}`` with action BLUR, or SKIP when it covers more than
    ``cover.max_area_fraction`` of the frame (AREA_OVER_CAP) or touches a face detected in that run
    (OVERLAPS_FACE): a giant blur or a blurred face is worse than the text, so those are flagged for review.
    ``faces``: frame time -> face boxes (frame fractions); None when faces were not measured.
    """
    cov = _cover_cfg(cfg)
    margin, cap, face_pad = float(cov["margin"]), float(cov["max_area_fraction"]), float(cov["face_pad"])
    out: list[list[dict[str, Any]]] = []
    for start, end in intervals:
        clusters: list[list[float]] = []
        for h in sorted(hits):
            if not (start <= h[0] <= end) or not _in_search(h, cfg) or not dialogue_like(h, cfg["scan"], cfg, dialogue_chars):
                continue
            box = [h[3], h[4], h[5], h[6]]
            for c in clusters:
                if _overlaps(tuple(c), tuple(box), margin):
                    c[:] = [min(c[0], box[0]), min(c[1], box[1]), max(c[2], box[2]), max(c[3], box[3])]
                    break
            else:
                clusters.append(box)
        # unions can make clusters touch each other: merge until stable
        merged = True
        while merged:
            merged = False
            for i in range(len(clusters)):
                for j in range(i + 1, len(clusters)):
                    a, b = clusters[i], clusters[j]
                    if _overlaps(tuple(a), tuple(b), margin):
                        clusters[i] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                        clusters.pop(j)
                        merged = True
                        break
                if merged:
                    break
        run_faces = [f for t, fs in (faces or {}).items() if start <= t <= end for f in fs]
        boxes = []
        for x0, y0, x1, y1 in clusters:
            box = {"x0": max(0.0, x0 - margin), "y0": max(0.0, y0 - margin),
                   "x1": min(1.0, x1 + margin), "y1": min(1.0, y1 + margin)}
            box = {k: round(v, 4) for k, v in box.items()}
            area = (box["x1"] - box["x0"]) * (box["y1"] - box["y0"])
            rect = (box["x0"], box["y0"], box["x1"], box["y1"])
            if area > cap:
                box.update(action="SKIP", reason="AREA_OVER_CAP", area=round(area, 4))
            elif any(_overlaps(rect, tuple(f), face_pad) for f in run_faces):
                box.update(action="SKIP", reason="OVERLAPS_FACE", area=round(area, 4))
            else:
                box.update(action="BLUR", reason="TEXT_BOX", area=round(area, 4))
            boxes.append(box)
        out.append(boxes)
    return out


def caption_at(captions: list[dict[str, Any]], t: float) -> str:
    return next((str(c.get("text") or "") for c in captions
                 if float(c.get("start", 0)) <= t <= float(c.get("end", 0))), "")


def reads_as_part_of(caption: str, read: str, min_ratio: float) -> bool:
    """True when ``read`` is one stretch of ``caption``, allowing for OCR misreads.

    A long caption is drawn on several rows and OCR returns one hit per row, so a hit is a PIECE of the
    caption and a whole-caption ratio is low by construction; one misread character then also defeats the
    exact-substring test (fleet 2026-11-14 E12 S7: the row 「看着就是家里横惯了的二世祖，」 of a 47-character
    caption read as 「…工世祖」/「…云世祖」, ratio 0.43, and 「呜呜」 read as 「呜鸣」, ratio 0.17 -- five hits,
    all our own caption on the opaque bar, and S7 stopped).  Compare against every window of the same length.
    """
    cap = "".join(CJK.findall(caption or ""))
    if not read or not cap:
        return False
    if read in cap:
        return True
    n = min(len(read), len(cap))
    return any(difflib.SequenceMatcher(None, cap[i:i + n], read).ratio() >= min_ratio
               for i in range(len(cap) - n + 1))


def _caption_rect_at(captions: list[dict[str, Any]], t: float, half: float) -> list[tuple[float, float]]:
    """Vertical extents (frame fractions) where build_burnin_subtitles drew the captions on screen around ``t``."""
    out = []
    for c in captions:
        if c.get("y0") is None or c.get("y1") is None:
            continue
        if float(c.get("start", 0)) - half <= t <= float(c.get("end", 0)) + half:
            out.append((float(c["y0"]), float(c["y1"])))
    return out


def verify(hits: list[Hit], captions: list[dict[str, Any]], cfg: dict[str, Any],
           *, episode: str | None = None,
           covered: list[tuple[float, float, list[dict[str, Any]]]] | None = None) -> dict[str, Any]:
    """Every CJK hit must sit inside the bar and read as the caption on screen at that moment.

    Hits that are not dialogue-like (small, vertical, off-centre: :func:`dialogue_like`) are ignored
    (NOT_DIALOGUE_TEXT).  A hit inside a box the scan flagged for review (``covered`` SKIP boxes: over the area
    cap / on a face) is reported under ``flagged_for_review`` and does not fail.  A hit that reads as the caption
    on screen and sits where build_burnin_subtitles drew it (rows ``y0``/``y1``) is our caption."""
    v, band = cfg["verify"], band_for(episode, cfg)
    # The rule is about the spoken line H3 burns into the picture (K143), not about every character in frame:
    # E13 S7 stopped on 8 hits that were the meaningless characters painted on VU-014's gate plaque and door
    # couplet at y≈0.00-0.14 (reported as P2 at Q2, where the period/anachronism OCR gate owns scene signage).
    # So a hit outside the bar counts only when it sits within ``dialogue_band_pad`` of the burn band, or when it
    # reads like the caption on screen at that moment (a burned caption the bar failed to cover).
    pad = float(v.get("dialogue_band_pad", 0.10))
    caption_slack = float(v.get("caption_on_screen_slack", 0.04))
    outside_candidates, mismatched, flagged, not_dialogue = [], [], [], []
    skip_boxes = [(s0, e0, b) for s0, e0, boxes in (covered or []) for b in boxes if b.get("action") == "SKIP"]
    for hit in hits:
        t, text, conf, x0, y0, x1, y1 = hit
        if conf < v["min_confidence"] or cjk_count(text) < v["min_cjk_chars"]:
            continue
        if not dialogue_like(hit, v, cfg):
            not_dialogue.append({"t": round(t, 2), "text": text, "box": [round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3)],
                                 "reason": "NOT_DIALOGUE_TEXT"})
            continue
        cx_, cy_ = (x0 + x1) / 2, (y0 + y1) / 2
        flag = next((b for s0, e0, b in skip_boxes if s0 <= t <= e0
                     and b["x0"] <= cx_ <= b["x1"] and b["y0"] <= cy_ <= b["y1"]), None)
        if flag is not None:
            flagged.append({"t": round(t, 2), "text": text, "reason": flag.get("reason"),
                            "box": [flag["x0"], flag["y0"], flag["x1"], flag["y1"]]})
            continue
        cy, cx = (y0 + y1) / 2, (x0 + x1) / 2
        inside = band["y0"] <= cy <= band["y1"] and band["x0"] <= cx <= band["x1"]
        row = {"t": round(t, 2), "text": text, "box": [round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3)]}
        if not inside:
            outside_candidates.append(row)
            continue
        # A sample at fps F is placed within half a step of t, so a frame read at t may show the caption that
        # starts or ends within that half step (E12 first real run: 38 of our own captions read 0.01-0.2 s
        # before their listed start).  Any caption on screen inside +/- half a step counts; a burned line with
        # no caption anywhere near it still fails.
        half = 0.5 / float(v["fps"])
        expected = caption_at(captions, t)
        candidates = [c for c in dict.fromkeys(caption_at(captions, t + d) for d in (-half, 0.0, half)) if c] or [""]
        read = "".join(CJK.findall(text))
        ratio = max(difflib.SequenceMatcher(None, "".join(CJK.findall(c)), read).ratio() for c in candidates)
        if ratio < v["inside_bar_min_similarity"] and not any(
                reads_as_part_of(c, read, v["inside_bar_min_similarity"]) for c in candidates):
            mismatched.append({**row, "caption_on_screen": expected, "similarity": round(ratio, 2)})
    outside, ignored = [], []
    half = 0.5 / float(v["fps"])
    for row in outside_candidates:
        t = row["t"]
        candidates = [c for c in dict.fromkeys(caption_at(captions, t + d) for d in (-half, 0.0, half)) if c] or [""]
        read = "".join(CJK.findall(row["text"]))
        # OCR frequently reads only part of our own caption (E13 96.5-100.5 s: the last three characters of a 12-character caption),
        # so a read that is a contiguous piece of the caption on screen counts the same as a whole match.
        looks_like_caption = any(
            difflib.SequenceMatcher(None, "".join(CJK.findall(c)), read).ratio() >= v["inside_bar_min_similarity"]
            or (read and read in "".join(CJK.findall(c)))
            or (read and any(read[i:j] in "".join(CJK.findall(c))
                             for i in range(len(read)) for j in range(len(read), i + 1, -1)))
            for c in candidates)
        # Our own caption, drawn by this pipeline above the bar, also sits outside the band (E13 2026-11-01: the
        # transparent-plate caption reads at y 0.81-0.85, 0.01 below the band edge).  That is not a burned line:
        # the bar's job is to hide what H3 burned in, and the caption on screen is the line we put there ourselves.
        # Only where our caption can actually be: on or right at the band edge.  The same words higher up the
        # frame are a burned copy of the line (knowledge-loop CASE_001 control), not the caption we drew.
        centre = (row["box"][1] + row["box"][3]) / 2
        at_caption_place = (band["y0"] - caption_slack) <= centre <= (band["y1"] + caption_slack)
        # 2026-11-19: our caption keeps its normal place and moves clear of a blurred box, so the report row
        # says where it was drawn; a caption read there is ours
        drawn = _caption_rect_at(captions, t, half)
        if drawn:
            at_caption_place = any(y0c - caption_slack <= centre <= y1c + caption_slack for y0c, y1c in drawn)
        if looks_like_caption and at_caption_place:
            ignored.append({**row, "reason": "CAPTION_ON_SCREEN"})
            continue
        near_band = (band["y0"] - pad) <= (row["box"][1] + row["box"][3]) / 2 <= (band["y1"] + pad)
        (outside if near_band else ignored).append(
            row if near_band else {**row, "reason": "AWAY_FROM_BURN_BAND"})
    status = "PASS" if not outside and not mismatched else "FAIL"
    return {"schema": "qingshan.h3_burned_text_cover_verification.v1", "policy_id": POLICY_ID, "status": status,
            "text_outside_bar": outside, "text_inside_bar_not_the_caption": mismatched,
            "ignored_non_dialogue_text": ignored + not_dialogue, "flagged_for_review": flagged,
            "rule": "no CJK dialogue text outside the caption bar; text inside the bar must be the caption on "
                    "screen; scene signage away from the burn band is the period/anachronism gate's business"}


def load_covered(path: Path | None) -> list[tuple[float, float, list[dict[str, Any]]]]:
    """(start, end, boxes) per burned-text run of a scan output; [] for none or a scan without boxes (an older
    engine's whole-band scan is never replayed: the S7 caller always re-scans)."""
    if not path or not Path(path).is_file():
        return []
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    intervals, boxes = data.get("intervals") or [], data.get("boxes")
    if not isinstance(boxes, list) or len(boxes) != len(intervals):
        return []
    return [(float(s), float(e), [dict(b) for b in bs]) for (s, e), bs in zip(intervals, boxes)]


def contract_dialogue_chars(path: Path | None) -> set[str] | None:
    """CJK characters of the episode's scripted dialogue (generation contract), or None when unknown."""
    if not path or not Path(path).is_file():
        return None
    try:
        contract = json.loads(Path(path).read_text(encoding="utf-8"))
    except ValueError:
        return None
    rows = (contract.get("audio_contract") or {}).get("dialogue_units") or []
    chars = {ch for row in rows for ch in CJK.findall(str(row.get("text") or ""))}
    return chars or None


def face_boxes(video: Path, times: list[float]) -> dict[float, list[tuple[float, float, float, float]]]:
    """Face boxes (frame fractions) at ``times`` of ``video``: InsightFace when installed, else OpenCV Haar
    (the S7 lock-off detector).  Local and free; {} when the frame or a detector is unavailable."""
    if not Path(video).is_file() or not times:
        return {}
    try:
        import cv2  # noqa: PLC0415
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lines/nalu/runtime/tools"))
        from clip_lockoff_stabilize import detect_faces  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return {}
    out: dict[float, list[tuple[float, float, float, float]]] = {}
    cap = cv2.VideoCapture(str(video))
    try:
        for t in times:
            cap.set(cv2.CAP_PROP_POS_MSEC, float(t) * 1000.0)
            ok, frame = cap.read()
            if not ok:
                continue
            h, w = frame.shape[:2]
            out[round(float(t), 3)] = [(x0 / w, y0 / h, x1 / w, y1 / h) for x0, y0, x1, y1 in detect_faces(frame)]
    finally:
        cap.release()
    return out


def main(argv: list[str] | None = None, *, ocr: Callable[[Path, float], list[Hit]] = ocr_frames,
         faces: Callable[[Path, list[float]], dict[float, list[tuple[float, float, float, float]]]] = face_boxes) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("scan"); sp.add_argument("video", type=Path); sp.add_argument("--out", type=Path, required=True)
    sp.add_argument("--episode", default=None, help="episode (its band only bounds where captions are expected)")
    sp.add_argument("--contract", type=Path, default=None,
                    help="generation contract: a single large glyph counts only when it is a dialogue character")
    vp = sub.add_parser("verify"); vp.add_argument("video", type=Path)
    vp.add_argument("--captions", type=Path, required=True, help="build_burnin_subtitles report (rows: text/start/end)")
    vp.add_argument("--out", type=Path, required=True)
    vp.add_argument("--episode", default=None,
                    help="episode whose own band applies (band_by_episode), e.g. E14")
    vp.add_argument("--intervals", type=Path, default=None,
                    help="the scan output: text inside a box it flagged for review is reported, not failed")
    a = ap.parse_args(argv)
    cfg = policy()
    if a.cmd == "scan":
        hits = ocr(a.video, cfg["scan"]["fps"])
        chars = contract_dialogue_chars(a.contract)
        intervals = scan(hits, cfg, chars)
        boxes = interval_boxes(hits, cfg, intervals, chars)
        # faces only where a box would be blurred: 3 frames per such run (start, middle, end)
        times = sorted({round(t, 3) for (s0, e0), bs in zip(intervals, boxes) if any(b["action"] == "BLUR" for b in bs)
                        for t in (s0 + 0.1, (s0 + e0) / 2, max(s0, e0 - 0.1))})
        face_map = faces(a.video, times) if times else {}
        boxes = interval_boxes(hits, cfg, intervals, chars, faces=face_map)
        flagged = [{"interval": iv, **b} for iv, bs in zip(intervals, boxes) for b in bs if b["action"] == "SKIP"]
        out = {"schema": "qingshan.h3_burned_text_intervals.v2_tight_boxes", "policy_id": POLICY_ID,
               "video": str(a.video), "intervals": intervals, "seconds": round(sum(e - s for s, e in intervals), 3),
               "boxes": boxes, "flagged_for_review": flagged, "faces_checked": bool(face_map),
               "cover": _cover_cfg(cfg)}
    else:
        rows = json.loads(a.captions.read_text(encoding="utf-8")).get("rows") or []
        out = {**verify(ocr(a.video, cfg["verify"]["fps"]), rows, cfg, episode=a.episode,
                        covered=load_covered(a.intervals)),
               "video": str(a.video), "episode": getattr(a, "episode", None),
               "band": band_for(getattr(a, "episode", None), cfg)}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: out[k] for k in out if k in ("status", "intervals", "seconds", "flagged_for_review")},
                     ensure_ascii=False)[:400])
    return 0 if out.get("status", "PASS") == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
