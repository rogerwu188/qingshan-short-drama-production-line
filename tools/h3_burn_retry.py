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
  reinforcing the existing "picture stays clean / no on-screen text" clause (a burn retry: the FIRST line, and from
  retry 2 each dialogue literal framed as heard speech; sheet / wobble retries: the last line).
* :func:`s6_escalation` / :data:`S6_STEPS` (2026-11-22, E23 device 1101 + paid lab probe: H3 renders a
  near-identical clip for a near-identical request, so the one-pixel nudge and the tail sentence re-rendered the
  same burned line) -- the ladder: lead sentence + 1.5 % @Image1 scale jitter, then + heard-speech mark + 3 %
  jitter + identity sheets as front-view crops.
* :func:`request_content_fingerprint` / :func:`request_delta` -- per-attempt request evidence (prompt sha + every
  sent reference sha); S6 says ``S6_BURN_RETRY_SAME_REQUEST`` / ``S6_BURN_RETRY_SAME_RENDER`` when a retry could
  not differ.

The task field ``h3_burn_retry`` (int, 1..max) carries the retry index from the S6 wave state
(``s6_burn_retry``) through the compile into ``provider_prompt_unit`` and the submitter.  Absent on every other task,
so their prompts, fingerprints and request bytes are unchanged.

Env: ``NALU_S6_BURN_RETRY_MAX`` (default 2; 0 disables detection-triggered retries).

Camera wobble (KO E05 on device ...0080, 2026-11-21): a locked-off unit whose take moves the set with the actor
(tools/h3_camera_wobble.detect) is retried once through this same record (attempt flag ``camera_wobble``) with the
locked-off sentence (:data:`WOBBLE_RETRY_SENTENCES`); the total S6 retries of a unit stay capped by this module's
maximum.

