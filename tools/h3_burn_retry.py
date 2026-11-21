#!/usr/bin/env python3
"""S6 burned-text detection and perturbed retry for MiniMax-H3 clips (line owner 2026-11-19).

MiniMax-H3 sometimes burns the spoken line into the picture as an on-screen caption (centred, y ~0.74, glyphs
52-60 px at 720 px width).  Paid experiments (2026-11-19) showed that HopsAPI returns a BYTE-IDENTICAL clip for an
identical request: changing the reference URL or the ``resolution`` field does not change the output, changing the
reference image BYTES does.  A plain resubmit is therefore useless; a retry must perturb the request content.

Line owner approval (2026-11-19): an automatic paid retry ONLY when burned text is detected, at most 2 retries per
unit, and no blur cover by default.

This module holds the three free, local pieces the engine wires together:

* :func:`detect` -- right after a clip lands in S6 (before its tail frame is extracted for a successor): sample the
  clip at ~4 fps and OCR the band y 0.55-0.95 with the RapidOCR engine and false-positive filters of
  ``tail_frame_text_clean.find_text_boxes`` (>= 2 CJK/Latin/kana/hangul chars, score >= 0.6, glyph >= 40 px at
  720 w, horizontal, centred, area cap).  A clip is BURNED when hits persist in >= 2 consecutive samples.  Raw H3
  clips never carry our own subtitles, so nothing is excluded.  Fail-open (OCR / OpenCV missing -> FAIL_OPEN).
* :func:`perturb_start_frame` -- the send-time @Image1 bytes of retry ``n``: one pixel nudged by one level at a
  retry-indexed position, re-encoded JPEG at quality 92 - n, so the bytes (and the pixels, imperceptibly) differ.
* :func:`retry_sentence` / :func:`apply_retry_sentence` -- the retry-indexed prompt variation: one plain sentence
  reinforcing the existing "picture stays clean / no on-screen text" clause, appended as the prompt's last line.

The task field ``h3_burn_retry`` (int, 1..max) carries the retry index from the S6 wave state
(``s6_burn_retry``) through the compile into ``provider_prompt_unit`` and the submitter.  Absent on every other task,
so their prompts, fingerprints and request bytes are unchanged.

Env: ``NALU_S6_BURN_RETRY_MAX`` (default 2; 0 disables detection-triggered retries).
"""
from __future__ import annotations

import hashlib
import io
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

SCHEMA = "qingshan.s6_burned_text_detect.v1"
TASK_FIELD = "h3_burn_retry"
STATE_KEY = "s6_burn_retry"
ENV_MAX = "NALU_S6_BURN_RETRY_MAX"
DEFAULT_MAX = 2
SAMPLE_FPS = 4.0
MIN_CONSECUTIVE = 2
UNRESOLVED_FLAG = "burned_text_unresolved"

#: retry index -> the sentence appended to the provider prompt (no all-caps label, no digits: H3 voices labels)
RETRY_SENTENCES = {
    1: ("The picture stays completely clean for the whole clip: the spoken words are only heard, never written on "
        "screen, with no caption, subtitle or lettering anywhere in the frame."),
    2: ("Every frame shows only the scene itself: no caption, subtitle, lettering or text overlay appears at any "
        "moment, and the lower part of the frame stays free of any writing."),
}


def max_retries(env: dict[str, str] | None = None) -> int:
    raw = str((env if env is not None else os.environ).get(ENV_MAX, DEFAULT_MAX)).strip()
    try:
        return max(0, int(float(raw)))
    except ValueError:
        return DEFAULT_MAX


def retry_index(payload: dict[str, Any] | None) -> int:
    """The declared burn-retry index of a task / prompt unit (0 = not a burn retry)."""
    try:
        value = int((payload or {}).get(TASK_FIELD) or 0)
    except (TypeError, ValueError):
        return 0
    return value if value > 0 else 0


