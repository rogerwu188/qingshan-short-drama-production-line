#!/usr/bin/env python3
"""S7 hard edit invariants (owner report 2026-11-21, device 1101 E21: "characters are often cut off before finishing
their line; there are even shots of 1-2 seconds where the character doesn't say anything before it cuts away; cuts
between shots are far too fast").

These are not gates: every S7 step that shortens or splits a shot asks this module where it may cut, and simply
does not cut anywhere else.

1. never inside spoken dialogue -- a cut lands at least ``tail_seconds`` after the end of the last word before it
   (TAIL_SECONDS 0.25 s; SENTENCE_TAIL_SECONDS 0.4 s after a line's last word / sentence-final punctuation) and at
   least HEAD_LEAD_SECONDS before the next word starts; a shot never starts mid-word.  Word timing is the ASR's
   (faster-whisper word timestamps) when present, else the segment (VAD-like) span.
2. minimum shot -- no visible shot shorter than ``min_shot_seconds()`` (1.2 s, ``NALU_S7_MIN_SHOT_SECONDS``); a shot
   that shows a speaking unit's picture without that unit's own line is either >= REACTION_MIN_SECONDS (a motivated
   reaction) or it is merged away (the neighbouring picture runs on over it; the sound never moves).
3. pacing -- the median kept unit length stays >= ``median_floor_seconds()`` (2.0 s,
   ``NALU_S7_MEDIAN_SHOT_FLOOR_SECONDS``): a pacing trim that would take it below is skipped.

Pure functions (no I/O); the S7 caller (nalu_pipeline), tools/performance_cut, lines/nalu/runtime/tools/
final_fix_round (STATIC_SHOT_SPLIT) and nalu_qa_defect_checklist (the post-S7 measurement) use them.
"""
from __future__ import annotations

import os
import re
from typing import Any, Iterable

SCHEMA = "nalu.s7_edit_invariants.v1"
MIN_SHOT_SECONDS = 1.2
MIN_SHOT_ENV = "NALU_S7_MIN_SHOT_SECONDS"
REACTION_MIN_SECONDS = 1.5
MEDIAN_FLOOR_SECONDS = 2.0
MEDIAN_FLOOR_ENV = "NALU_S7_MEDIAN_SHOT_FLOOR_SECONDS"
TAIL_SECONDS = 0.25
SENTENCE_TAIL_SECONDS = 0.4
HEAD_LEAD_SECONDS = 0.1
TAIL_GAP_FLAG_SECONDS = 0.15      # the post-S7 measurement: a line ending closer than this to the next cut
SPEECH_OVERLAP_SECONDS = 0.3      # a shot "contains" a line when at least this much speech plays under it
#: S7 J-cut (tools/dialogue_jcut.py, device 1101 E27 2026-11-25): the next speaker's line may start up to 0.2 s before
#: the picture cut on purpose; a cut this close after a line's START is that J-cut, not a cut inside the line
JCUT_HEAD_TOLERANCE_SECONDS = 0.25
SNAP_MAX_SECONDS = 1.0            # an unsafe join is moved at most this far to the nearest line boundary
STEP_SECONDS = 0.02
EPS = 1e-6
_SENTENCE_END = re.compile(r"[。！？!?…\.~～」』”\"]\s*$")


def _env_float(name: str, default: float, lo: float, hi: float, environ: dict[str, str] | None = None) -> float:
    raw = str((os.environ if environ is None else environ).get(name) or "").strip()
    try:
        value = float(raw) if raw else default
    except ValueError:
        value = default
    return min(hi, max(lo, value))


def min_shot_seconds(environ: dict[str, str] | None = None) -> float:
    """MIN_SHOT_SECONDS or ``NALU_S7_MIN_SHOT_SECONDS`` (0.8-3.0 s)."""
    return _env_float(MIN_SHOT_ENV, MIN_SHOT_SECONDS, 0.8, 3.0, environ)