Reference-sheet leaks (JA-01 E04 VU-007, 2026-11-21): a take that shows the unit's multi-view identity sheet as its
picture (tools/h3_reference_sheet_guard.detect_leak) is retried like burned text, with the SHEET retry sentence
(:data:`SHEET_RETRY_SENTENCES`) and the identity sheets sent as their front-view crop; a take is never CLEAN while the
sheet detector fires.  An UNRESOLVED take's residual text band (:func:`residual_text_band`) moves our caption above it
in S7 and joins the final fix round.
"""
from __future__ import annotations

import hashlib
import io
import json
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


#: retry index -> the sentence of a retry after a REFERENCE-SHEET leak (no all-caps label, no digits); it also keeps
#: the picture free of writing, because a sheet retry may follow a burned take
SHEET_RETRY_SENTENCES = {
    1: ("The identity reference images only show who each person is: the picture is one ordinary moment of the scene "
        "with each person appearing once, never a character sheet, turnaround views or a face inset, and no writing "
        "appears anywhere in the frame."),
    2: ("Every frame is a single live moment of the scene itself, not a reference board: each person appears exactly "
        "once, with no side or back view copies, no close-up inset and no caption or lettering anywhere."),
}
#: retry index -> the sentence of a retry after a CAMERA WOBBLE (tools/h3_camera_wobble.py, KO E05 2026-11-21: the
#: set moved with the actor on a locked-off unit); no all-caps label, no digits; also keeps the picture free of writing
WOBBLE_RETRY_SENTENCES = {
    1: ("The camera is locked off on a tripod for the whole clip: the background, the walls and the edges of the "
        "frame stay perfectly still; only the people move, and no nod, gesture or step ever moves the frame. No "
        "writing appears anywhere in the picture."),
    2: ("Every frame is shot from one fixed tripod position: the set behind the people never shifts, sways or "
        "warps, the frame never chases a movement, and only the people themselves move. No caption or lettering "
        "appears anywhere."),
}
WOBBLE_FLAG = "camera_wobble"
#: our subtitle band (fractions of the frame height): an H3 text box centred here stacks under our caption
SUBTITLE_BAND = (0.55, 0.95)
SHEET_LEAK_FLAG = "reference_sheet_leak"


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


def retry_sentence(index: int, sheet: bool = False, wobble: bool = False) -> str:
    if index <= 0:
        return ""
    table = SHEET_RETRY_SENTENCES if sheet else WOBBLE_RETRY_SENTENCES if wobble else RETRY_SENTENCES
    return table.get(index) or table[max(table)]


#: burned-text retry >= 2 (escalation, 2026-11-22): appended right after every dialogue literal ``</d>`` so the line
#: itself is framed as heard speech (E23 device 1101: the burned text WAS the quoted line, at y 0.70-0.77)
DIALOGUE_HEARD_MARK = ", heard as speech only and never written on screen"
#: burned-text retry index from which the dialogue literals carry :data:`DIALOGUE_HEARD_MARK`
DIALOGUE_MARK_FROM = 2


def apply_retry_sentence(text: str, index: int, sheet: bool = False, wobble: bool = False) -> str:
    """``text`` with the retry sentence; unchanged for index 0.

    The sheet variant (after a reference-sheet leak) and the locked-off variant (after a camera wobble) are the
    prompt's last line (trailing newlines kept).  A BURNED-TEXT retry escalates (2026-11-22, E23 device 1101: five
    units burned the same line on every retry because the tail sentence barely moved the render): its sentence is
    the prompt's FIRST line, ahead of the anti-text rule (the E12 lesson: a text ban stated first holds better),
    and from retry :data:`DIALOGUE_MARK_FROM` on every dialogue literal is followed by
    :data:`DIALOGUE_HEARD_MARK`.  :func:`strip_retry_sentence` is its exact inverse."""
    sentence = retry_sentence(index, sheet, wobble)
    if not sentence or sentence in text:
        return text
    if sheet or wobble:
        core = text.rstrip("\n")
        return core + "\n" + sentence + text[len(core):]
    body = text
    if index >= DIALOGUE_MARK_FROM and DIALOGUE_HEARD_MARK not in body:
        body = body.replace("</d>", "</d>" + DIALOGUE_HEARD_MARK)
    return sentence + "\n" + body


def strip_retry_sentence(text: str) -> tuple[str, int]:
    """(``text`` without an engine retry sentence, the retry index found or 0) -- the exact inverse of
    :func:`apply_retry_sentence`, used to prove a changed prompt differs from a reviewed one only by it.  A tail
    burn sentence (engines before 2026-11-22) is still recognised."""
    for index, sentence in RETRY_SENTENCES.items():
        if text.startswith(sentence + "\n"):
            body = text[len(sentence) + 1:]
            if index >= DIALOGUE_MARK_FROM:
                body = body.replace("</d>" + DIALOGUE_HEARD_MARK, "</d>")
            return body, index
    for table in (RETRY_SENTENCES, SHEET_RETRY_SENTENCES, WOBBLE_RETRY_SENTENCES):
        for index, sentence in table.items():
            marker = "\n" + sentence
            if marker in text:
                return text.replace(marker, "", 1), index
    return text, 0


def sheet_retry(record: dict[str, Any] | None) -> bool:
    """A unit's ``s6_burn_retry`` record asks for the sheet retry (its latest attempt followed a sheet leak)."""
    attempts = list((record or {}).get("attempts") or [])
    return bool(attempts and attempts[-1].get(SHEET_LEAK_FLAG))


def wobble_retry(record: dict[str, Any] | None) -> bool:
    """A unit's ``s6_burn_retry`` record asks for the locked-off retry (its latest attempt followed a camera wobble)."""
    attempts = list((record or {}).get("attempts") or [])
    return bool(attempts and attempts[-1].get(WOBBLE_FLAG))


