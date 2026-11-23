#!/usr/bin/env python3
"""Fuzzy match between a subtitle cue and text read off the picture (OCR) -- stdlib only, language-agnostic.

JA-01 E07 on device 1485 (2026-11-22): at 0:13 (E07-VU-004) H3 burned the line 「言わないでくださいまし！」 into the
picture; the S6 burn retries stayed UNRESOLVED, S7 moved OUR caption of the same line just above the burned one
(--avoid-bands) and the viewer read the same line twice.  When the burned text IS the cue's line, the line is already
on screen: S7 suppresses our cue for that window (free) instead of stacking a second copy.  The same match finds two
stacked near-identical caption rows in the final cut (av_evidence_pack, post-S7 measurement).

Normalisation: NFKC, lower case, every character that is not a letter / digit / CJK / kana / hangul dropped (spaces,
punctuation, brackets, speaker labels' colons ...).  Similarity: max(SequenceMatcher ratio, partial coverage of the
shorter string when it holds >= MIN_PARTIAL_UNITS characters and >= half of the longer one) -- an OCR read that
caught most of the line, or a cue that is one sequential piece of a split line, still matches.

2026-11-23: the fuzzy match is NOT used to suppress a cue any more (it accepted wrong burned lines); S7 decides with
:func:`strict_burned_line_check` (bottom of this module).  The fuzzy match remains a FLAG source (post-S7 stacked rows,
the S6 whole-frame pass), where a false positive only costs a look.
"""
from __future__ import annotations

import difflib
import unicodedata
from typing import Any, Iterable

#: a burned read whose similarity to the cue reaches this is the same line (owner order 2026-11-22: ~0.6)
DUPLICATE_THRESHOLD = 0.6
MIN_UNITS = 2
MIN_PARTIAL_UNITS = 4


def normalise(text: Any) -> str:
    raw = unicodedata.normalize("NFKC", str(text or "")).lower()
    # a leading speaker label ("林岚：" / "Lin:") is not part of what the picture shows
    for sep in ("：", ":"):
        at = raw.find(sep)
        if 0 <= at < 24 and at < len(raw) - 1:
            raw = raw[at + 1:]
            break
    return "".join(ch for ch in raw if ch.isalnum())


def similarity(a: Any, b: Any) -> float:
    """0..1 similarity of two texts after :func:`normalise`; 0 when either has fewer than MIN_UNITS characters."""
    x, y = normalise(a), normalise(b)
    if len(x) < MIN_UNITS or len(y) < MIN_UNITS:
        return 0.0
    if x == y:
        return 1.0
    matcher = difflib.SequenceMatcher(None, x, y, autojunk=False)
    ratio = matcher.ratio()
    short, long_ = (x, y) if len(x) <= len(y) else (y, x)
    partial = 0.0
    if len(short) >= MIN_PARTIAL_UNITS and len(short) * 2 >= len(long_):
        matched = sum(block.size for block in matcher.get_matching_blocks())
        partial = matched / float(len(short))
    return round(max(ratio, partial), 3)


def best_match(cue: Any, reads: Iterable[Any]) -> tuple[float, str]:
    """(best similarity, the read) of a cue against several OCR reads -- each read alone and all of them joined
    (a line the OCR split into two boxes)."""
    rows = [str(r) for r in reads or [] if normalise(r)]
    best, which = 0.0, ""
    for read in rows + (["".join(rows)] if len(rows) > 1 else []):
        score = similarity(cue, read)
        if score > best:
            best, which = score, read
    return best, which


def is_duplicate(cue: Any, reads: Iterable[Any], threshold: float = DUPLICATE_THRESHOLD) -> bool:
    return best_match(cue, reads)[0] >= threshold


def stacked_duplicate(rows: list[tuple[float, str]], *, min_gap: float = 0.02,
                      threshold: float = DUPLICATE_THRESHOLD) -> dict[str, Any] | None:
    """Two caption-band text rows of ONE frame, ``[(y_centre fraction, text), ...]``, that say the same line:
    {texts, ys, similarity} of the most similar pair at least ``min_gap`` apart vertically, else None.  Our own
    two-row caption holds two DIFFERENT halves of a line, so it never matches itself."""
    best = None
    ordered = sorted((float(y), str(t)) for y, t in rows if normalise(t))
    for i, (ya, ta) in enumerate(ordered):
        for yb, tb in ordered[i + 1:]:
            if yb - ya < min_gap:
                continue
            score = similarity(ta, tb)
            if score >= threshold and (best is None or score > best["similarity"]):
                best = {"texts": [ta, tb], "ys": [round(ya, 3), round(yb, 3)], "similarity": score}
    return best


