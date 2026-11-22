#!/usr/bin/env python3
"""Dialogue tail guard + post-line beat (owner 2026-11-19, published 《摄政王她又来找茬了》 episodes).

The last character of a line was sometimes cut mid-syllable at the jump to the next shot, and a line often
ended with no breath before the cut.  The cut after a line was placed from the ASR end of its last word (plus a
pad, or capped at the start of the next ASR segment), and Whisper's word end runs early on the final syllable,
most of all on Chinese finals and trailing vowels; with babble right after the line the cut landed exactly on
that early end, and the 80 ms equal-power cut crossfade then faded the syllable that was still sounding.

Two rules, used by tools/performance_cut (speaking units) and tools/dialogue_tail_trim (the older tail plan):

* tail guard: the cut after a line's last word is at least
  ``max(word_end + TAIL_GUARD_SECONDS, speech_end + SPEECH_END_PAD_SECONDS)`` where ``speech_end`` is where the
  unit's own audio energy (RMS dBFS frames, the S7 caller's ``_unit_energy_db``) decays below the line's speech
  level minus ``DECAY_DB`` for ``QUIET_SECONDS`` after the ASR end -- the true offset of the final syllable.
  Nothing (an unscripted line after it, a runtime budget, a min-length hold) cuts before the guard.
* post-line beat: when nothing follows the line in the take, hold ``POST_LINE_BEAT_SECONDS`` (0.5 s) after it;
  ``REACTION_BEAT_SECONDS`` (0.3 s) when the next shot is the listener's reaction or an authored L-cut.  Never
  below the guard.  ``NALU_S7_POST_LINE_BEAT_SECONDS`` or contract ``s7_post_line_beat_seconds`` sets the beat.

Pure functions; numpy-free (the frames are already measured locally by S7, free).
"""
from __future__ import annotations

import os
from typing import Any

TAIL_GUARD_SECONDS = 0.25
#: S7 edit invariant 1 (owner 2026-11-21, device 1101 E21 "cut off before finishing their line"; tools/
#: s7_edit_invariants): the cut after a LINE's last word (the end of a sentence, the only place tail_cut is used) is
#: at least this far after the word end, even when unscripted speech follows right away
SENTENCE_END_GUARD_SECONDS = 0.4
SPEECH_END_PAD_SECONDS = 0.10
POST_LINE_BEAT_SECONDS = 0.5
REACTION_BEAT_SECONDS = 0.3
MAX_BEAT_SECONDS = 1.5
SEARCH_SECONDS = 0.8
QUIET_SECONDS = 0.06
DECAY_DB = 18.0
FLOOR_DB = -45.0
HOP = 0.02
BEAT_ENV = "NALU_S7_POST_LINE_BEAT_SECONDS"
BEAT_FIELD = "s7_post_line_beat_seconds"
#: the final fix round (owner 2026-11-20, final_fix_round.py) widens the guard after a confirmed clipped tail
GUARD_ENV = "NALU_S7_TAIL_GUARD_SECONDS"
MAX_TAIL_GUARD_SECONDS = 0.8


def tail_guard_seconds(environ: dict[str, str] | None = None) -> float:
    """TAIL_GUARD_SECONDS, or ``NALU_S7_TAIL_GUARD_SECONDS`` (never below the default, at most 0.8 s)."""
    raw = str((os.environ if environ is None else environ).get(GUARD_ENV) or "").strip()
    try:
        return min(MAX_TAIL_GUARD_SECONDS, max(TAIL_GUARD_SECONDS, float(raw))) if raw else TAIL_GUARD_SECONDS
    except ValueError:
        return TAIL_GUARD_SECONDS