def combine_sheet_leak(detection: dict[str, Any], leak: dict[str, Any] | None) -> dict[str, Any]:
    """The burn detection of a take merged with the reference-sheet detector: a LEAK makes the take BURNED (never
    CLEAN) with the leak frames counted for the best take; a burn-detector FAIL_OPEN with a LEAK is still BURNED."""
    if not isinstance(leak, dict) or leak.get("status") != "LEAK":
        out = dict(detection)
        if isinstance(leak, dict) and leak.get("status") not in (None, "NO_SHEET"):
            out["sheet_leak"] = {k: leak.get(k) for k in ("status", "leak_frames", "best_score", "error")
                                 if leak.get(k) is not None}
        return out
    out = dict(detection)
    out["status"] = "BURNED"
    out["burned_frames"] = int(detection.get("burned_frames") or 0) + int(leak.get("leak_frames") or 0)
    out[SHEET_LEAK_FLAG] = True
    out["sheet_leak"] = {k: leak.get(k) for k in ("status", "leak_frames", "longest_run", "best_score", "hits")
                         if leak.get(k) is not None}
    return out


def residual_text_band(hits: list[dict[str, Any]] | None, band: tuple[float, float] = SUBTITLE_BAND
                       ) -> dict[str, Any] | None:
    """The vertical band (fractions of the frame) of the burned text a kept take still carries, from its detection
    hits (``y_centre`` + ``glyph_px_at_720``), when it sits in our subtitle band; None otherwise.  Pure."""
    ys = []
    for h in hits or []:
        try:
            y = float(h.get("y_centre"))
        except (TypeError, ValueError):
            continue
        if band[0] <= y <= band[1]:
            half = max(0.012, float(h.get("glyph_px_at_720") or 52) / 1280.0 / 2.0 + 0.008)
            ys.append((y - half, y + half))
    if not ys:
        return None
    return {"y0": round(max(0.0, min(a for a, _ in ys)), 4), "y1": round(min(1.0, max(b for _, b in ys)), 4),
            "hits": len(ys)}


def residual_band_texts(hits: list[dict[str, Any]] | None, band: tuple[float, float] = SUBTITLE_BAND,
                        limit: int = 6) -> list[str]:
    """The OCR texts of a kept take's burned hits inside our subtitle band (unique, in order) -- S7 compares them
    with the unit's cues: a burned line that IS the cue's line suppresses our copy instead of stacking under it
    (JA-01 E07 VU-004, 2026-11-22).  Pure."""
    out: list[str] = []
    for h in hits or []:
        try:
            y = float(h.get("y_centre"))
        except (TypeError, ValueError):
            continue
        text = str(h.get("text") or "").strip()
        if text and band[0] <= y <= band[1] and text not in out:
            out.append(text)
            if len(out) >= limit:
                break
    return out


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
#: S6 burned-text retry n -> (crop fraction, JPEG quality) of @Image1 (2026-11-22, E23 device 1101: the one-pixel
#: nudge of PR #278 changed the request bytes but the renders stayed near-identical -- VU-004 11/11/11, VU-006
#: 14/14/14 burned frames over three takes); a 1.5 % / 3 % scale jitter moves every latent of the opening frame
#: while the framing stays the same to the eye
S6_STEPS = {1: (0.015, 88), 2: (0.03, 83)}
#: the final-fix redo itself (before any of its own burn retries) follows two failed S6 retries: the S6 maximum
S6_FINAL_FIX_REDO_STEP = S6_STEPS[max(S6_STEPS)]
#: S6 burned-text retry index from which the identity sheets go out as their front-view face crop (send time only)
SHEET_CROP_FROM = 2