# ============================================================================ strict "is the burned line correct?"
# Owner fallback 2026-11-23 (prototype ~/Desktop/烧字后期方案对比/scripts/strict_burn_check.py): the >= 0.6 fuzzy match
# above accepted T3's 「…教习嬷媽…」 (0.962), a line missing a character (1.0), 「…看上你妈」 (0.889) and a
# traditional-character copy (0.75) as "the cue's line" -- S7 then suppressed our correct caption and the viewer read a
# WRONG line.  Suppressing our cue is only allowed when the picture provably shows exactly the cue's line, stably.
# Everything else keeps our cue (moved clear of the burned band) and the unit goes to the final fix round.

ACCEPT_CORRECT = "ACCEPT_CORRECT"
REJECT_WRONG = "REJECT_WRONG"
REJECT_UNSTABLE = "REJECT_UNSTABLE"
NO_BURN = "NO_BURN"
STRICT_SCHEMA = "nalu.strict_burned_line_check.v1"

#: the thresholds of the strict rule (owner 2026-11-23)
STRICT_RULE = {
    "min_stable_cover": 0.90,      # >= 90 % of text-bearing frames read one of the accepted segments
    "min_mean_conf": 0.90,         # mean OCR confidence of the accepted frames
    "min_box_conf": 0.80,          # no box of an accepted frame below this
    "max_size_jitter": 0.06,       # glyph height (p95 - p5) / median, per segment
    "max_position_jitter": 0.01,   # box centre (p95 - p5), fraction of the frame height, per segment
    "min_stable_seconds": 0.25,    # a segment holds >= this long (and >= 2 samples)
    "min_glyph_width_frac": 0.05,  # a box lower than 5 % of the frame width is set dressing, not a caption
    "texture_score": 0.70,         # a 1-2 character box below this score is texture, not text
}

#: Japanese punctuation the recogniser reads as a look-alike glyph (lab 2026-11-23: 「素敵ですわ、セイン様」 read as
#: 「素敵ですわーセイン様」 by japan_PP-OCRv4_rec_mobile).  A look-alike is accepted ONLY at a position where the cue
#: itself has punctuation, at most once per position -- a real character can never be swapped through it.
PUNCT_LOOKALIKES = {
    "ja": {"、": "ー一丶ヽ", "，": "ー一丶ヽ", "。": "o0〇口", "…": "ー一", "‥": "ー一", "・": "ー一",
           "～": "ー一", "〜": "ー一", "―": "ー一", "—": "ー一"},
}


def strict_normalise(text: Any) -> str:
    """NFKC, lower case, letters / digits / CJK / kana / hangul only -- NO simplified / traditional folding and NO
    speaker-label stripping (a burned speaker label is not the line)."""
    raw = unicodedata.normalize("NFKC", str(text or "")).lower()
    return "".join(ch for ch in raw if ch.isalnum())


def _cue_chars(text: Any, lang: str) -> tuple[str, dict[int, str]]:
    """(normalised cue, {position: look-alike glyphs allowed before that character}) for ``lang``."""
    table = PUNCT_LOOKALIKES.get(str(lang or "").lower()[:2]) or {}
    chars, gaps = [], {}
    for ch in str(text or ""):
        kept = strict_normalise(ch)
        if kept:
            chars.append(kept)
            continue
        allowed = table.get(ch) or table.get(unicodedata.normalize("NFKC", ch))
        if allowed:
            pos = len("".join(chars))
            gaps[pos] = gaps.get(pos, "") + allowed
    return "".join(chars), gaps


def _spells(read: str, cue: str, gaps: dict[int, str]) -> bool:
    """``read`` is exactly ``cue``, allowing one punctuation look-alike at each punctuation position of the cue."""
    i = j = 0
    used: set[int] = set()
    while i < len(read):
        if j < len(cue) and read[i] == cue[j]:
            i += 1
            j += 1
        elif j in gaps and j not in used and read[i] in gaps[j]:
            used.add(j)
            i += 1
        else:
            return False
    return j == len(cue)


