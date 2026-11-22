#!/usr/bin/env python3
"""Local audio/visual evidence pack for the final audience review (line owner 2026-11-19, video-native final review).

Benchmark 2026-11-19 (《摄政王她又来找茬了》 E17-E19, ~/Desktop/终审测试/REPORT.md): a video model (Gemini Flash,
checklist pass) catches most model-burned text and letterboxed shots, but it cannot hear clipped line tails or
music fragments reliably (recall <= 2/16 and <= 1/9).  Those are MEASURED here, for free, on the decoded final MP4,
and handed to the video reviewer and to the Codex reviewer as suspects with timestamps to confirm or dismiss.

One decode pass at ``SCAN_FPS`` (4 fps) feeds:

  burned_text     cross-frame RapidOCR; our caption (bottom band, caption glyph height, the ASS geometry) is
                  separated from model-burned text (bigger glyphs, outside our band / bigger than our glyph);
                  burned runs whose characters are not in the ASR / caption text are flagged GARBLED
  subtitle_wrap   the ASS wrap check (nalu_qa_defect_checklist.measure_subtitle_wrap, reused) + a pixel check for
                  a short lone row under a one-row caption (a lone 「！」 is not read by OCR)
  letterbox       per-shot top/bottom (and left/right) dark-band detection: a 16:9 shot inside the 9:16 episode
  lookalike_cast  live action: InsightFace at 2 fps, average-linkage clusters, centroid similarity matrix, two
                  similar faces in ONE frame, and a line-up sheet (JPEG, one face per cluster); anime: NOT_APPLICABLE
and one audio decode (16 kHz mono) feeds:

  dialogue_tail   per cut: silence gap between the last voiced frame and the cut, and the voice-band energy over
                  the floor in the last 50 ms (rule C2: gap < 0.12 s, or >= 8 dB above the floor with the line
                  running into the cut)
  bgm             the S7 BGM plan / audio-bed segments when nalu_qa_defect_checklist measured them; otherwise a
                  chroma-peakiness music map per shot and the music runs that start AND stop on cuts within a
                  shot or two

Authority: ADVISORY.  Every component is best effort (an error leaves ``{"error": ...}``), nothing here gates.
The pack is written next to the review request and SHA-bound under ``evidence.av_evidence_pack``.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))

SCHEMA = "nalu.av_evidence_pack.v1"
AUTHORITY = "ADVISORY_NOT_A_GATE: leads for the final reviewers, measured locally for free"

SCAN_FPS = 4.0
FACE_EVERY = 2                 # faces on every 2nd scanned frame (2 fps)
SR = 16000
HOP = 160                      # 10 ms
NFFT = 1024

# --- caption / burned-text geometry (fractions of the frame; build_burnin_subtitles: 720x1280, MarginV 170,
#     bottom-centre, glyph ~40 px -> two rows at y ~996-1043 / 1051-1095)
CAPTION_BAND_Y = (0.770, 0.866)     # centre-y range of our caption rows
CAPTION_MAX_H = 0.0453              # our glyph box height (58 px of 1280)
BURNED_MIN_H = 0.039                # model-burned glyphs are 55-80 px tall (>= 50 px of 1280)
BURNED_MAX_H = 0.078                # a single big glyph (H3's 「能」) up to 100 px
OCR_MIN_SCORE = 0.75
OCR_LOW_SCORE = 0.60                # 0.60-0.75 big-glyph reads count as garbled candidates
LOWCONF_MARK = "?"
TITLE_CARD_S = 3.0                  # opening title card (centre band) is ours
TITLE_CARD_Y = (0.28, 0.42)
END_CARD_S = 3.6                    # tail card is ours
BURNED_MERGE_GAP_S = 0.5
GARBLED_MIN_READS = 2
GARBLED_UNKNOWN_FRAC = 0.5          # share of a read's CJK characters found in no ASR / caption text
CJK = re.compile(r"[一-鿿]")
PUNCT = "，。！？、…；：,.!?"

# --- lone caption row (pixel): bright stroke pixels under a one-row caption, narrower than this many glyphs
LONE_ROW_MAX_GLYPHS = 1.6
LONE_ROW_LUMA = 200
LONE_ROW_OUTLINE_LUMA = 50

# --- letterbox
DARK_LUMA = 24
DARK_ROW_FRAC = 0.95
LETTERBOX_MIN_BAND = 0.03           # each band >= 3 % of the frame height (38 px of 1280)
LETTERBOX_GAP_TOLERANCE = 0.10      # a caption may interrupt the bottom band (<= 10 % of the height)
LETTERBOX_FRAME_SHARE = 0.6         # share of a shot's frames that must show the same bands
LETTERBOX_BAND_JITTER = 0.008
PORTRAIT_9_16 = 9 / 16
ASPECT_TOLERANCE = 0.03             # H3 768x1344 is 1.6 % off 9:16

# --- dialogue tail (C2)
TAIL_WINDOW_S = 1.5
TAIL_FLOOR_PCT = 15
EPISODE_FLOOR_PCT = 10
TAIL_VOICED_DB = 12.0
TAIL_GAP_S = 0.12
TAIL_LEVEL_DB = 8.0
TAIL_SPAN_S = 0.10                  # a line whose end is within this of the cut (or after it) runs into it

# --- music heuristic (C6), calibrated on E17-E19 (REPORT.md fixtures)
MUSIC_BAND = (80.0, 2000.0)
MUSIC_SMOOTH_FRAMES = 30
MUSIC_PEAK_MIN = 0.33
MUSIC_PEAK_REL = 1.4
MUSIC_FRAGMENT_MAX_SHOTS = 2
MUSIC_FRAGMENT_MAX_S = 9.5

# --- faces
FACE_MIN_W = 40
FACE_MIN_SCORE = 0.6
FACE_LINK = 0.40
FACE_MAX = 700
LOOKALIKE_SAME_FRAME = 0.45
LOOKALIKE_SAME_FRAME_MIN_HITS = 2
LOOKALIKE_CLUSTER = 0.60


def _r(x: Any, n: int = 2) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, n) if v == v else None


# ------------------------------------------------------------------------------------------------ media helpers
def ffmpeg_bin() -> str:
    return os.environ.get("FFMPEG_BIN") or shutil.which("ffmpeg") or "ffmpeg"


def ffprobe_bin() -> str:
    return os.environ.get("FFPROBE_BIN") or shutil.which("ffprobe") or "ffprobe"


def probe(video: Path) -> dict[str, Any]:
    run = subprocess.run([ffprobe_bin(), "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,avg_frame_rate:format=duration", "-of", "json", str(video)],
                         capture_output=True, text=True, timeout=60)
    data = json.loads(run.stdout or "{}")
    stream = (data.get("streams") or [{}])[0]
    return {"width": int(stream.get("width") or 0), "height": int(stream.get("height") or 0),
            "duration": float((data.get("format") or {}).get("duration") or 0.0)}


def iter_frames(video: Path, fps: float, width: int, height: int) -> Iterable[tuple[float, Any]]:
    """(t, BGR uint8 frame) at ``fps`` through one ffmpeg pipe."""
    import numpy as np  # noqa: PLC0415
    proc = subprocess.Popen([ffmpeg_bin(), "-v", "error", "-i", str(video), "-vf", f"fps={fps}",
                             "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], stdout=subprocess.PIPE)
    size = width * height * 3
    index = 0
    try:
        while True:
            buf = proc.stdout.read(size) if proc.stdout else b""
            if len(buf) < size:
                break
            yield index / fps, np.frombuffer(buf, np.uint8).reshape(height, width, 3)
            index += 1
    finally:
        if proc.stdout:
            proc.stdout.close()
        proc.wait(timeout=60)


def decode_audio(video: Path, sr: int = SR) -> Any:
    import numpy as np  # noqa: PLC0415
    raw = subprocess.run([ffmpeg_bin(), "-v", "error", "-i", str(video), "-ac", "1", "-ar", str(sr),
                          "-f", "s16le", "-"], capture_output=True, timeout=600).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0


def detect_cuts(video: Path, threshold: float = 10.0) -> list[float]:
    """ffmpeg scdet cut times (fallback when no measured shots are given)."""
    run = subprocess.run([ffmpeg_bin(), "-v", "info", "-i", str(video), "-vf", f"scdet=threshold={threshold}",
                          "-an", "-f", "null", "-"], capture_output=True, text=True, timeout=1200)
    return sorted({round(float(m.group(1)), 3) for m in re.finditer(r"lavfi\.scd\.time:\s*([\d.]+)", run.stderr)})


def cuts_from_shots(shots: list[dict[str, Any]] | None) -> list[float]:
    ends = sorted({round(float(s["end_seconds"]), 3) for s in shots or [] if s.get("end_seconds") is not None})
    return ends[:-1] if ends else []


def stft_power(x: Any) -> tuple[Any, Any]:
    """|STFT|^2 (hann, NFFT, HOP), frequencies; frame k is centred at k*HOP/SR seconds."""
    import numpy as np  # noqa: PLC0415
    pad = np.pad(x, (NFFT // 2, NFFT // 2))
    count = max(1, 1 + (len(pad) - NFFT) // HOP)
    window = np.hanning(NFFT).astype(np.float32)
    power = np.empty((NFFT // 2 + 1, count), np.float32)
    step = 2048
    for a in range(0, count, step):
        b = min(count, a + step)
        idx = np.arange(a, b)[:, None] * HOP + np.arange(NFFT)[None, :]
        power[:, a:b] = (np.abs(np.fft.rfft(pad[idx] * window, axis=1)) ** 2).T
    return power, np.fft.rfftfreq(NFFT, 1.0 / SR)


# ------------------------------------------------------------------------------------------------ ASR / captions
def asr_rows(asr: Any) -> list[dict[str, Any]]:
    """Line windows {start, end, text, words?} from the final-cut ASR windows (list or {segments|windows})."""
    rows_in = asr if isinstance(asr, list) else ((asr or {}).get("segments") or (asr or {}).get("windows") or []
                                                 if isinstance(asr, dict) else [])
    out = []
    for row in rows_in:
        if not isinstance(row, dict) or str(row.get("presence") or "") == "VOICE_OVER":
            continue
        s, e = _r(row.get("start"), 3), _r(row.get("end"), 3)
        if s is None or e is None:
            continue
        words = []
        for w in row.get("words") or []:
            ws, we = _r(w.get("s", w.get("start")), 3), _r(w.get("e", w.get("end")), 3)
            if ws is not None and we is not None:
                words.append((ws, we))
        out.append({"start": s, "end": e, "text": str(row.get("text") or ""), "words": words})
    return out


_ASS_TIME = re.compile(r"(\d+):(\d{2}):(\d{2}(?:\.\d+)?)")


def ass_captions(ass_text: str | None) -> list[dict[str, Any]]:
    out = []
    for line in (ass_text or "").splitlines():
        if not line.startswith("Dialogue:"):
            continue
        parts = line.split(",", 9)
        if len(parts) < 10:
            continue
        times = [_ASS_TIME.fullmatch(p.strip()) for p in parts[1:3]]
        if not all(times):
            continue
        a, b = (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) for m in times)
        text = re.sub(r"\{[^}]*\}", "", parts[9])
        out.append({"start": a, "end": b, "rows": text.split("\\N"), "text": text.replace("\\N", "")})
    return out


# ------------------------------------------------------------------------------------------------ frame analysis
def box_geometry(box: Any, width: int, height: int) -> tuple[float, float, float, float]:
    xs, ys = [p[0] for p in box], [p[1] for p in box]
    return min(xs) / width, min(ys) / height, max(xs) / width, max(ys) / height


def classify_box(t: float, text: str, score: float, geom: tuple[float, float, float, float], duration: float,
                 caption_text_at: Callable[[float], str] | None = None) -> str:
    """OURS | BURNED | TITLE_CARD | END_CARD | SCENE_TEXT | LOW_CONFIDENCE."""
    x0, y0, x1, y1 = geom
    h, yc = y1 - y0, (y0 + y1) / 2
    n = len(CJK.findall(text))
    if n < 1 or score < OCR_LOW_SCORE:
        return "LOW_CONFIDENCE"
    if t < TITLE_CARD_S and TITLE_CARD_Y[0] < yc < TITLE_CARD_Y[1]:
        return "TITLE_CARD"
    if duration and t > duration - END_CARD_S:
        return "END_CARD"
    if CAPTION_BAND_Y[0] <= yc <= CAPTION_BAND_Y[1] and h <= CAPTION_MAX_H:
        return "OURS"
    if h >= BURNED_MIN_H and (n >= 2 or h < BURNED_MAX_H * 1.3):
        # big glyphs the OCR reads with low confidence are typically garbled model glyphs
        return "BURNED" if score >= OCR_MIN_SCORE else ("BURNED_LOW_CONFIDENCE" if n >= 2 else "LOW_CONFIDENCE")
    if score < OCR_MIN_SCORE:
        return "LOW_CONFIDENCE"
    return "SCENE_TEXT"


#: the caption band where a burned copy of a line can stack with ours (h3_burn_retry.SUBTITLE_BAND, a bit lower)
STACK_BAND_Y = (0.55, 0.97)
STACK_MIN_GAP = 0.02            # two rows at least this far apart vertically (one row split in two boxes is not two)
STACK_MERGE_GAP_S = 0.6
STACK_MIN_READS = 2


def stacked_rows(boxes: list[tuple[Any, str, float]], width: int, height: int) -> dict[str, Any] | None:
    """One frame's OCR boxes -> the most similar pair of caption-band rows saying the same line (JA-01 E07 VU-004
    2026-11-22: H3's burned 「言わないでくださいまし！」 under our copy of it), else None."""
    import subtitle_text_match as _stm  # noqa: PLC0415 -- same directory
    rows = []
    for box, text, score in boxes or []:
        if score < OCR_LOW_SCORE:
            continue
        x0, y0, x1, y1 = box_geometry(box, width, height)
        yc = (y0 + y1) / 2
        if STACK_BAND_Y[0] <= yc <= STACK_BAND_Y[1]:
            rows.append((yc, str(text)))
    return _stm.stacked_duplicate(rows, min_gap=STACK_MIN_GAP) if len(rows) >= 2 else None