def s6_escalation(index: int) -> dict[str, Any]:
    """What S6 burned-text retry ``index`` changes in the request (free first, all at the same price): the prompt
    (retry sentence as the first line; from :data:`DIALOGUE_MARK_FROM` the dialogue literals framed as heard
    speech), @Image1 (:data:`S6_STEPS` scale jitter) and, from :data:`SHEET_CROP_FROM`, every identity sheet sent
    as its front-view crop.  Duration and the start keyframe are never changed: the unit's length is bound to the
    cut and the start frame to the predecessor's tail (continuity), and both would cost more."""
    if index <= 0:
        return {"retry": 0}
    frac, quality = S6_STEPS.get(index) or S6_STEPS[max(S6_STEPS)]
    return {"retry": index, "prompt": "LEAD_SENTENCE" + ("+DIALOGUE_HEARD_MARK" if index >= DIALOGUE_MARK_FROM
                                                         else ""),
            "image1": f"CROP_SCALE_{frac * 100:g}PCT_JPEG_Q{quality}", "sheet_front_crop": index >= SHEET_CROP_FROM}


def perturb_start_frame_strong(data: bytes, index: int, retry: int,
                               steps: dict[int, tuple[float, int]] | None = None) -> tuple[bytes, dict[str, Any]]:
    """A STRONGER @Image1 perturbation for a final-fix burned-text redo retry (line owner 2026-11-20, E18: the
    one-pixel nudge only re-rolls the seed and three of four redone units burned the same line again).

    Retry ``retry`` (1..2) crops ``STRONG_STEPS[retry][0]`` of the width / height (1 % then 2 %) at a retry-indexed
    offset, scales back to the original size (aspect and framing kept: a 1-2 % scale jitter), nudges one pixel and
    re-encodes at a different JPEG quality.  Never raises; falls back to :func:`perturb_start_frame`."""
    if retry <= 0:
        return perturb_start_frame(data, index)
    table = steps or STRONG_STEPS
    frac, quality = table.get(retry) or table[max(table)]
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
                         "status": "PERTURBED", "method": f"CROP_SCALE_{frac * 100:g}PCT_JPEG_Q{quality}",
                         "crop_box": list(box), "size": [w, h], "sha256_after": hashlib.sha256(encoded).hexdigest()}
    except Exception as exc:  # noqa: BLE001 - the plain perturbation still changes the bytes
        encoded, note = perturb_start_frame(data, index + retry)
        return encoded, {**note, "final_fix_burn_retry": retry, "strong_error": f"{type(exc).__name__}: {exc}"[:200]}


# ------------------------------------------------------------------------------------ request fingerprint
#: the request fields that decide what H3 renders (HopsAPI returns a byte-identical clip for an identical request;
#: upload URLs are NOT part of it -- a new URL for the same bytes renders the same clip)
FINGERPRINT_FIELDS = ("prompt_sha256", "sent_reference_sha256", "sent_audio_sha256", "duration", "resolution",
                      "aspect_ratio", "model")
SAME_REQUEST_LOG = "S6_BURN_RETRY_SAME_REQUEST"
SAME_RENDER_LOG = "S6_BURN_RETRY_SAME_RENDER"


def request_content_fingerprint(*, prompt: str, sent_reference_sha256: list[str], sent_audio_sha256: list[Any],
                                duration: Any, resolution: Any, aspect_ratio: Any, model: Any) -> dict[str, Any]:
    """The content fingerprint of one provider request (pure): the sent prompt's sha and every sent reference's
    sha (the bytes H3 received, after the send-time re-encode / perturbation / crop), never the upload URLs."""
    row = {"prompt_sha256": hashlib.sha256(str(prompt).encode("utf-8")).hexdigest(),
           "sent_reference_sha256": [str(v) for v in sent_reference_sha256 or []],
           "sent_audio_sha256": [str(v) for v in sent_audio_sha256 or [] if v],
           "duration": duration, "resolution": str(resolution or "").lower() or None,
           "aspect_ratio": aspect_ratio, "model": model}
    row["digest"] = hashlib.sha256(json.dumps({k: row[k] for k in FINGERPRINT_FIELDS}, sort_keys=True,
                                              ensure_ascii=False).encode("utf-8")).hexdigest()
    return row