def _canonical(read: str, lines: list[tuple[str, dict[int, str]]]) -> str:
    """A frame read that spells a contiguous piece of one of the unit's lines (punctuation look-alikes allowed at
    the line's punctuation) is replaced by that exact piece, so 「素敵ですわーセイン様」 and 「素敵ですわセイン様」 --
    two reads of the same picture -- are one stable segment.  Any other read is returned unchanged."""
    best = ""
    for cue, gaps in lines:
        for j in range(len(cue)):
            i, k, used = 0, j, set()
            while i < len(read):
                if k < len(cue) and read[i] == cue[k]:
                    i += 1
                    k += 1
                elif k in gaps and k not in used and k > j and read[i] in gaps[k]:
                    used.add(k)
                    i += 1
                else:
                    break
            if i == len(read) and k > j and len(cue[j:k]) > len(best):
                best = cue[j:k]
    return best or read


def _percentile(values: list[float], q: float) -> float:
    """Linear-interpolated percentile (numpy's default), stdlib only."""
    xs = sorted(values)
    if not xs:
        return 0.0
    k = (len(xs) - 1) * q / 100.0
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def _frame_boxes(frame: dict[str, Any]) -> list[dict[str, float | str]]:
    """The caption-like boxes of one OCR frame -> [{text, score, h, yc, xc}] in reading order.

    Frame shape (h3_burn_retry.band_frame_row): {t, w, h, boxes: [{text, score, box: [x0, y0, x1, y1] px}]}; the
    prototype rows {t, boxes: [{t, s, h, yc, xc}]} are read too."""
    width, height = float(frame.get("w") or 0), float(frame.get("h") or 0)
    out = []
    for b in frame.get("boxes") or []:
        text = str(b.get("text", b.get("t", "")) or "")
        score = float(b.get("score", b.get("s", 0.0)) or 0.0)
        box = b.get("box")
        if isinstance(box, (list, tuple)) and len(box) == 4 and height > 0:
            x0, y0, x1, y1 = (float(v) for v in box)
            gh, yc, xc = y1 - y0, (y0 + y1) / 2.0 / height, (x0 + x1) / 2.0 / (width or height)
        else:
            gh, yc, xc = float(b.get("h") or 0.0), float(b.get("yc") or 0.0), float(b.get("xc") or 0.0)
        norm = strict_normalise(text)
        if not norm:
            continue
        if width and gh < STRICT_RULE["min_glyph_width_frac"] * width:
            continue
        if score < STRICT_RULE["texture_score"] and len(norm) <= 2:
            continue
        out.append({"text": text, "norm": norm, "score": score, "h": gh, "yc": yc, "xc": xc})
    out.sort(key=lambda x: (round(float(x["yc"]), 2), float(x["xc"])))
    return out


def _partition(segments: list[str], lines: list[tuple[str, dict[int, str]]]) -> list[int] | None:
    """Assign the stable segments, in order, to the unit's lines, in order: each line takes a run of consecutive
    segments that together spell it exactly (lines may be absent).  Returns the line index of every segment, or None
    when the segments cannot be read as the unit's lines (wrong / extra / missing characters)."""
    memo: dict[tuple[int, int], list[int] | None] = {}

    def go(i: int, k: int) -> list[int] | None:
        if i == len(segments):
            return []
        if k == len(lines) or (i, k) in memo:
            return memo.get((i, k))
        found = None
        cue, gaps = lines[k]
        acc = ""
        for end in range(i, len(segments)):
            acc += segments[end]
            if _spells(acc, cue, gaps):
                rest = go(end + 1, k + 1)
                if rest is not None:
                    found = [k] * (end - i + 1) + rest
                    break
        if found is None:
            found = go(i, k + 1)  # this line is not burned
        memo[(i, k)] = found
        return found

    return go(0, 0)