def reaction_min_seconds(environ: dict[str, str] | None = None) -> float:
    return max(REACTION_MIN_SECONDS, min_shot_seconds(environ))


def median_floor_seconds(environ: dict[str, str] | None = None) -> float:
    """MEDIAN_FLOOR_SECONDS or ``NALU_S7_MEDIAN_SHOT_FLOOR_SECONDS`` (0-4 s; 0 disables the floor)."""
    return _env_float(MEDIAN_FLOOR_ENV, MEDIAN_FLOOR_SECONDS, 0.0, 4.0, environ)


def median(values: Iterable[float]) -> float | None:
    vals = sorted(float(v) for v in values)
    if not vals:
        return None
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2.0


# ------------------------------------------------------------------------------------------------ speech
def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None


def speech_words(segments: Any) -> list[dict[str, Any]]:
    """[{start, end, text, line_end}] from unit ASR segments: the word timestamps when the segment has them, else the
    segment itself as one span.  ``line_end`` marks the last word of a segment (a line) or sentence-final text."""
    out: list[dict[str, Any]] = []
    for seg in segments or []:
        if not isinstance(seg, dict):
            continue
        words = [w for w in seg.get("words") or [] if isinstance(w, dict)
                 and _num(w.get("start")) is not None and _num(w.get("end")) is not None]
        if words:
            for i, w in enumerate(words):
                text = str(w.get("word") or w.get("text") or "")
                out.append({"start": float(w["start"]), "end": max(float(w["start"]), float(w["end"])),
                            "text": text, "line_end": i == len(words) - 1 or bool(_SENTENCE_END.search(text))})
            continue
        a, b = _num(seg.get("start")), _num(seg.get("end"))
        if a is None or b is None or b <= a:
            continue
        out.append({"start": a, "end": b, "text": str(seg.get("text") or ""), "line_end": True})
    out.sort(key=lambda w: (w["start"], w["end"]))
    return out


def spans(segments: Any) -> list[tuple[float, float]]:
    return [(w["start"], w["end"]) for w in speech_words(segments)]


def tail_after(word: dict[str, Any]) -> float:
    return SENTENCE_TAIL_SECONDS if word.get("line_end") else TAIL_SECONDS


def cut_violation(t: float, words: list[dict[str, Any]]) -> dict[str, Any] | None:
    """What a cut at ``t`` (source seconds of the unit the words belong to) would clip, or None when the cut is safe:
    ``t`` is inside [start - HEAD_LEAD, end + tail] of no word.  ``need_at_or_after`` is the earliest safe point
    after every word it touches, ``or_at_or_before`` the latest safe point before them; ``mid_word`` the cut falls
    inside a word itself."""
    hit = [w for w in words if w["start"] - HEAD_LEAD_SECONDS + EPS < t < w["end"] + tail_after(w) - EPS]
    if not hit:
        return None
    inside = [w for w in hit if w["start"] + EPS < t < w["end"] - EPS]
    w0 = (inside or hit)[0]
    return {"word": w0.get("text"), "start": round(w0["start"], 3), "end": round(w0["end"], 3),
            "need_at_or_after": round(max(w["end"] + tail_after(w) for w in hit), 3),
            "or_at_or_before": round(min(w["start"] - HEAD_LEAD_SECONDS for w in hit), 3),
            "mid_word": bool(inside)}


def safe_intervals(words: list[dict[str, Any]], a: float, b: float) -> list[tuple[float, float]]:
    """Where inside [a, b] a cut may land (the complement of every word's protected span)."""
    blocked = sorted((w["start"] - HEAD_LEAD_SECONDS, w["end"] + tail_after(w)) for w in words)
    out: list[tuple[float, float]] = []
    cur = float(a)
    for lo, hi in blocked:
        if hi <= cur:
            continue
        if lo > cur:
            out.append((cur, min(lo, b)))
        cur = max(cur, hi)
        if cur >= b:
            break
    if cur < b:
        out.append((cur, float(b)))
    return [(round(x, 3), round(y, 3)) for x, y in out if y - x > -EPS and x <= b + EPS]