def request_fingerprint(transaction: dict[str, Any] | None) -> dict[str, Any] | None:
    """The content fingerprint a submitter transaction recorded (``request_content_fingerprint``), or one rebuilt
    from its sent shas (transactions written before 2026-11-22: the prompt sha is then the prompt FILE sha, which
    is the sent prompt -- the submitter refuses any other); None without sent reference shas."""
    row = transaction or {}
    recorded = row.get("request_content_fingerprint")
    if isinstance(recorded, dict) and recorded.get("digest"):
        return dict(recorded)
    if not row.get("sent_reference_sha256"):
        return None
    out = {"prompt_sha256": row.get("sent_prompt_sha256") or row.get("prompt_sha256"),
           "sent_reference_sha256": [str(v) for v in row.get("sent_reference_sha256") or []],
           "sent_audio_sha256": [str(v) for v in row.get("sent_audio_sha256") or [] if v],
           "duration": (row.get("provider_request_input") or {}).get("duration"),
           "resolution": str((row.get("provider_request_input") or {}).get("resolution")
                             or row.get("resolution") or "").lower() or None,
           "aspect_ratio": (row.get("provider_request_input") or {}).get("aspect_ratio"),
           "model": row.get("model"), "rebuilt": True}
    out["digest"] = hashlib.sha256(json.dumps({k: out.get(k) for k in FINGERPRINT_FIELDS}, sort_keys=True,
                                              ensure_ascii=False).encode("utf-8")).hexdigest()
    return out


def request_delta(previous: dict[str, Any] | None, current: dict[str, Any] | None) -> dict[str, Any]:
    """What changed between two request fingerprints (pure): {status: CHANGED|SAME|UNKNOWN, changed: [...]}.
    SAME means the provider got the identical request again -- a retry that cannot render anything new."""
    if not previous or not current or not previous.get("digest") or not current.get("digest"):
        return {"status": "UNKNOWN", "changed": []}
    changed = [k for k in FINGERPRINT_FIELDS if k != "sent_reference_sha256" and previous.get(k) != current.get(k)]
    before, after = previous.get("sent_reference_sha256") or [], current.get("sent_reference_sha256") or []
    for i in range(max(len(before), len(after))):
        if (before[i] if i < len(before) else None) != (after[i] if i < len(after) else None):
            changed.append(f"image{i + 1}")
    status = "SAME" if previous["digest"] == current["digest"] else "CHANGED"
    return {"status": status, "changed": changed if status == "CHANGED" else []}


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


ENV_SUSPECT = "NALU_S6_SUSPECT_TEXT"
#: OCR frames kept per take for the strict burned-line check (4 fps x 15 s)
MAX_OCR_FRAMES = 60


def band_frame_row(t: float, image: Any, raw: list | None, band: tuple[float, float] | None = None
                   ) -> dict[str, Any]:
    """One sampled frame's raw OCR boxes of the subtitle-band crop in full-frame pixels -- the per-frame detail the
    strict burned-line check (subtitle_text_match.strict_burned_line_check) reads: {t, w, h, boxes: [{text, score,
    box: [x0, y0, x1, y1]}]}.  Boxes without text are dropped; nothing else is filtered (the check filters)."""
    import tail_frame_text_clean as _ttc  # noqa: PLC0415
    h, w = image.shape[:2]
    y_off = int(round(h * (band or (_ttc.BAND_Y0, _ttc.BAND_Y1))[0]))
    boxes = []
    for box, text, score in raw or []:
        if not str(text or "").strip():
            continue
        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) + y_off for p in box]
        boxes.append({"text": str(text), "score": round(float(score), 4),
                      "box": [int(min(xs)), int(min(ys)), int(round(max(xs))), int(round(max(ys)))]})
    return {"t": t, "w": int(w), "h": int(h), "boxes": boxes}