def retry_sentence(index: int) -> str:
    if index <= 0:
        return ""
    return RETRY_SENTENCES.get(index) or RETRY_SENTENCES[max(RETRY_SENTENCES)]


def apply_retry_sentence(text: str, index: int) -> str:
    """``text`` with the retry sentence as its last line (trailing newlines kept); unchanged for index 0."""
    sentence = retry_sentence(index)
    if not sentence or sentence in text:
        return text
    core = text.rstrip("\n")
    return core + "\n" + sentence + text[len(core):]


def strip_retry_sentence(text: str) -> tuple[str, int]:
    """(``text`` without an engine retry sentence, the retry index found or 0) -- the exact inverse of
    :func:`apply_retry_sentence`, used to prove a changed prompt differs from a reviewed one only by it."""
    for index, sentence in RETRY_SENTENCES.items():
        marker = "\n" + sentence
        if marker in text:
            return text.replace(marker, "", 1), index
    return text, 0


# ------------------------------------------------------------------------------------------- image perturbation
def perturb_start_frame(data: bytes, index: int) -> tuple[bytes, dict[str, Any]]:
    """Retry ``index`` of the @Image1 bytes: one pixel +-1 level at a retry-indexed position, JPEG quality 92-index.

    Returns (bytes, note).  Never raises; when the image cannot be decoded a JPEG comment segment is inserted (or,
    for other formats, the bytes are returned with status SKIPPED_UNDECODABLE)."""
    before = hashlib.sha256(data).hexdigest()
    note: dict[str, Any] = {"retry": index, "sha256_before": before}
    if index <= 0:
        return data, {**note, "status": "NOT_A_RETRY"}
    try:
        from PIL import Image  # noqa: PLC0415
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            work = image.convert("RGB")
        w, h = work.size
        x, y = (37 * index) % max(1, w), (53 * index) % max(1, h)
        r, g, b = work.getpixel((x, y))
        work.putpixel((x, y), (r, g, b + 1 if b < 255 else b - 1))
        quality = max(70, 92 - index)
        out = io.BytesIO()
        work.save(out, format="JPEG", quality=quality)
        encoded = out.getvalue()
        if encoded == data:  # practically impossible; never send the same bytes twice
            raise ValueError("re-encode produced identical bytes")
        return encoded, {**note, "status": "PERTURBED", "method": f"PIXEL_NUDGE_JPEG_Q{quality}",
                         "pixel": [x, y], "sha256_after": hashlib.sha256(encoded).hexdigest()}
    except Exception as exc:  # noqa: BLE001 - fall back to a lossless byte change
        if data[:2] == b"\xff\xd8":
            comment = f"nalu-s6-burn-retry-{index}".encode("ascii")
            encoded = data[:2] + b"\xff\xfe" + (len(comment) + 2).to_bytes(2, "big") + comment + data[2:]
            return encoded, {**note, "status": "PERTURBED", "method": "JPEG_COMMENT_SEGMENT",
                             "error": f"{type(exc).__name__}: {exc}"[:200],
                             "sha256_after": hashlib.sha256(encoded).hexdigest()}
        return data, {**note, "status": "SKIPPED_UNDECODABLE", "error": f"{type(exc).__name__}: {exc}"[:200]}


#: final-fix burned-text redo retry n -> (crop fraction per side, JPEG quality); escalates per retry (2026-11-20)
STRONG_STEPS = {1: (0.01, 86), 2: (0.02, 80)}