def snap(t: float, words: list[dict[str, Any]], a: float, b: float, max_shift: float = SNAP_MAX_SECONDS
         ) -> float | None:
    """The safe cut point nearest ``t`` inside [a, b] within ``max_shift``, or None."""
    best = None
    for lo, hi in safe_intervals(words, a, b):
        cand = min(max(t, lo), hi)
        if abs(cand - t) <= max_shift + EPS and (best is None or abs(cand - t) < abs(best - t)):
            best = cand
    return None if best is None else round(best, 3)


def speech_in(words: list[dict[str, Any]], a: float, b: float) -> float:
    return sum(max(0.0, min(b, w["end"]) - max(a, w["start"])) for w in words)


# ----------------------------------------------------------------------------------- shot splitting points
def split_points(words: list[dict[str, Any]], a: float, b: float, *, pieces: int = 2, min_s: float | None = None,
                 speaking: bool = False, reaction_s: float | None = None) -> list[float] | None:
    """``pieces - 1`` cut points inside [a, b], each at a line boundary (safe), every piece >= ``min_s`` and, for a
    speaking unit, every piece either carries speech (>= SPEECH_OVERLAP_SECONDS) or is >= ``reaction_s``.  The
    most even split is chosen; None when the take has no such split."""
    min_s = min_shot_seconds() if min_s is None else float(min_s)
    reaction_s = reaction_min_seconds() if reaction_s is None else float(reaction_s)
    safe = safe_intervals(words, a, b)
    cands: list[float] = []
    for lo, hi in safe:
        x = lo
        while x <= hi + EPS:
            if a + min_s - EPS <= x <= b - min_s + EPS:
                cands.append(round(x, 3))
            x += STEP_SECONDS
    if pieces != 2:  # only two-piece splits are needed by the callers; keep the API honest
        raise ValueError("split_points supports pieces=2")

    def ok(x0: float, x1: float) -> bool:
        if x1 - x0 < min_s - EPS:
            return False
        return not speaking or speech_in(words, x0, x1) >= SPEECH_OVERLAP_SECONDS or x1 - x0 >= reaction_s - EPS

    centre = (a + b) / 2.0
    good = [x for x in cands if ok(a, x) and ok(x, b)]
    if not good:
        return None
    return [min(good, key=lambda x: (abs(x - centre), x))]


# --------------------------------------------------------------------------------- recut plan sanitizer
def _seg_len(seg: dict[str, Any]) -> float:
    return float(seg["video"][2]) - float(seg["video"][1])


def _same_shot(s0: dict[str, Any], s1: dict[str, Any]) -> bool:
    """No visible cut between two consecutive segments (same picture source, contiguous frames, same reframe)."""
    return (str(s0["video"][0]) == str(s1["video"][0]) and abs(float(s0["video"][2]) - float(s1["video"][1])) < 0.003
            and s0.get("reframe") == s1.get("reframe"))


def _audio_continuous(s0: dict[str, Any], s1: dict[str, Any]) -> bool:
    return str(s0["audio"][0]) == str(s1["audio"][0]) and abs(float(s0["audio"][2]) - float(s1["audio"][1])) < 0.003