#: the strict burned-line check reads the kept take at the prototype's rate (every 2nd frame at 24 fps): at the S6
#: 4 fps a correct, steady line measured SIZE_JITTER 0.066 / 0.093 (p95 - p5 of ~10 integer-pixel box heights) and
#: was rejected; at 12 fps the same clips measure 0.02
STRICT_FPS = 12.0


def ocr_band_frames(video: Path, lang: str = "zh", *, fps: float = STRICT_FPS, frames: FrameReader | None = None,
                    ocr: Any = None, model: str | None = None) -> dict[str, Any]:
    """Re-read a kept take's subtitle band with the recogniser of the dialogue language (tools/ocr_lang_models):
    {model, lang, sample_fps, frames} for the strict burned-line check in S7, or {error} -- never raises."""
    out: dict[str, Any] = {"lang": lang, "sample_fps": fps, "source": "S7_REOCR"}
    try:
        reader = frames or _cv2_frames
        if ocr is None:
            import ocr_lang_models as _olm  # noqa: PLC0415
            engine, model = _olm.engine(lang)  # no fallback: a wrong recogniser must not feed the strict check

            def ocr(img: Any) -> list:
                return engine(img)[0] or []
        import tail_frame_text_clean as _ttc  # noqa: PLC0415
        rows = []
        for t, image in reader(Path(video), fps):
            h = image.shape[0]
            crop = image[int(round(h * _ttc.BAND_Y0)):int(round(h * _ttc.BAND_Y1))]
            rows.append(band_frame_row(t, image, ocr(crop)))
        out.update(model=model or "injected", frames=rows)
    except Exception as exc:  # noqa: BLE001 - no frames: the strict check cannot accept (our cue is kept)
        out["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    return out


def suspect_pass_enabled(env: dict[str, str] | None = None) -> bool:
    value = str((env if env is not None else os.environ).get(ENV_SUSPECT, "1")).strip().lower()
    return value not in ("0", "off", "false", "no")


def detect(video: Path, *, fps: float = SAMPLE_FPS, ocr: Any = None, frames: FrameReader | None = None,
           min_consecutive: int = MIN_CONSECUTIVE, lines: list[str] | None = None, lang: str = "zh",
           suspect_ocr: Any = None) -> dict[str, Any]:
    """Burned caption text in a raw H3 clip.  Never raises.

    ``status``: BURNED (hits in >= ``min_consecutive`` consecutive samples), CLEAN, or FAIL_OPEN (cannot measure:
    treated as clean by the caller).  ``burned_frames`` counts every sample with a hit (the best-take measure).

    Two passes per sample: the subtitle-band pass (tail_frame_text_clean.find_text_boxes) and, from 2026-11-23 (E24
    review: garbled 「不姒伴」「揞哓」 and a 198 px mid-frame placard 「樸花美娇」 slipped through), a whole-frame pass
    (find_suspect_text_boxes: score >= 0.4, any orientation / position, area <= 25 %) that keeps only text saying
    the unit's ``lines`` or garbled text; its hits carry ``pass: WHOLE_FRAME`` + ``kind``.  The whole-frame pass runs
    with the default engine (or ``suspect_ocr``); an injected band ``ocr`` without ``suspect_ocr`` skips it, and
    ``NALU_S6_SUSPECT_TEXT=off`` disables it.  ``ocr_frames``: every sample's raw band boxes (band_frame_row) for
    the strict burned-line check, recorded with the recogniser id ``ocr_model``."""
    started = time.perf_counter()
    out: dict[str, Any] = {"schema": SCHEMA, "video": str(video), "fps": fps, "min_consecutive": min_consecutive}
    try:
        import tail_frame_text_clean as _ttc  # noqa: PLC0415 - same OCR engine + filters as the tail cleaner
        reader = frames or _cv2_frames
        model = "injected"
        if ocr is None:
            base, model = _language_ocr(lang)
            out["ocr_model"] = model
        else:
            base = ocr
        if suspect_ocr is None and ocr is None and suspect_pass_enabled():
            suspect_ocr = base
        raw_seen: list[Any] = []

        def engine(img: Any) -> list:
            result = base(img)
            raw_seen.append(result)
            return result
        flags: list[bool] = []
        hits: list[dict[str, Any]] = []
        ocr_frames: list[dict[str, Any]] = []
        suspects = 0
        for t, image in reader(Path(video), fps):
            raw_seen.clear()
            boxes = _ttc.find_text_boxes(image, engine)
            if len(ocr_frames) < MAX_OCR_FRAMES:
                ocr_frames.append(band_frame_row(t, image, raw_seen[0] if raw_seen else []))
            extra: list[dict[str, Any]] = []
            if suspect_ocr is not None:
                try:
                    extra = _ttc.find_suspect_text_boxes(image, suspect_ocr, lines=lines, lang=lang, skip=boxes)
                except Exception as exc:  # noqa: BLE001 - the band pass still counts
                    out.setdefault("suspect_error", f"{type(exc).__name__}: {str(exc)[:160]}")
            flags.append(bool(boxes or extra))
            h = float(image.shape[0])
            for b in boxes:
                hits.append({"t": t, "text": b["text"], "score": b["score"],
                             "glyph_px_at_720": b["glyph_px_at_720"],
                             "y_centre": round((b["y0"] + b["y1"]) / 2.0 / h, 3)})
            for b in extra:
                suspects += 1
                hits.append({"t": t, "text": b["text"], "score": b["score"], "glyph_px_at_720": b["glyph_px_at_720"],
                             "y_centre": round((b["y0"] + b["y1"]) / 2.0 / h, 3),
                             "x_centre": round((b["x0"] + b["x1"]) / 2.0 / float(image.shape[1]), 3),
                             "pass": "WHOLE_FRAME", "kind": b["kind"], **({"vertical": True} if b["vertical"] else {})})
        run = longest_run(flags)
        out.update(status="BURNED" if run >= min_consecutive else "CLEAN", frames_sampled=len(flags),
                   burned_frames=sum(flags), longest_run=run, hits=hits[:40], ocr_frames=ocr_frames,
                   ocr_model=model,
                   **({"suspect_hits": suspects} if suspects else {}))
    except Exception as exc:  # noqa: BLE001 - fail-open: never block the line on the detector
        out.update(status="FAIL_OPEN", error=f"{type(exc).__name__}: {exc}"[:300], burned_frames=0)
    out["elapsed_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
    return out


def _language_ocr(lang: str) -> tuple[Any, str]:
    """(OCR callable, recogniser id) for the dialogue language: RapidOCR's bundled recogniser for zh / en, the pinned
    Japanese / Korean recogniser for ja / ko (tools/ocr_lang_models; the bundled one misses kana -- lab 2026-11-23:
    an all-kana burned line read as nothing).  A language model that cannot be loaded falls back to the bundled
    recogniser (the detector behaves as before; the strict check then re-reads or rejects)."""
    import tail_frame_text_clean as _ttc  # noqa: PLC0415
    try:
        import ocr_lang_models as _olm  # noqa: PLC0415
        if _olm.model_id(lang) == _olm.DEFAULT_MODEL_ID:
            return _ttc._default_ocr, _olm.DEFAULT_MODEL_ID
        engine, model = _olm.engine(lang)

        def ocr(img: Any) -> list:
            return engine(img)[0] or []
        return ocr, model
    except Exception:  # noqa: BLE001
        return _ttc._default_ocr, "rapidocr_onnxruntime-1.4.4-default"


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
    """The take with the fewest burned frames, then the least camera wobble (``wobble_pct``, the set's excursion);
    on a tie the latest (it carries the strongest prompt)."""
    rows = [t for t in takes if t.get("path")]
    if not rows:
        return None
    return min(reversed(rows), key=lambda t: (int(t.get("burned_frames") or 0), float(t.get("wobble_pct") or 0.0)))


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