def perturb_start_frame_strong(data: bytes, index: int, retry: int) -> tuple[bytes, dict[str, Any]]:
    """A STRONGER @Image1 perturbation for a final-fix burned-text redo retry (line owner 2026-11-20, E18: the
    one-pixel nudge only re-rolls the seed and three of four redone units burned the same line again).

    Retry ``retry`` (1..2) crops ``STRONG_STEPS[retry][0]`` of the width / height (1 % then 2 %) at a retry-indexed
    offset, scales back to the original size (aspect and framing kept: a 1-2 % scale jitter), nudges one pixel and
    re-encodes at a different JPEG quality.  Never raises; falls back to :func:`perturb_start_frame`."""
    if retry <= 0:
        return perturb_start_frame(data, index)
    frac, quality = STRONG_STEPS.get(retry) or STRONG_STEPS[max(STRONG_STEPS)]
    before = hashlib.sha256(data).hexdigest()
    try:
        from PIL import Image  # noqa: PLC0415
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            work = image.convert("RGB")
        w, h = work.size
        dx, dy = max(2, round(w * frac)), max(2, round(h * frac))  # pixels removed per axis in total
        # retry-indexed offset: retry 1 keeps a third of the margin on the left / top, retry 2 two thirds
        left, top = (dx // 3, dy // 3) if retry % 2 else (2 * dx // 3, 2 * dy // 3)
        box = (left, top, left + w - dx, top + h - dy)
        resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
        work = work.crop(box).resize((w, h), resample)
        x, y = (41 * (index + retry)) % max(1, w), (59 * (index + retry)) % max(1, h)
        r, g, b = work.getpixel((x, y))
        work.putpixel((x, y), (r, g, b + 1 if b < 255 else b - 1))
        out = io.BytesIO()
        work.save(out, format="JPEG", quality=quality)
        encoded = out.getvalue()
        if encoded == data:
            raise ValueError("re-encode produced identical bytes")
        return encoded, {"retry": index, "final_fix_burn_retry": retry, "sha256_before": before,
                         "status": "PERTURBED", "method": f"CROP_SCALE_{round(frac * 100)}PCT_JPEG_Q{quality}",
                         "crop_box": list(box), "size": [w, h], "sha256_after": hashlib.sha256(encoded).hexdigest()}
    except Exception as exc:  # noqa: BLE001 - the plain perturbation still changes the bytes
        encoded, note = perturb_start_frame(data, index + retry)
        return encoded, {**note, "final_fix_burn_retry": retry, "strong_error": f"{type(exc).__name__}: {exc}"[:200]}


# ------------------------------------------------------------------------------------------------- detection
#: frame reader: video path, fps -> iterable of (time_s, BGR ndarray)
FrameReader = Callable[[Path, float], Any]


def _cv2_frames(video: Path, fps: float):
    """Sample ``fps`` frames per second with OpenCV (grab every frame, decode only the sampled ones)."""
    import cv2  # noqa: PLC0415
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise ValueError(f"cannot open {video}")
    try:
        native = float(cap.get(cv2.CAP_PROP_FPS) or 0.0) or 24.0
        step = 1.0 / fps
        next_t, index = step / 2.0, 0
        while True:
            if not cap.grab():
                break
            t = index / native
            index += 1
            if t + 0.5 / native < next_t:
                continue
            ok, frame = cap.retrieve()
            if ok and frame is not None:
                yield round(next_t, 3), frame
            next_t += step
    finally:
        cap.release()


def longest_run(flags: list[bool]) -> int:
    best = run = 0
    for flag in flags:
        run = run + 1 if flag else 0
        best = max(best, run)
    return best


def detect(video: Path, *, fps: float = SAMPLE_FPS, ocr: Any = None, frames: FrameReader | None = None,
           min_consecutive: int = MIN_CONSECUTIVE) -> dict[str, Any]:
    """Burned caption text in a raw H3 clip.  Never raises.

    ``status``: BURNED (hits in >= ``min_consecutive`` consecutive samples), CLEAN, or FAIL_OPEN (cannot measure:
    treated as clean by the caller).  ``burned_frames`` counts every sample with a hit (the best-take measure)."""
    started = time.perf_counter()
    out: dict[str, Any] = {"schema": SCHEMA, "video": str(video), "fps": fps, "min_consecutive": min_consecutive}
    try:
        import tail_frame_text_clean as _ttc  # noqa: PLC0415 - same OCR engine + filters as the tail cleaner
        reader = frames or _cv2_frames
        engine = ocr or _ttc._default_ocr
        flags: list[bool] = []
        hits: list[dict[str, Any]] = []
        for t, image in reader(Path(video), fps):
            boxes = _ttc.find_text_boxes(image, engine)
            flags.append(bool(boxes))
            for b in boxes:
                hits.append({"t": t, "text": b["text"], "score": b["score"],
                             "glyph_px_at_720": b["glyph_px_at_720"],
                             "y_centre": round((b["y0"] + b["y1"]) / 2.0 / float(image.shape[0]), 3)})
        run = longest_run(flags)
        out.update(status="BURNED" if run >= min_consecutive else "CLEAN", frames_sampled=len(flags),
                   burned_frames=sum(flags), longest_run=run, hits=hits[:40])
    except Exception as exc:  # noqa: BLE001 - fail-open: never block the line on the detector
        out.update(status="FAIL_OPEN", error=f"{type(exc).__name__}: {exc}"[:300], burned_frames=0)
    out["elapsed_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
    return out


# ---------------------------------------------------------------------------------------------- retry planning
def plan(row: dict[str, Any] | None, detection: dict[str, Any], *, retry_max: int, headroom: int | None,
         cost: int, owner_accepted: bool = False) -> dict[str, Any]:
    """What to do with one unit's freshly landed take.  Pure: no I/O.

    ``row`` is the unit's ``s6_burn_retry`` wave-state record ({"attempts": [...]} or None).  Returns
    {"action": KEEP|RETRY|KEEP_BEST, "reason": ..., "retry": n} where n is the retry index to submit."""
    attempts = list((row or {}).get("attempts") or [])
    done = len(attempts)
    if detection.get("status") == "FAIL_OPEN":
        return {"action": "KEEP", "reason": "DETECTOR_FAIL_OPEN", "retry": done}
    if detection.get("status") != "BURNED":
        return {"action": "KEEP", "reason": "RESOLVED" if done else "CLEAN", "retry": done}
    if retry_max <= 0:
        return {"action": "KEEP_BEST", "reason": "RETRY_DISABLED", "retry": done}
    if owner_accepted:
        return {"action": "KEEP_BEST", "reason": "LINE_OWNER_ACCEPTED_THIS_CLIP", "retry": done}
    if done >= retry_max:
        return {"action": "KEEP_BEST", "reason": "RETRY_MAX_REACHED", "retry": done}
    if headroom is None:
        return {"action": "KEEP_BEST", "reason": "BUDGET_HEADROOM_UNKNOWN", "retry": done, "cost": cost}
    if cost > int(headroom):
        return {"action": "KEEP_BEST", "reason": "BUDGET_HEADROOM_SHORT", "retry": done, "cost": cost,
                "headroom": int(headroom)}
    return {"action": "RETRY", "reason": "BURNED_TEXT_DETECTED", "retry": done + 1, "cost": cost}


def best_take(takes: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The take with the fewest burned frames; on a tie the latest (it carries the strongest prompt)."""
    rows = [t for t in takes if t.get("path")]
    if not rows:
        return None
    return min(reversed(rows), key=lambda t: int(t.get("burned_frames") or 0))


def main(argv: list[str] | None = None) -> int:
    import argparse  # noqa: PLC0415
    import json  # noqa: PLC0415
    ap = argparse.ArgumentParser(description="S6 burned-text detection on raw H3 clips (local, free)")
    ap.add_argument("videos", nargs="+", type=Path)
    args = ap.parse_args(argv)
    for video in args.videos:
        result = detect(video)
        print(json.dumps({k: result.get(k) for k in ("video", "status", "frames_sampled", "burned_frames",
                                                      "longest_run", "elapsed_ms")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