def visible_shots(segs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """[{first, last, start, end, video_unit}] (output seconds of the derived clip) -- runs of segments with no
    visible cut between them."""
    shots: list[dict[str, Any]] = []
    t = 0.0
    for i, seg in enumerate(segs):
        length = _seg_len(seg)
        if shots and _same_shot(segs[i - 1], seg):
            shots[-1].update(last=i, end=round(t + length, 3))
        else:
            shots.append({"first": i, "last": i, "start": round(t, 3), "end": round(t + length, 3),
                          "video_unit": str(seg["video"][0])})
        t += length
    return shots


def _r(seg: dict[str, Any]) -> dict[str, Any]:
    out = dict(seg)
    out["video"] = [seg["video"][0], round(float(seg["video"][1]), 3), round(float(seg["video"][2]), 3)]
    out["audio"] = [seg["audio"][0], round(float(seg["audio"][1]), 3), round(float(seg["audio"][2]), 3)]
    return out


def _cover(segs: list[dict[str, Any]], target: int, donor: int, clip_seconds: dict[str, float]) -> bool:
    """Picture-only merge: segment ``target`` shows the continuation of its neighbour ``donor``'s picture (the
    frames right after / before it), so the visible cut between them disappears.  The sound is untouched.  False
    when the donor's source has no room."""
    seg, nb = segs[target], segs[donor]
    length = _seg_len(seg)
    unit = str(nb["video"][0])
    total = clip_seconds.get(unit)
    if donor < target:
        start = float(nb["video"][2])
        if total is None or start + length > float(total) + 0.002:
            return False
        segs[target] = _r({**{k: v for k, v in seg.items() if k != "reframe"},
                           **({"reframe": nb["reframe"]} if nb.get("reframe") is not None else {}),
                           "video": [unit, start, start + length]})
    else:
        end = float(nb["video"][1])
        if end - length < -0.002:
            return False
        segs[target] = _r({**{k: v for k, v in seg.items() if k != "reframe"},
                           **({"reframe": nb["reframe"]} if nb.get("reframe") is not None else {}),
                           "video": [unit, max(0.0, end - length), end]})
    return True


def _shift_join(segs: list[dict[str, Any]], i: int, d: float, clip_seconds: dict[str, float]) -> bool:
    """Move the join between segments i and i+1 by ``d`` seconds (both picture and sound, which are continuous across
    it): segment i grows / shrinks at its end, segment i+1 at its start.  False when a source has no room."""
    s0, s1 = segs[i], segs[i + 1]
    v0 = float(s0["video"][2]) + d
    v1 = float(s1["video"][1]) + d
    a0 = float(s0["audio"][2]) + d
    if v0 <= float(s0["video"][1]) + EPS or v1 >= float(s1["video"][2]) - EPS or v1 < -0.002:
        return False
    total = clip_seconds.get(str(s0["video"][0]))
    if total is None or v0 > float(total) + 0.002:
        return False
    segs[i] = _r({**s0, "video": [s0["video"][0], s0["video"][1], v0], "audio": [s0["audio"][0], s0["audio"][1], a0]})
    segs[i + 1] = _r({**s1, "video": [s1["video"][0], v1, s1["video"][2]],
                      "audio": [s1["audio"][0], a0, s1["audio"][2]]})
    return True


def sanitize_recut(uid: str, segments: list[dict[str, Any]], *, words_by_unit: dict[str, list[dict[str, Any]]],
                   clip_seconds: dict[str, float], speaking_units: set[str] | None = None,
                   min_s: float | None = None, reaction_s: float | None = None) -> dict[str, Any]:
    """A unit re-cut plan's segments with the invariants enforced; the sound of the derived clip never changes
    except where an authored SOUND cut itself lands inside a word (then that segment is extended to the word's
    safe end when its sources have room).

    * a visible cut inside speech (sound continuous across it) moves to the nearest line boundary (<= 1 s) when
      both sides keep >= min_s; otherwise the picture of the shorter side continues the other side's (merge);
    * a visible shot shorter than ``min_s``, or a shot of a SPEAKING unit's picture that carries none of that
      unit's own speech and is shorter than ``reaction_s``, is merged into a neighbour the same way.

    Returns {segments, actions, problems}; ``problems`` lists what could not be fixed (recorded, never a stop)."""
    min_s = min_shot_seconds() if min_s is None else float(min_s)
    reaction_s = reaction_min_seconds() if reaction_s is None else float(reaction_s)
    speaking_units = set(speaking_units or ())
    segs = [_r(s) for s in segments]
    actions: list[dict[str, Any]] = []
    problems: list[dict[str, Any]] = []

    def words(unit: str) -> list[dict[str, Any]]:
        return words_by_unit.get(str(unit)) or []

    # 1. authored SOUND cuts (a dropped middle) must not clip a word: extend the outgoing / incoming segment
    for i in range(len(segs) - 1):
        s0, s1 = segs[i], segs[i + 1]
        if _audio_continuous(s0, s1):
            continue
        out_t = float(s0["audio"][2])
        bad = cut_violation(out_t, words(s0["audio"][0]))
        if bad and bad["need_at_or_after"] > out_t:
            d = bad["need_at_or_after"] - out_t
            vt, at = clip_seconds.get(str(s0["video"][0])), clip_seconds.get(str(s0["audio"][0]))
            if (vt is not None and at is not None and float(s0["video"][2]) + d <= vt + 0.002
                    and out_t + d <= at + 0.002 and d <= SNAP_MAX_SECONDS):
                segs[i] = _r({**s0, "video": [s0["video"][0], s0["video"][1], float(s0["video"][2]) + d],
                              "audio": [s0["audio"][0], s0["audio"][1], out_t + d]})
                actions.append({"action": "EXTEND_SOUND_CUT_TO_WORD_END", "segment": i, "seconds": round(d, 3)})
            else:
                problems.append({"problem": "SOUND_CUT_INSIDE_SPEECH_NO_ROOM", "segment": i, **bad})
        in_t = float(segs[i + 1]["audio"][1])
        bad = cut_violation(in_t, words(s1["audio"][0]))
        if bad and bad["or_at_or_before"] < in_t:
            d = in_t - max(0.0, bad["or_at_or_before"])
            if float(s1["video"][1]) - d >= -0.002 and d <= SNAP_MAX_SECONDS:
                s1 = segs[i + 1]
                segs[i + 1] = _r({**s1, "video": [s1["video"][0], max(0.0, float(s1["video"][1]) - d), s1["video"][2]],
                                  "audio": [s1["audio"][0], max(0.0, in_t - d), s1["audio"][2]]})
                actions.append({"action": "START_SOUND_CUT_BEFORE_WORD", "segment": i + 1, "seconds": round(d, 3)})
            else:
                problems.append({"problem": "SOUND_CUT_STARTS_MID_WORD_NO_ROOM", "segment": i + 1, **bad})

    # 2. visible cuts inside continuous speech -> nearest line boundary, else merge the shorter side away
    for i in range(len(segs) - 1):
        s0, s1 = segs[i], segs[i + 1]
        if _same_shot(s0, s1) or not _audio_continuous(s0, s1):
            continue
        unit = str(s0["audio"][0])
        t = float(s0["audio"][2])
        if cut_violation(t, words(unit)) is None:
            continue
        lo = float(s0["audio"][1]) + min_s
        hi = float(s1["audio"][2]) - min_s
        target = snap(t, words(unit), lo, hi) if hi > lo else None
        if target is not None and _shift_join(segs, i, target - t, clip_seconds):
            actions.append({"action": "MOVE_CUT_TO_LINE_BOUNDARY", "segment": i, "from": round(t, 3),
                            "to": round(target, 3)})
            continue
        short, donor = (i, i + 1) if _seg_len(s0) <= _seg_len(s1) else (i + 1, i)
        if _cover(segs, short, donor, clip_seconds) or _cover(segs, donor, short, clip_seconds):
            actions.append({"action": "MERGE_CUT_INSIDE_SPEECH", "segment": i, "at": round(t, 3)})
        else:
            problems.append({"problem": "CUT_INSIDE_SPEECH_UNFIXABLE", "segment": i, "at": round(t, 3)})

    # 3. fragments and silent-speaker fragments -> merge into a neighbour (picture only)
    for _ in range(len(segs) + 1):
        shots = visible_shots(segs)
        if len(shots) <= 1:
            break
        changed = False
        for k, shot in enumerate(shots):
            length = shot["end"] - shot["start"]
            seg_ids = range(shot["first"], shot["last"] + 1)
            own = [segs[j] for j in seg_ids if str(segs[j]["audio"][0]) == shot["video_unit"]]
            own_speech = sum(speech_in(words(shot["video_unit"]), float(s["audio"][1]), float(s["audio"][2]))
                             for s in own)
            silent_speaker = (shot["video_unit"] in speaking_units and own_speech < SPEECH_OVERLAP_SECONDS
                              and length < reaction_s - EPS)
            if length >= min_s - EPS and not silent_speaker:
                continue
            reason = "FRAGMENT" if length < min_s - EPS else "SPEAKER_NOT_SPEAKING"
            order = [k - 1, k + 1] if k > 0 else [k + 1]
            if k + 1 >= len(shots):
                order = [k - 1]
            for nb in sorted(order, key=lambda n: -(shots[n]["end"] - shots[n]["start"])):
                donor = shots[nb]["last"] if nb < k else shots[nb]["first"]
                saved = list(segs)
                ok = True
                ids = list(seg_ids) if nb < k else list(reversed(list(seg_ids)))
                for j in ids:
                    if not _cover(segs, j, j - 1 if nb < k else j + 1, clip_seconds):
                        ok = False
                        break
                if ok:
                    actions.append({"action": "MERGE_" + reason, "shot_start": shot["start"],
                                    "seconds": round(length, 3), "into_picture_of": str(segs[donor]["video"][0])})
                    changed = True
                    break
                segs[:] = saved
            if changed:
                break
            problems.append({"problem": reason + "_NOT_MERGEABLE", "shot_start": shot["start"],
                             "seconds": round(length, 3)})
        if not changed:
            break
    # dedupe problems (the fragment loop may record the same shot once per pass)
    seen, uniq = set(), []
    for p in problems:
        key = tuple(sorted((k, str(v)) for k, v in p.items()))
        if key not in seen:
            seen.add(key)
            uniq.append(p)
    return {"unit_id": uid, "segments": segs, "actions": actions, "problems": uniq,
            "changed": segs != [_r(s) for s in segments]}


# ------------------------------------------------------------------------------- post-S7 measurement
def measure_cut(*, shots: list[dict[str, Any]], lines: list[dict[str, Any]],
                unit_windows: list[dict[str, Any]] | None = None, speaking_units: set[str] | None = None,
                s7_cuts: list[float] | None = None, min_s: float | None = None,
                reaction_s: float | None = None, exclude: list[tuple[float, float]] | None = None) -> dict[str, Any]:
    """Free measurement of the delivered cut.

    ``shots``: measured shot windows [{start_seconds, end_seconds}] (scene cuts of the decoded final MP4).
    ``lines``: final-cut ASR line windows [{start, end, unit_id?, presence?}] (V.O. rows are ignored).
    ``unit_windows``: the release timeline segments [{unit_id, output_start, output_end}] -- which unit a shot shows.
    ``s7_cuts``: output seconds of the cuts S7 made (unit boundaries + re-cut internal cuts): a flag at one of them is
    S7's own (``s7_cut`` True, fixable by a free re-edit); others are cuts inside the video model's own take.
    ``exclude``: windows (title card, end card) left out of the shot statistics.

    Returns {fragments, speaker_not_speaking, tail_gaps, mid_line_cuts, counts, pacing}."""
    min_s = min_shot_seconds() if min_s is None else float(min_s)
    reaction_s = reaction_min_seconds() if reaction_s is None else float(reaction_s)
    speaking_units = set(speaking_units or ())
    s7 = sorted(float(c) for c in s7_cuts or [])
    exclude = list(exclude or [])
    windows = [(float(r["start"]), float(r["end"]), r.get("unit_id")) for r in lines or []
               if isinstance(r, dict) and str(r.get("presence") or "") != "VOICE_OVER"
               and _num(r.get("start")) is not None and _num(r.get("end")) is not None
               and float(r["end"]) > float(r["start"])]
    rows = []
    for s in shots or []:
        a, b = _num(s.get("start_seconds")), _num(s.get("end_seconds"))
        if a is None or b is None or b <= a:
            continue
        if any(x0 - 0.05 <= a and b <= x1 + 0.05 for x0, x1 in exclude):
            continue
        rows.append((a, b))
    cuts = sorted({round(b, 3) for _a, b in rows[:-1]})

    def at_s7(t: float) -> bool:
        return any(abs(t - c) <= 0.12 for c in s7)

    def unit_at(t0: float, t1: float) -> str | None:
        best, overlap = None, 0.0
        for w in unit_windows or []:
            a, b = _num(w.get("output_start")), _num(w.get("output_end"))
            if a is None or b is None:
                continue
            ov = min(b, t1) - max(a, t0)
            if ov > overlap:
                best, overlap = str(w.get("unit_id") or ""), ov
        return best

    fragments, silent = [], []
    for a, b in rows:
        length = b - a
        speech = sum(max(0.0, min(b, w1) - max(a, w0)) for w0, w1, _u in windows)
        unit = unit_at(a, b)
        made_by_s7 = at_s7(a) or at_s7(b)
        row = {"start": round(a, 3), "end": round(b, 3), "seconds": round(length, 3), "speech_seconds": round(speech, 3),
               **({"unit_id": unit} if unit else {}), "s7_cut": made_by_s7}
        if length < min_s - EPS:
            fragments.append(row)
        if unit and unit in speaking_units and speech < SPEECH_OVERLAP_SECONDS and length < reaction_s - EPS:
            silent.append(row)
    tails, mids = [], []
    for w0, w1, unit in windows:
        nxt = next((c for c in cuts if c >= w1 - 0.02), None)
        if nxt is not None and nxt - w1 < TAIL_GAP_FLAG_SECONDS:
            tails.append({"line_start": round(w0, 3), "line_end": round(w1, 3), "next_cut": nxt,
                          "gap_seconds": round(nxt - w1, 3), **({"unit_id": unit} if unit else {}),
                          "s7_cut": at_s7(nxt)})
        for c in cuts:
            if w0 + max(0.12, JCUT_HEAD_TOLERANCE_SECONDS) < c < w1 - 0.12:
                mids.append({"at": c, "line_start": round(w0, 3), "line_end": round(w1, 3),
                             **({"unit_id": unit} if unit else {}), "s7_cut": at_s7(c)})
    lengths = [b - a for a, b in rows]
    pacing = {}
    if lengths:
        pacing = {"shot_count": len(lengths), "mean_shot_seconds": round(sum(lengths) / len(lengths), 3),
                  "median_shot_seconds": round(median(lengths) or 0.0, 3),
                  "median_floor_seconds": median_floor_seconds(),
                  "below_median_floor": (median(lengths) or 0.0) < median_floor_seconds() - EPS}
    counts = {"fragments": len(fragments), "speaker_not_speaking": len(silent), "tail_gaps": len(tails),
              "mid_line_cuts": len(mids),
              "s7_attributable": sum(1 for r in fragments + silent + tails + mids if r.get("s7_cut"))}
    return {"schema": SCHEMA, "source": "measured shot windows + final-cut ASR + release timeline (free)",
            "thresholds": {"min_shot_seconds": min_s, "reaction_min_seconds": reaction_s,
                           "tail_gap_seconds": TAIL_GAP_FLAG_SECONDS},
            "fragments": fragments[:40], "speaker_not_speaking": silent[:40], "tail_gaps": tails[:40],
            "mid_line_cuts": mids[:40], "counts": counts, "pacing": pacing}