def stacked_runs(hits: list[tuple[float, dict[str, Any]]]) -> list[dict[str, Any]]:
    """Per-frame stacked-duplicate hits -> runs {start, end, reads, texts, similarity} of >= STACK_MIN_READS reads."""
    out: list[dict[str, Any]] = []
    for t, hit in sorted(hits, key=lambda h: h[0]):
        if out and t - out[-1]["_last"] <= STACK_MERGE_GAP_S:
            run = out[-1]
            run["_last"] = t
            run["reads"] += 1
            run["similarity"] = max(run["similarity"], hit["similarity"])
            continue
        out.append({"start": round(t, 2), "_last": t, "reads": 1, "texts": hit["texts"],
                    "ys": hit["ys"], "similarity": hit["similarity"]})
    rows = []
    for run in out:
        if run["reads"] >= STACK_MIN_READS:
            last = run.pop("_last")
            rows.append({**run, "end": round(last + 1.0 / SCAN_FPS, 2)})
    return rows


def lone_row_pixels(gray: Any, caption_rows: list[tuple[float, float, float, float]]) -> dict[str, Any] | None:
    """Under a ONE-row caption: bright stroke pixels in the next row slot narrower than LONE_ROW_MAX_GLYPHS glyphs
    (a lone 「！」 / one-character row that OCR does not read)."""
    import numpy as np  # noqa: PLC0415
    if len(caption_rows) != 1:
        return None
    height, width = gray.shape[:2]
    x0, y0, x1, y1 = caption_rows[0]
    glyph = (y1 - y0) * height
    a, b = int(y1 * height + 0.15 * glyph), int(y1 * height + 1.35 * glyph)
    if b >= height or glyph <= 0:
        return None
    import cv2  # noqa: PLC0415
    band = np.ascontiguousarray(gray[a:b]).astype(np.uint8)
    dark = cv2.dilate((band < LONE_ROW_OUTLINE_LUMA).astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
    ys, xs = np.where((band >= LONE_ROW_LUMA) & dark)   # white stroke with our black outline next to it
    if len(xs) < 12:
        return None
    w = int(xs.max() - xs.min() + 1)
    hh = int(ys.max() - ys.min() + 1)
    centre = (xs.max() + xs.min()) / 2.0
    caption_centre = (x0 + x1) / 2 * width
    if w <= LONE_ROW_MAX_GLYPHS * glyph and hh >= 0.4 * glyph and abs(centre - caption_centre) <= glyph:
        return {"width_px": w, "glyph_px": round(glyph, 1)}
    return None


def letterbox_bands(gray: Any) -> dict[str, float]:
    """Dark bands (fractions of the frame): top / bottom (a caption may interrupt the bottom band) / left / right."""
    import numpy as np  # noqa: PLC0415
    height, width = gray.shape[:2]
    dark = gray < DARK_LUMA
    rows, cols = dark.mean(1), dark.mean(0)

    def run(profile: Any, tolerance: int) -> int:
        n, k, gap = len(profile), 0, 0
        last_dark = 0
        while k < n:
            if profile[k] >= DARK_ROW_FRAC:
                last_dark, gap = k + 1, 0
            else:
                gap += 1
                if gap > tolerance:
                    break
            k += 1
        return last_dark

    tol = int(LETTERBOX_GAP_TOLERANCE * height)
    top = run(rows, 0)
    bottom = run(rows[::-1], tol)
    left = run(cols, 0)
    right = run(cols[::-1], 0)
    out = {"top": top / height, "bottom": bottom / height, "left": left / width, "right": right / width}
    # a real band ends on a sharp edge into picture
    out["sharp"] = bool(top < height and bottom < height and
                        (top == 0 or rows[min(height - 1, top + 2)] < 0.6) and
                        (bottom == 0 or rows[max(0, height - bottom - 3)] < 0.6))
    return out


def letterbox_frame(bands: dict[str, float]) -> str | None:
    if bands["top"] >= LETTERBOX_MIN_BAND and bands["bottom"] >= LETTERBOX_MIN_BAND and bands.get("sharp"):
        if bands["top"] + bands["bottom"] < 0.9:
            return "LETTERBOX"
    if bands["left"] >= LETTERBOX_MIN_BAND and bands["right"] >= LETTERBOX_MIN_BAND \
            and bands["left"] + bands["right"] < 0.9:
        return "PILLARBOX"
    return None


def letterbox_verdict(samples: list[dict[str, float]], width: int, height: int) -> dict[str, Any]:
    """Shot / clip verdict from per-frame bands: >= LETTERBOX_FRAME_SHARE of frames boxed with the same bands."""
    kinds = [letterbox_frame(b) for b in samples]
    boxed = [b for b, k in zip(samples, kinds) if k]
    if not samples or len(boxed) < max(1, math.ceil(LETTERBOX_FRAME_SHARE * len(samples))):
        return {"status": "PASS", "frames": len(samples), "boxed_frames": len(boxed)}
    kind = max(set(k for k in kinds if k), key=kinds.count)
    key = ("top", "bottom") if kind == "LETTERBOX" else ("left", "right")
    med = {k: sorted(b[k] for b in boxed)[len(boxed) // 2] for k in ("top", "bottom", "left", "right")}
    steady = [b for b in boxed if all(abs(b[k] - med[k]) <= LETTERBOX_BAND_JITTER for k in key)]
    if len(steady) < max(1, math.ceil(LETTERBOX_FRAME_SHARE * len(samples))):
        return {"status": "PASS", "frames": len(samples), "boxed_frames": len(boxed), "note": "bands not steady"}
    content_w = width * (1 - med["left"] - med["right"])
    content_h = height * (1 - med["top"] - med["bottom"])
    return {"status": "FAIL", "kind": kind, "frames": len(samples), "boxed_frames": len(steady),
            "bands": {k: round(v, 4) for k, v in med.items()},
            "content_aspect": round(content_w / content_h, 3) if content_h > 0 else None}


# ------------------------------------------------------------------------------------------------ text runs
def merge_runs(hits: list[tuple[float, str, float, float]], gap: float = BURNED_MERGE_GAP_S) -> list[dict[str, Any]]:
    """hits (t, text, yc, h) -> runs {start, end, texts, y, h}."""
    runs: list[dict[str, Any]] = []
    for t, text, yc, h in sorted(hits):
        if runs and t - runs[-1]["end"] <= gap:
            run = runs[-1]
            run["end"] = t
            run["texts"].append(text)
            run["times"].append(t)
            run["h"] = max(run["h"], h)
        else:
            runs.append({"start": t, "end": t, "texts": [text], "times": [t], "y": yc, "h": h})
    return runs


def garbled_read(text: str, reference: set[str]) -> bool:
    if text.startswith(LOWCONF_MARK):
        return True
    chars = CJK.findall(text)
    if len(chars) < 2 or not reference:
        return False
    unknown = [c for c in chars if c not in reference]
    return len(unknown) >= 2 and len(unknown) / len(chars) >= GARBLED_UNKNOWN_FRAC


def burned_runs(hits: list[tuple[float, str, float, float]], reference_text: str) -> list[dict[str, Any]]:
    reference = set(CJK.findall(reference_text or ""))
    out = []
    for run in merge_runs(hits):
        texts = run["texts"]
        bad = [(t, x) for t, x in zip(run["times"], texts) if garbled_read(x, reference)]
        uniq = list(dict.fromkeys(texts))
        flag = len(bad) >= GARBLED_MIN_READS or len(bad) * 2 > len(texts)
        out.append({"start": round(run["start"], 2), "end": round(run["end"] + 1.0 / SCAN_FPS, 2),
                    "y_frac": round(run["y"], 3), "glyph_h_frac": round(run["h"], 4), "reads": len(texts),
                    "texts": uniq[:6], **({"garbled": True, "garbled_window": [round(bad[0][0], 2), round(
                        bad[-1][0] + 1.0 / SCAN_FPS, 2)], "garbled_texts": list(dict.fromkeys(x for _, x in bad))[:3]}
                        if flag else {})})
    return out


# ------------------------------------------------------------------------------------------------ faces
def cluster_faces(embeddings: Any, link: float = FACE_LINK) -> list[list[int]]:
    """Average-linkage agglomerative clustering on cosine similarity (unit vectors), stop below ``link``."""
    import numpy as np  # noqa: PLC0415
    n = len(embeddings)
    if n == 0:
        return []
    e = np.asarray(embeddings, np.float64)
    e /= np.linalg.norm(e, axis=1, keepdims=True) + 1e-9
    sums = e @ e.T
    sizes = np.ones(n)
    alive = np.ones(n, bool)
    members = [[i] for i in range(n)]
    np.fill_diagonal(sums, -np.inf)
    while True:
        avg = sums / np.outer(sizes, sizes)
        avg[~alive, :] = -np.inf
        avg[:, ~alive] = -np.inf
        i, j = np.unravel_index(int(np.argmax(avg)), avg.shape)
        if not np.isfinite(avg[i, j]) or avg[i, j] < link:
            break
        if i > j:
            i, j = j, i
        sums[i, :] += sums[j, :]
        sums[:, i] += sums[:, j]
        sums[i, i] = -np.inf
        sizes[i] += sizes[j]
        alive[j] = False
        members[i] += members[j]
        members[j] = []
    return sorted((m for m in members if m), key=len, reverse=True)


def lookalike_analysis(faces: list[dict[str, Any]]) -> dict[str, Any]:
    """faces: {t, bbox, emb, crop?} -> clusters, centroid matrix, same-frame look-alikes, suspects."""
    import numpy as np  # noqa: PLC0415
    if not faces:
        return {"status": "NO_FACES", "clusters": [], "suspects": []}
    emb = np.asarray([f["emb"] for f in faces], np.float64)
    emb /= np.linalg.norm(emb, axis=1, keepdims=True) + 1e-9
    clusters = [c for c in cluster_faces(emb) if len(c) >= 2]
    cent = [emb[c].mean(0) / (np.linalg.norm(emb[c].mean(0)) + 1e-9) for c in clusters]
    rows = []
    for k, c in enumerate(clusters):
        times = sorted(faces[i]["t"] for i in c)
        spans: list[list[float]] = []
        for t in times:
            if spans and t - spans[-1][1] <= 1.0:
                spans[-1][1] = t
            else:
                spans.append([t, t])
        rows.append({"id": f"F{k}", "faces": len(c), "spans": [[round(a, 2), round(b, 2)] for a, b in spans][:12],
                     "rep": max(c, key=lambda i: faces[i]["bbox"][2] - faces[i]["bbox"][0])})
    matrix = [[round(float(a @ b), 3) for b in cent] for a in cent]
    suspects = []
    for i in range(len(cent)):
        for j in range(i + 1, len(cent)):
            if matrix[i][j] >= LOOKALIKE_CLUSTER:
                suspects.append({"kind": "CLUSTERS_SIMILAR", "a": rows[i]["id"], "b": rows[j]["id"],
                                 "cosine": matrix[i][j], "a_spans": rows[i]["spans"][:6],
                                 "b_spans": rows[j]["spans"][:6]})
    by_t: dict[float, list[int]] = {}
    for i, f in enumerate(faces):
        by_t.setdefault(f["t"], []).append(i)
    same = []
    for t, idx in sorted(by_t.items()):
        for a in range(len(idx)):
            for b in range(a + 1, len(idx)):
                s = float(emb[idx[a]] @ emb[idx[b]])
                if s >= LOOKALIKE_SAME_FRAME:
                    same.append((t, round(s, 3)))
    for t0, t1, best, hits in _spans(same, with_count=True):
        if hits < LOOKALIKE_SAME_FRAME_MIN_HITS:
            continue
        suspects.append({"kind": "TWO_SIMILAR_FACES_IN_ONE_FRAME", "start": t0, "end": t1, "cosine": best})
    return {"status": "OK", "faces": len(faces), "clusters": rows, "centroid_cosine": matrix,
            "suspects": suspects[:12],
            "thresholds": {"cluster_link": FACE_LINK, "same_frame": LOOKALIKE_SAME_FRAME,
                           "cluster_pair": LOOKALIKE_CLUSTER},
            "note": "AI faces score high in ArcFace generally; a merged cluster can hide two characters sharing one "
                    "face -- check the line-up sheet"}


def _spans(points: list[tuple[float, float]], gap: float = 1.0, with_count: bool = False) -> list[tuple[Any, ...]]:
    out: list[list[float]] = []
    for t, s in sorted(points):
        if out and t - out[-1][1] <= gap:
            out[-1][1] = t
            out[-1][2] = max(out[-1][2], s)
            out[-1][3] += 1
        else:
            out.append([t, t, s, 1])
    return [(round(a, 2), round(b, 2), c, int(n)) if with_count else (round(a, 2), round(b, 2), c)
            for a, b, c, n in out]


def lineup_sheet(faces: list[dict[str, Any]], analysis: dict[str, Any], out: Path) -> str | None:
    try:
        from PIL import Image, ImageDraw  # noqa: PLC0415
    except ImportError:
        return None
    rows = analysis.get("clusters") or []
    crops = [(row, faces[row["rep"]].get("crop")) for row in rows]
    crops = [(r, c) for r, c in crops if c is not None]
    if not crops:
        return None
    cell, label = 160, 34
    cols = min(6, len(crops))
    sheet = Image.new("RGB", (cols * cell, math.ceil(len(crops) / cols) * (cell + label)), "black")
    draw = ImageDraw.Draw(sheet)
    for k, (row, crop) in enumerate(crops):
        img = Image.fromarray(crop[:, :, ::-1]).convert("RGB")
        img.thumbnail((cell, cell))
        x, y = (k % cols) * cell, (k // cols) * (cell + label)
        sheet.paste(img, (x + (cell - img.width) // 2, y))
        spans = row["spans"]
        draw.text((x + 4, y + cell + 2), f"{row['id']} n={row['faces']}", fill="white")
        draw.text((x + 4, y + cell + 16), f"{spans[0][0]:.1f}-{spans[-1][1]:.1f}s", fill="white")
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, format="JPEG", quality=85)
    return str(out)


def _insightface_detector() -> Callable[[Any], list[dict[str, Any]]] | None:
    try:
        from insightface.app import FaceAnalysis  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return None
    app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=-1, det_size=(640, 640))

    def detect(frame: Any) -> list[dict[str, Any]]:
        out = []
        for f in app.get(frame):
            x1, y1, x2, y2 = [int(v) for v in f.bbox]
            if x2 - x1 < FACE_MIN_W or float(f.det_score) < FACE_MIN_SCORE:
                continue
            out.append({"bbox": [x1, y1, x2, y2], "emb": [float(v) for v in f.normed_embedding]})
        return out
    return detect


def _rapidocr() -> Callable[[Any], list[tuple[Any, str, float]]] | None:
    try:
        from rapidocr_onnxruntime import RapidOCR  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return None
    engine = RapidOCR()

    def ocr(frame: Any) -> list[tuple[Any, str, float]]:
        return [(box, str(text), float(score)) for box, text, score in (engine(frame)[0] or [])]
    return ocr


# ------------------------------------------------------------------------------------------------ audio analyses
def tail_gaps(x: Any, cuts: list[float], rows: list[dict[str, Any]], *, power: Any = None,
              freqs: Any = None) -> dict[str, Any]:
    """Rule C2 per cut that a line ends near: gap from the last voiced frame to the cut, level at the cut."""
    import numpy as np  # noqa: PLC0415
    if power is None:
        power, freqs = stft_power(x)
    band = (freqs >= 250) & (freqs <= 3500)
    voice_db = 10 * np.log10(power[band].sum(0) + 1e-10)
    episode_floor = float(np.percentile(voice_db, EPISODE_FLOOR_PCT)) + TAIL_VOICED_DB / 2
    out_rows, suspects = [], []
    for c in cuts:
        i = int(round(c * SR / HOP))
        win = voice_db[max(0, i - int(TAIL_WINDOW_S * SR / HOP)): i]
        if len(win) < 50:
            continue
        near = [r for r in rows if r["start"] < c and r["end"] > c - TAIL_WINDOW_S]
        if not near:
            continue
        line = max(near, key=lambda r: r["end"])
        # a line spoken through the whole window has no pause to measure a floor from: the episode floor caps it
        floor = min(float(np.percentile(win, TAIL_FLOOR_PCT)), episode_floor)
        voiced = np.where(win > floor + TAIL_VOICED_DB)[0]
        if len(voiced) == 0:
            continue
        gap = (len(win) - 1 - voiced[-1]) * HOP / SR
        level = float(win[-5:].mean() - floor)
        last_end = max((we for _, we in line["words"]), default=line["end"])
        spans = last_end >= c - TAIL_SPAN_S
        reasons = []
        if gap < TAIL_GAP_S:
            reasons.append("NO_GAP_BEFORE_CUT")
        if level >= TAIL_LEVEL_DB and spans:
            reasons.append("VOICE_AT_CUT_LINE_RUNS_INTO_CUT")
        row = {"cut": round(c, 2), "gap_s": round(gap, 2), "level_at_cut_db": round(level, 1),
               "line_end": round(last_end, 2), "line_runs_into_cut": spans}
        out_rows.append(row)
        if reasons:
            suspects.append({**row, "reasons": reasons})
    return {"method": "voice band 250-3500 Hz energy, floor = 15th percentile of the 1.5 s before the cut",
            "rule": f"gap < {TAIL_GAP_S} s, or >= {TAIL_LEVEL_DB} dB over the floor with the line running into "
                    "the cut", "cuts_checked": len(out_rows), "suspects": suspects[:40]}


def chroma_peakiness(power: Any, freqs: Any) -> Any:
    """Per STFT frame: the largest pitch-class share of 80-2000 Hz energy, smoothed over 0.3 s.  Music (held notes
    and chords) concentrates energy in a few pitch classes; speech and room tone spread it."""
    import numpy as np  # noqa: PLC0415
    sel = (freqs >= MUSIC_BAND[0]) & (freqs <= MUSIC_BAND[1])
    ps, fs = power[sel], freqs[sel]
    pitch_class = np.round(12 * np.log2(fs / 440.0)) % 12
    chroma = np.stack([ps[pitch_class == k].sum(0) for k in range(12)])
    chroma = chroma / (chroma.sum(0) + 1e-12)
    kernel = np.ones(MUSIC_SMOOTH_FRAMES) / MUSIC_SMOOTH_FRAMES
    return np.stack([np.convolve(row, kernel, "same") for row in chroma]).max(0)


def bgm_heuristic(power: Any, freqs: Any, cuts: list[float], duration: float) -> dict[str, Any]:
    """Music map without an S7 BGM report (e.g. music the video model put into a clip): a shot is MUSIC when its
    median chroma peakiness is >= max(MUSIC_PEAK_MIN, MUSIC_PEAK_REL x the episode median); music runs that start
    AND stop on cuts within MUSIC_FRAGMENT_MAX_SHOTS shots / MUSIC_FRAGMENT_MAX_S are fragments."""
    import numpy as np  # noqa: PLC0415
    peak = chroma_peakiness(power, freqs)
    edges = [0.0] + list(cuts) + [duration]
    shots = []
    for a, b in zip(edges[:-1], edges[1:]):
        ia, ib = int(a * SR / HOP), max(int(a * SR / HOP) + 1, int(b * SR / HOP))
        m = peak[ia:ib]
        shots.append({"start": round(a, 2), "end": round(b, 2),
                      "peakiness": round(float(np.median(m)) if len(m) else 0.0, 3)})
    level = float(np.median([s["peakiness"] for s in shots])) if shots else 0.0
    threshold = max(MUSIC_PEAK_MIN, MUSIC_PEAK_REL * level)
    music = [s["peakiness"] >= threshold and s["end"] - s["start"] >= 0.5 for s in shots]
    runs, k = [], 0
    while k < len(shots):
        if music[k]:
            j = k
            while j + 1 < len(shots) and music[j + 1]:
                j += 1
            runs.append((k, j))
            k = j + 1
        else:
            k += 1
    segments, suspects = [], []
    for a, b in runs:
        start, end = shots[a]["start"], shots[b]["end"]
        seg = {"start": start, "end": end, "shots": b - a + 1, "duration": round(end - start, 2)}
        segments.append(seg)
        short = b - a + 1 <= MUSIC_FRAGMENT_MAX_SHOTS or end - start <= MUSIC_FRAGMENT_MAX_S
        if a > 0 and b < len(shots) - 1 and short:
            suspects.append({**seg, "reasons": ["MUSIC_STARTS_AND_STOPS_ON_CUTS"]})
        elif a == 0 and b < len(shots) - 1 and end - start <= MUSIC_FRAGMENT_MAX_S:
            suspects.append({**seg, "reasons": ["OPENING_MUSIC_STOPS_ON_A_CUT"]})
    return {"source": "HEURISTIC_CHROMA_PEAKINESS",
            "method": "per shot median pitch-class concentration of 80-2000 Hz energy vs the episode median",
            "threshold": round(threshold, 3), "segments": segments[:40], "suspects": suspects[:20],
            "shot_peakiness": [s["peakiness"] for s in shots]}


def bgm_from_reports(measured: dict[str, Any]) -> dict[str, Any]:
    """The #274 BGM measurement (S7 plan cues + audio-bed pads) as the BGM map."""
    return {"source": "S7_BGM_PLAN_AND_AUDIO_BED (nalu_qa_defect_checklist.measure_bgm)",
            "segments": [{"start": r.get("start"), "end": r.get("end"), "duration": r.get("duration")}
                         for r in measured.get("runs") or []][:40],
            "suspects": [{"start": r.get("start"), "end": r.get("end"), "reasons": r.get("reasons")}
                         for r in measured.get("flagged") or []][:20]}


# ------------------------------------------------------------------------------------------------ build
def build(video: Path, *, shots: list[dict[str, Any]] | None = None, asr: Any = None,
          ass_text: str | None = None, render_style: str | None = None, bgm_measurement: dict[str, Any] | None = None,
          out_dir: Path | None = None, episode: str = "", media_sha256: str | None = None,
          ocr_fn: Callable[[Any], list[tuple[Any, str, float]]] | None = None,
          face_fn: Callable[[Any], list[dict[str, Any]]] | None = None, audio: Any = None,
          frames: Iterable[tuple[float, Any]] | None = None, info: dict[str, Any] | None = None) -> dict[str, Any]:
    """The pack.  Every component best effort.  ``ocr_fn`` / ``face_fn`` / ``frames`` / ``audio`` / ``info`` are
    injectable (tests); by default RapidOCR, InsightFace and ffmpeg decode the video."""
    import numpy as np  # noqa: PLC0415
    errors: dict[str, str] = {}
    info = info or probe(video)
    width, height, duration = info["width"], info["height"], info["duration"]
    if width <= 0 or height <= 0:
        raise ValueError(f"no decodable video stream: {video}")
    cuts = cuts_from_shots(shots) if shots else None
    if cuts is None:
        try:
            cuts = detect_cuts(video)
        except Exception as exc:  # noqa: BLE001
            cuts, errors["cuts"] = [], f"{type(exc).__name__}:{str(exc)[:120]}"
    rows = asr_rows(asr)
    captions = ass_captions(ass_text)
    reference_text = "".join(r["text"] for r in rows) + "".join(c["text"] for c in captions)
    anime = str(render_style or "").lower() == "anime"
    if ocr_fn is None:
        ocr_fn = _rapidocr()
        if ocr_fn is None:
            errors["burned_text"] = "RAPIDOCR_UNAVAILABLE"
    if face_fn is None and not anime:
        try:
            face_fn = _insightface_detector()
        except Exception as exc:  # noqa: BLE001
            face_fn, errors["lookalike_cast"] = None, f"{type(exc).__name__}:{str(exc)[:120]}"
        if face_fn is None:
            errors.setdefault("lookalike_cast", "INSIGHTFACE_UNAVAILABLE")

    burned_hits: list[tuple[float, str, float, float]] = []
    stacked_hits: list[tuple[float, dict[str, Any]]] = []
    lone_hits: list[float] = []
    bands_by_t: list[tuple[float, dict[str, float]]] = []
    faces: list[dict[str, Any]] = []
    frame_count = 0
    try:
        for index, (t, frame) in enumerate(frames if frames is not None else
                                           iter_frames(video, SCAN_FPS, width, height)):
            frame_count += 1
            gray = frame.mean(2) if frame.ndim == 3 else frame
            bands_by_t.append((t, letterbox_bands(gray)))
            if ocr_fn is not None:
                try:
                    boxes = ocr_fn(frame)
                except Exception:  # noqa: BLE001
                    boxes = []
                try:
                    stack = stacked_rows(boxes, width, height)
                except Exception:  # noqa: BLE001
                    stack = None
                if stack:
                    stacked_hits.append((t, stack))
                caption_rows = []
                for box, text, score in boxes:
                    geom = box_geometry(box, width, height)
                    kind = classify_box(t, text, score, geom, duration)
                    if kind in ("BURNED", "BURNED_LOW_CONFIDENCE"):
                        burned_hits.append((t, text if kind == "BURNED" else LOWCONF_MARK + text,
                                            (geom[1] + geom[3]) / 2, geom[3] - geom[1]))
                    elif kind == "OURS":
                        caption_rows.append(geom)
                rows_y: list[tuple[float, float, float, float]] = []
                for geom in sorted(caption_rows, key=lambda g: g[1]):  # one entry per caption row
                    if rows_y and abs((geom[1] + geom[3]) - (rows_y[-1][1] + rows_y[-1][3])) / 2 < 0.012:
                        prev = rows_y[-1]
                        rows_y[-1] = (min(prev[0], geom[0]), min(prev[1], geom[1]), max(prev[2], geom[2]),
                                      max(prev[3], geom[3]))
                    else:
                        rows_y.append(geom)
                if lone_row_pixels(gray, rows_y):
                    lone_hits.append(t)
            if face_fn is not None and index % FACE_EVERY == 0 and len(faces) < FACE_MAX:
                try:
                    for f in face_fn(frame):
                        x1, y1, x2, y2 = f["bbox"]
                        crop = frame[max(0, y1):max(0, y2), max(0, x1):max(0, x2)].copy()
                        faces.append({"t": round(t, 2), "bbox": f["bbox"], "emb": f["emb"],
                                      "crop": crop if crop.size else None})
                except Exception as exc:  # noqa: BLE001
                    errors["lookalike_cast"] = f"{type(exc).__name__}:{str(exc)[:120]}"
                    face_fn = None
    except Exception as exc:  # noqa: BLE001
        errors["video_decode"] = f"{type(exc).__name__}:{str(exc)[:160]}"

    pack: dict[str, Any] = {"schema": SCHEMA, "authority": AUTHORITY, "episode": episode,
                            "media_sha256": media_sha256, "video": str(video),
                            "frame": {"width": width, "height": height, "duration_s": round(duration, 3)},
                            "scan_fps": SCAN_FPS, "frames_scanned": frame_count, "cuts": [round(c, 2) for c in cuts]}

    if "burned_text" not in errors and frame_count:
        runs = burned_runs(burned_hits, reference_text)
        pack["burned_text"] = {"method": "RapidOCR 4 fps; ours = caption band and caption glyph height; burned = "
                                         "glyphs >= 3.9 % of the frame height elsewhere",
                               "runs": runs[:60], "garbled": [r for r in runs if r.get("garbled")][:12]}
        pack["stacked_subtitles"] = {"method": f"RapidOCR {SCAN_FPS:g} fps; two caption-band rows (y "
                                               f"{STACK_BAND_Y[0]}-{STACK_BAND_Y[1]}) >= {STACK_MIN_GAP} apart saying "
                                               "the same line (subtitle_text_match >= 0.6) in >= 2 reads",
                                     "runs": stacked_runs(stacked_hits)[:30]}
    # subtitle wrap: the ASS check (reused from the must-check list) + pixel lone rows
    try:
        import nalu_qa_defect_checklist as _qa  # noqa: PLC0415
        wrap = _qa.measure_subtitle_wrap(ass_text) if ass_text else {}
    except Exception as exc:  # noqa: BLE001
        wrap = {"error": f"{type(exc).__name__}:{str(exc)[:120]}"}
    lone_runs = [{"start": round(a, 2), "end": round(b + 1.0 / SCAN_FPS, 2)}
                 for a, b, _ in _spans([(t, 0.0) for t in lone_hits], gap=0.6) if b - a >= 0.4]
    pack["subtitle_wrap"] = {"ass": {k: wrap.get(k) for k in ("captions", "flagged", "error") if k in wrap},
                             "pixel_lone_rows": lone_runs[:20]}
    # letterbox per shot
    edges = [0.0] + list(cuts) + [duration]
    lb_shots = []
    for a, b in zip(edges[:-1], edges[1:]):
        if (duration and a >= duration - END_CARD_S - 0.5) or b <= TITLE_CARD_S - 0.5:
            continue  # our own title / tail card
        samples = [bd for t, bd in bands_by_t if a + 0.1 <= t < b - 0.1] or [bd for t, bd in bands_by_t if a <= t < b]
        verdict = letterbox_verdict(samples, width, height)
        if verdict["status"] == "FAIL":
            lb_shots.append({"start": round(a, 2), "end": round(b, 2), **{k: verdict.get(k) for k in
                                                                          ("kind", "bands", "content_aspect")}})
    pack["letterbox"] = {"method": f"rows/cols with >= {DARK_ROW_FRAC:.0%} pixels below luma {DARK_LUMA}; both "
                                   f"bands >= {LETTERBOX_MIN_BAND:.0%}, steady in >= {LETTERBOX_FRAME_SHARE:.0%} of "
                                   "a shot's frames", "shots": lb_shots}
    # faces
    if anime:
        pack["lookalike_cast"] = {"status": "NOT_APPLICABLE", "reason": "RENDER_STYLE_ANIME: InsightFace cannot "
                                  "separate anime characters; the video reviewer judges it"}
    elif face_fn is not None or faces:
        analysis = lookalike_analysis(faces)
        sheet = lineup_sheet(faces, analysis, (out_dir or video.parent) / f"{episode or video.stem}_CAST_LINEUP.jpg") \
            if faces else None
        for row in analysis.get("clusters") or []:
            row.pop("rep", None)
        pack["lookalike_cast"] = {**analysis, **({"lineup_sheet": sheet} if sheet else {})}
    # audio
    try:
        x = audio if audio is not None else decode_audio(video)
        if len(x) < SR // 2:
            raise ValueError("no audio")
        power, freqs = stft_power(x)
        pack["dialogue_tail"] = tail_gaps(x, cuts, rows, power=power, freqs=freqs) if rows else {
            "status": "NO_ASR_LINES"}
        if bgm_measurement and (bgm_measurement.get("runs") or bgm_measurement.get("segments")):
            pack["bgm"] = bgm_from_reports(bgm_measurement)
        else:
            pack["bgm"] = bgm_heuristic(power, freqs, cuts, duration or len(x) / SR)
        del power
    except Exception as exc:  # noqa: BLE001
        errors["audio"] = f"{type(exc).__name__}:{str(exc)[:160]}"
    if errors:
        pack["errors"] = errors
    pack["summary"] = summary(pack)
    _ = np
    return pack


def summary(pack: dict[str, Any]) -> dict[str, Any]:
    """Compact suspects with timestamps (the part the reviewers read first)."""
    def win(r: dict[str, Any]) -> list[Any]:
        return [r.get("start"), r.get("end")]
    out: dict[str, Any] = {}
    bt = pack.get("burned_text") or {}
    if "runs" in bt:
        out["burned_text_runs"] = [{"window": win(r), "text": (r.get("texts") or [""])[0].lstrip(LOWCONF_MARK)[:12],
                                    **({"garbled": True} if r.get("garbled") else {})} for r in bt["runs"][:40]]
    st = pack.get("stacked_subtitles") or {}
    if st.get("runs"):
        out["stacked_subtitle_runs"] = [{"window": win(r), "texts": [str(x)[:24] for x in r.get("texts") or []],
                                         "similarity": r.get("similarity")} for r in st["runs"][:20]]
    dt = pack.get("dialogue_tail") or {}
    if "suspects" in dt:
        out["tail_cut_suspects"] = [{"cut": r["cut"], "gap_s": r["gap_s"], "level_db": r["level_at_cut_db"]}
                                    for r in dt["suspects"][:30]]
    bgm = pack.get("bgm") or {}
    if "suspects" in bgm:
        out["bgm_suspects"] = [{"window": win(r), "reasons": r.get("reasons")} for r in bgm["suspects"][:15]]
        out["bgm_source"] = bgm.get("source")
    lb = pack.get("letterbox") or {}
    out["letterbox_shots"] = [{"window": win(r), "kind": r.get("kind"), "content_aspect": r.get("content_aspect")}
                              for r in lb.get("shots") or []]
    lc = pack.get("lookalike_cast") or {}
    if lc:
        out["lookalike"] = {"status": lc.get("status"), "clusters": len(lc.get("clusters") or []),
                            "suspects": lc.get("suspects") or []}
    sw = pack.get("subtitle_wrap") or {}
    out["wrap_suspects"] = ([{"at": r.get("start"), "rows": r.get("rows"), "reasons": r.get("reasons")}
                             for r in ((sw.get("ass") or {}).get("flagged") or [])][:15]
                            + [{"window": win(r), "reasons": ["PIXEL_LONE_SHORT_ROW"]}
                               for r in sw.get("pixel_lone_rows") or []][:15])
    if pack.get("errors"):
        out["errors"] = sorted(pack["errors"])
    return out


# ------------------------------------------------------------------------------------------------ S6 clip check
def clip_letterbox(media: Path, *, samples: int = 8) -> dict[str, Any]:
    """Free post-generation check of ONE unit clip: decoded aspect ~9:16 and no letterbox / pillarbox bands.
    ``status`` FAIL is a technical defect, redo-eligible once under q2_auto_redo.  Never raises."""
    try:
        info = probe(media)
        width, height, duration = info["width"], info["height"], info["duration"]
        if not width or not height:
            return {"status": "ERROR", "error": "NO_VIDEO_STREAM", "method": CLIP_METHOD}
        aspect = width / height
        out: dict[str, Any] = {"method": CLIP_METHOD, "decoded": f"{width}x{height}", "aspect": round(aspect, 4)}
        failures = []
        if abs(aspect - PORTRAIT_9_16) / PORTRAIT_9_16 > ASPECT_TOLERANCE:
            failures.append("DECODED_ASPECT_NOT_9_16")
        fps = samples / max(duration, 0.5)
        bands = [letterbox_bands(frame.mean(2)) for _, frame in iter_frames(media, fps, width, height)]
        verdict = letterbox_verdict(bands, width, height)
        out["letterbox"] = verdict
        if verdict["status"] == "FAIL":
            failures.append(f"{verdict['kind']}_BANDS")
        out["status"] = "FAIL" if failures else "PASS"
        if failures:
            out["failure"] = "LETTERBOX:" + ",".join(failures)
        return out
    except Exception as exc:  # noqa: BLE001
        return {"status": "ERROR", "error": f"{type(exc).__name__}:{str(exc)[:160]}", "method": CLIP_METHOD}


CLIP_METHOD = "AV_EVIDENCE_LETTERBOX_V1"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--video", type=Path, required=True)
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--asr", type=Path)
    b.add_argument("--ass", type=Path)
    b.add_argument("--cuts", type=Path, help="text file, one cut time per line (else scdet)")
    b.add_argument("--render-style", default=None)
    b.add_argument("--episode", default="")
    c = sub.add_parser("clip")
    c.add_argument("--video", type=Path, required=True)
    args = ap.parse_args(argv)
    if args.cmd == "clip":
        print(json.dumps(clip_letterbox(args.video), ensure_ascii=False))
        return 0
    shots = None
    if args.cuts:
        cuts = [float(x) for x in args.cuts.read_text().split()]
        edges = [0.0] + cuts + [1e9]
        shots = [{"end_seconds": e} for e in edges[1:]]
    asr = json.loads(args.asr.read_text(encoding="utf-8")) if args.asr else None
    pack = build(args.video, shots=shots, asr=asr,
                 ass_text=args.ass.read_text(encoding="utf-8") if args.ass else None,
                 render_style=args.render_style, out_dir=args.out.parent, episode=args.episode)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(pack, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(pack["summary"], ensure_ascii=False)[:3000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