def strict_burned_line_check(frames_ocr: Any, cue_text: Any, lang: str = "zh", *,
                             spoken_window: tuple[float, float] | list[float] | None = None,
                             unit_lines: list[Any] | None = None, sample_fps: float | None = None) -> dict[str, Any]:
    """Is the text H3 burned into the picture EXACTLY the cue's line?  Pure, never raises.

    ``frames_ocr``: per sampled frame of the unit's kept take, the OCR boxes of our subtitle band
    (:func:`_frame_boxes` shapes), with ``t`` in the clip's seconds.  ``spoken_window``: (start, end) of the spoken
    line in the same clip seconds (S7 ASR / cue timing).  ``unit_lines``: every line of the unit in order (the cue's
    line among them) -- the burned segments must read as the unit's lines, nothing else.

    ACCEPT_CORRECT only when all of: the stable OCR segments (>= 0.25 s each), in time order, spell the unit's lines
    and the cue's line in full EXACTLY (NFKC, punctuation dropped, no simplified / traditional folding; Japanese
    punctuation look-alikes only at the cue's punctuation); >= 90 % of the text-bearing frames read one of those
    segments; mean OCR confidence >= 0.90 and no box < 0.80; glyph-size jitter <= 6 % and position jitter <= 1 % of
    the frame height per segment; the burned window overlaps the spoken window.  Otherwise REJECT_WRONG (text or
    timing), REJECT_UNSTABLE (reads / confidence / jitter / no usable OCR) or NO_BURN (no caption text for this
    line)."""
    rule = STRICT_RULE
    out: dict[str, Any] = {"schema": STRICT_SCHEMA, "lang": lang, "cue": str(cue_text or ""), "reasons": []}
    try:
        cue, gaps = _cue_chars(cue_text, lang)
        out["expected"] = cue
        if not cue:
            return {**out, "verdict": REJECT_UNSTABLE, "reasons": ["EMPTY_CUE"]}
        if not isinstance(frames_ocr, list):
            return {**out, "verdict": REJECT_UNSTABLE, "reasons": ["NO_OCR_FRAME_DETAIL"]}
        lines = [x for x in (unit_lines or []) if strict_normalise(x)] or [cue_text]
        if not any(_cue_chars(x, lang)[0] == cue for x in lines):
            lines = [*lines, cue_text]
        parsed = [_cue_chars(x, lang) for x in lines]
        targets = [k for k, p in enumerate(parsed) if p[0] == cue]
        rows = []
        for f in frames_ocr:
            if not isinstance(f, dict) or f.get("t") is None:
                continue
            boxes = _frame_boxes(f)
            read = "".join(str(b["norm"]) for b in boxes)
            rows.append({"t": float(f["t"]), "boxes": boxes, "raw_read": read,
                         "read": _canonical(read, parsed) if read else read})
        rows.sort(key=lambda r: r["t"])
        if not rows:
            return {**out, "verdict": REJECT_UNSTABLE, "reasons": ["NO_OCR_FRAME_DETAIL"]}
        if sample_fps is None:
            steps = sorted(b["t"] - a["t"] for a, b in zip(rows, rows[1:]) if b["t"] > a["t"])
            sample_fps = 1.0 / steps[len(steps) // 2] if steps else 4.0
        out["sample_fps"] = round(float(sample_fps), 3)
        text_rows = [r for r in rows if r["read"]]
        out["text_frames"] = len(text_rows)
        if not text_rows:
            return {**out, "verdict": NO_BURN}
        # runs of identical reads over the text-bearing frames (an empty sample in between does not break a run)
        runs: list[dict[str, Any]] = []
        for r in text_rows:
            if runs and runs[-1]["read"] == r["read"]:
                runs[-1]["frames"].append(r)
            else:
                runs.append({"read": r["read"], "frames": [r]})
        min_frames = max(2, int(round(rule["min_stable_seconds"] * float(sample_fps))))
        stable = [u for u in runs if len(u["frames"]) >= min_frames]
        out["distinct_reads"] = sorted({r["raw_read"] for r in text_rows})[:12]
        if not stable:
            return {**out, "verdict": REJECT_UNSTABLE, "reasons": ["NO_STABLE_SEGMENT"]}

        def merged(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
            seq: list[dict[str, Any]] = []
            for u in units:  # the same read again after a flicker of another read is one segment
                if seq and seq[-1]["read"] == u["read"]:
                    seq[-1] = {"read": u["read"], "frames": seq[-1]["frames"] + u["frames"]}
                else:
                    seq.append(u)
            return seq

        seq = merged(stable)
        owner = _partition([u["read"] for u in seq], parsed)
        if owner is None:
            # a karaoke build-up (each segment a prefix of the next) counts as its full segment
            grown = merged([u for k, u in enumerate(seq) if not (k + 1 < len(seq)
                                                                and seq[k + 1]["read"].startswith(u["read"]))])
            owner = _partition([u["read"] for u in grown], parsed)
            if owner is not None:
                seq = grown
        out["segments"] = [u["read"] for u in seq]
        if owner is None:
            return {**out, "verdict": REJECT_WRONG,
                    "reasons": [f"TEXT_MISMATCH read={'|'.join(out['segments'])!r} expected={cue!r}"
                                + (f" (unit lines {'|'.join(p[0] for p in parsed)!r})" if len(parsed) > 1 else "")]}
        mine = [u for u, k in zip(seq, owner) if k in targets]
        if not mine:
            return {**out, "verdict": NO_BURN, "reasons": ["LINE_NOT_BURNED (other lines of the unit are)"]}
        reasons: list[str] = []
        accepted_reads = {u["read"] for u in seq}
        ok_rows = [r for r in text_rows if r["read"] in accepted_reads]
        cover = len(ok_rows) / float(len(text_rows))
        out["stable_cover"] = round(cover, 3)
        if cover < rule["min_stable_cover"]:
            reasons.append(f"UNSTABLE_READS {cover:.2f} of text frames read an accepted segment")
        frames = [r for u in mine for r in u["frames"]]
        scores = [float(b["score"]) for r in frames for b in r["boxes"]]
        mean = sum(scores) / len(scores) if scores else 0.0
        low = min(scores) if scores else 0.0
        out["mean_conf"], out["min_conf"] = round(mean, 3), round(low, 3)
        if mean < rule["min_mean_conf"]:
            reasons.append(f"LOW_OCR_CONF mean={mean:.2f}")
        if low < rule["min_box_conf"]:
            reasons.append(f"LOW_OCR_CONF_BOX min={low:.2f}")
        jitter = []
        for u in mine:
            hs = [sum(float(b["h"]) for b in r["boxes"]) / len(r["boxes"]) for r in u["frames"]]
            ys = [sum(float(b["yc"]) for b in r["boxes"]) / len(r["boxes"]) for r in u["frames"]]
            med = _percentile(hs, 50)
            hj = (_percentile(hs, 95) - _percentile(hs, 5)) / med if med > 0 else 1.0
            yj = _percentile(ys, 95) - _percentile(ys, 5)
            jitter.append({"segment": u["read"], "size": round(hj, 4), "position": round(yj, 4)})
            if hj > rule["max_size_jitter"]:
                reasons.append(f"SIZE_JITTER {hj:.3f} in {u['read']!r}")
            if yj > rule["max_position_jitter"]:
                reasons.append(f"POSITION_JITTER {yj:.4f} in {u['read']!r}")
        out["jitter"] = jitter
        burn = [min(r["t"] for r in frames), max(r["t"] for r in frames) + 1.0 / float(sample_fps)]
        out["burn_window"] = [round(burn[0], 3), round(burn[1], 3)]
        wrong: list[str] = []
        try:
            a, b = (float(v) for v in spoken_window)  # type: ignore[union-attr]
        except (TypeError, ValueError):
            a = b = None
        if a is None or b is None or b <= a:
            reasons.append("SPOKEN_WINDOW_UNKNOWN")
        else:
            out["spoken_window"] = [round(a, 3), round(b, 3)]
            if not (burn[0] < b and burn[1] > a):
                wrong.append(f"TIME_WINDOW_MISMATCH burned {out['burn_window']} vs spoken {out['spoken_window']}")
        if wrong:
            return {**out, "verdict": REJECT_WRONG, "reasons": wrong + reasons}
        if reasons:
            return {**out, "verdict": REJECT_UNSTABLE, "reasons": reasons}
        return {**out, "verdict": ACCEPT_CORRECT}
    except Exception as exc:  # noqa: BLE001 - a check that cannot decide never suppresses
        return {**out, "verdict": REJECT_UNSTABLE, "reasons": [f"CHECK_ERROR {type(exc).__name__}: {str(exc)[:160]}"]}
