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