def speech_end(frames: list[float] | None, word_end: float, *, line_start: float | None = None,
               hop: float = HOP) -> float | None:
    """Where the line's sound actually stops: the first time after ``word_end`` the energy stays below the
    line's level - DECAY_DB (floor FLOOR_DB) for QUIET_SECONDS, searched up to SEARCH_SECONDS.  None when no
    frames, or the take stays loud all the way (speech runs straight on: the guard falls back to the word end)."""
    if not frames:
        return None
    lo = max(0, int((line_start if line_start is not None else max(0.0, word_end - 1.5)) / hop))
    hi = max(lo + 1, int(round(word_end / hop)))
    spoken = sorted(frames[lo:hi]) or sorted(frames[:hi])
    if not spoken:
        return None
    level = spoken[int(0.75 * (len(spoken) - 1))]
    threshold = max(FLOOR_DB, level - DECAY_DB)
    run = max(1, int(round(QUIET_SECONDS / hop)))
    i0 = int(round(word_end / hop))
    i_max = min(len(frames), i0 + int(round(SEARCH_SECONDS / hop)))
    for i in range(i0, i_max):
        window = frames[i:i + run]
        if len(window) == run and all(v <= threshold for v in window):
            return round(i * hop, 3)
    return None


def guard(word_end: float, frames: list[float] | None = None, *, line_start: float | None = None,
          hop: float = HOP, sentence_end: bool = False) -> dict[str, Any]:
    """{guard, speech_end}: the earliest cut that never clips the line's last syllable (``sentence_end``: the word
    ends a line, so the tail is at least SENTENCE_END_GUARD_SECONDS)."""
    end = speech_end(frames, word_end, line_start=line_start, hop=hop)
    g = word_end + max(tail_guard_seconds(), SENTENCE_END_GUARD_SECONDS if sentence_end else 0.0)
    if end is not None:
        g = max(g, end + SPEECH_END_PAD_SECONDS)
    return {"guard": round(g, 3), "speech_end": end, "word_end": round(float(word_end), 3)}


def post_line_beat(contract: dict[str, Any] | None = None, environ: dict[str, str] | None = None, *,
                   reaction: bool = False) -> float:
    """The hold after a line before the cut (configurable; shorter into a reaction / L-cut)."""
    env = os.environ if environ is None else environ
    value = env.get(BEAT_ENV)
    if value in (None, ""):
        value = (contract or {}).get(BEAT_FIELD)
    try:
        beat = float(value) if value not in (None, "") else POST_LINE_BEAT_SECONDS
    except (TypeError, ValueError):
        beat = POST_LINE_BEAT_SECONDS
    beat = min(MAX_BEAT_SECONDS, max(0.0, beat))
    return min(beat, REACTION_BEAT_SECONDS) if reaction else beat


def tail_cut(word_end: float, original: float, *, frames: list[float] | None = None,
             line_start: float | None = None, next_speech_start: float | None = None,
             beat: float = POST_LINE_BEAT_SECONDS, speech_gap: float = 0.05, hop: float = HOP,
             sentence_end: bool = True) -> dict[str, Any]:
    """The out point after a line: the beat (capped at unscripted speech that follows), never before the guard
    (a line's end: SENTENCE_END_GUARD_SECONDS at least, unless unscripted speech starts sooner -- then up to that
    speech, never below the plain guard), never past the clip.  Returns {cut, guard, speech_end, beat,
    capped_by_next_speech, guard_applied}."""
    g = guard(word_end, frames, line_start=line_start, hop=hop)
    if sentence_end:   # the line's end: >= SENTENCE_END_GUARD_SECONDS, yielding only to clearly separate speech
        floor = float(word_end) + SENTENCE_END_GUARD_SECONDS
        if next_speech_start is not None:
            floor = min(floor, float(next_speech_start) - speech_gap)
        g = {**g, "guard": round(max(g["guard"], floor), 3)}
    desired = float(word_end) + float(beat)
    capped = False
    if next_speech_start is not None and float(next_speech_start) - speech_gap < desired:
        desired, capped = float(next_speech_start) - speech_gap, True
    cut = max(g["guard"], desired)
    return {**g, "cut": round(min(float(original), cut), 3), "beat": round(float(beat), 3),
            "capped_by_next_speech": capped, "guard_applied": g["guard"] > desired}
