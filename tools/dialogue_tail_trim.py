#!/usr/bin/env python3
"""Dialogue tail trim (CAMERA_GRAMMAR_V1 episodes only; line owner 2026-10-23).

MiniMax-H3 fills the part of a dialogue unit's slot that outlasts its line with invented,
garbled speech.  At assembly each unit whose LAST shot carries on-screen dialogue is cut
``TAIL_SECONDS`` after the end of that line, so the leftover babble never reaches the viewer.

The line end is the end time of the last per-unit ASR segment that contains the end of the
expected line (fuzzy match on its last words / CJK characters); the tail stops early where the
next ASR segment (the babble) starts.  A unit is never cut below
``MIN_UNIT_SECONDS``, never inside a non-final shot, never lengthened; when the line end
cannot be matched confidently the unit stays untrimmed and the reason is recorded.

The line's last word must not be cut (lab E02 VU-007: ASR split "...of a terrified" | "woman.", the
fuzzy tail match accepted the first segment and the cap at the next segment start cut "woman"):
when the matched segment does not contain the line's last word (en; last CJK character for zh)
but one of the next ASR segments does, the line ends at that segment instead; when no segment
contains it and the word is not a proper name (ASR misspells names: E01 "Farintosh"), the unit
stays untrimmed (LINE_LAST_WORD_NOT_HEARD).  With measured audio energy (``unit_energy``: per-unit
RMS dBFS frames of ``ENERGY_HOP`` s) a cut that is not at a following ASR segment start is also
checked: speech-level energy in the ``ENERGY_GUARD_SECONDS`` after it moves the cut to where the
energy falls (at most ``ENERGY_EXTEND_MAX`` later), else the unit stays untrimmed.

Pure functions only: the S7 caller supplies the contract, grouping plan, unit ASR and the
measured clip durations, passes the plan to the AgentCut build (``--dialogue-tail-trim``) and
drops the ASR segments that the cut removed, so captions, V.O. placement, BGM and the
release timeline all follow the trimmed timeline.
"""

from __future__ import annotations

import difflib
import re
from typing import Any

SCHEMA = "nalu.dialogue_tail_trim.v1"
TAIL_SECONDS = 0.5
MIN_UNIT_SECONDS = 1.5
MIN_TRIM_SECONDS = 0.05
MATCH_THRESHOLD = 0.55
EN_TAIL_WORDS = 3
ZH_TAIL_CHARS = 4
VOICE_ONLY_MODE = "VOICE_ONLY_NO_PLATE"
WORD_MATCH = 0.75
LAST_WORD_LOOKAHEAD = 2
ENERGY_HOP = 0.02
ENERGY_GUARD_SECONDS = 0.3
ENERGY_EXTEND_MAX = 1.0
ENERGY_BELOW_SPEECH_DB = 15.0
ENERGY_FLOOR_DB = -45.0


def _cjk(text: str) -> str:
    return "".join(ch for ch in str(text) if "一" <= ch <= "鿿")


def _words(text: str) -> list[str]:
    return [w for w in re.split(r"[^0-9a-z]+", str(text).lower().replace("'", "").replace("’", "")) if w]


def _tokens(text: str, cjk_mode: bool) -> list[str]:
    return list(_cjk(text)) if cjk_mode else _words(text)


def tail_match_score(expected: str, segment_text: str, *, cjk_mode: bool) -> float:
    """Best similarity between the expected line's last words/chars and any window of the segment."""
    k_max = ZH_TAIL_CHARS if cjk_mode else EN_TAIL_WORDS
    want = _tokens(expected, cjk_mode)
    have = _tokens(segment_text, cjk_mode)
    if not want or not have:
        return 0.0
    k = min(k_max, len(want))
    target = "".join(want[-k:])
    best = 0.0
    for size in {max(1, k - 1), k, k + 1}:
        for i in range(0, max(1, len(have) - size + 1)):
            window = "".join(have[i:i + size])
            best = max(best, difflib.SequenceMatcher(None, target, window).ratio())
    return best


def has_last_word(expected: str, segment_text: str, *, cjk_mode: bool) -> bool:
    """True when the segment contains the expected line's last word (en, fuzzy) / last CJK character."""
    want = _tokens(expected, cjk_mode)
    have = _tokens(segment_text, cjk_mode)
    if not want or not have:
        return False
    if cjk_mode:
        return want[-1] in have
    return any(difflib.SequenceMatcher(None, want[-1], w).ratio() >= WORD_MATCH for w in have)


def _last_word_is_name(expected: str) -> bool:
    words = re.findall(r"[A-Za-z][A-Za-z'’-]*", str(expected))
    return bool(words) and words[-1][:1].isupper() and len(words) > 1


def speech_after(frames: list[float] | None, cut: float, line_end: float) -> tuple[bool, float | None]:
    """(speech-level energy right after ``cut``?, time the energy falls below the threshold or None).

    Threshold: the line's own speech level (75th percentile of the frames before ``line_end``) minus
    ``ENERGY_BELOW_SPEECH_DB``, never below ``ENERGY_FLOOR_DB``.  Speech = 3+ frames (60 ms) above it
    in the guard window.
    """
    if not frames:
        return False, None
    spoken = sorted(frames[:max(1, int(line_end / ENERGY_HOP))])
    level = spoken[int(0.75 * (len(spoken) - 1))]
    threshold = max(ENERGY_FLOOR_DB, level - ENERGY_BELOW_SPEECH_DB)
    i0 = int(round(cut / ENERGY_HOP))
    guard = frames[i0:i0 + int(round(ENERGY_GUARD_SECONDS / ENERGY_HOP))]
    if sum(1 for v in guard if v > threshold) < 3:
        return False, None
    quiet_run = int(round(0.1 / ENERGY_HOP))
    for i in range(i0, min(len(frames), i0 + int(round(ENERGY_EXTEND_MAX / ENERGY_HOP)))):
        if all(v <= threshold for v in frames[i:i + quiet_run]) and len(frames[i:i + quiet_run]) == quiet_run:
            return True, round(i * ENERGY_HOP, 3)
    return True, None


def plan(contract: dict[str, Any], grouping: dict[str, Any], unit_asr: dict[str, Any],
         clip_seconds: dict[str, float], unit_energy: dict[str, list[float]] | None = None) -> dict[str, Any]:
    """Per-unit trim plan: rows of {unit_id, original_seconds, kept_seconds, trimmed, matched_text, reason}."""
    language = str(contract.get("dialogue_language") or "zh").lower()
    shots = {str(s.get("shot_id")): s for s in contract.get("shots") or []}
    voice_only = {str(e.get("character_id")) for e in contract.get("character_entities") or []
                  if str((e.get("identity_source") or {}).get("mode") or "") == VOICE_ONLY_MODE}
    lines_by_shot: dict[str, list[dict[str, Any]]] = {}
    for row in (contract.get("audio_contract") or {}).get("dialogue_units") or []:
        lines_by_shot.setdefault(str(row.get("shot_id") or ""), []).append(row)
    rows: list[dict[str, Any]] = []
    for unit in grouping.get("units") or []:
        uid = str(unit.get("unit_id"))
        shot_ids = [str(s) for s in unit.get("editorial_shot_ids") or []]
        original = clip_seconds.get(uid)
        row: dict[str, Any] = {"unit_id": uid, "original_seconds": original, "kept_seconds": original,
                               "trimmed": False, "matched_text": None, "line_end_seconds": None}
        rows.append(row)
        if not original or original <= 0:
            row["reason"] = "CLIP_DURATION_UNKNOWN"
            continue
        last_lines = lines_by_shot.get(shot_ids[-1], []) if shot_ids else []
        if not last_lines:
            row["reason"] = "NO_DIALOGUE_IN_LAST_SHOT"
            continue
        if any(str(line.get("speaker_id") or "") in voice_only for line in last_lines):
            row["reason"] = "LAST_SHOT_HAS_VOICE_OVER"
            continue
        expected = str(last_lines[-1].get("text") or "")
        row["expected_text"] = expected
        cjk_mode = language.startswith("zh") or (bool(_cjk(expected)) and not _words(expected))
        segs = [s for s in unit_asr.get(uid) or [] if s.get("end") is not None and str(s.get("text") or "").strip()]
        if not segs:
            row["reason"] = "NO_ASR_SEGMENTS"
            continue
        hit, hit_score = None, 0.0
        for seg in reversed(segs):
            score = tail_match_score(expected, str(seg.get("text") or ""), cjk_mode=cjk_mode)
            if score >= MATCH_THRESHOLD:
                hit, hit_score = seg, score
                break
            hit_score = max(hit_score, score)
        row["match_score"] = round(hit_score, 3)
        if hit is None:
            row["reason"] = "LINE_END_NOT_MATCHED"
            continue
        if not has_last_word(expected, str(hit.get("text") or ""), cjk_mode=cjk_mode):
            later_hit = next((s for s in segs[segs.index(hit) + 1:segs.index(hit) + 1 + LAST_WORD_LOOKAHEAD]
                              if has_last_word(expected, str(s.get("text") or ""), cjk_mode=cjk_mode)), None)
            if later_hit is not None:
                hit = later_hit
                row["line_end_extended_to_last_word"] = True
            elif not cjk_mode and not _last_word_is_name(expected):
                row["matched_text"] = str(hit.get("text") or "")
                row["reason"] = "LINE_LAST_WORD_NOT_HEARD"
                continue
        line_end = float(hit["end"])
        row["matched_text"] = str(hit.get("text") or "")
        row["line_end_seconds"] = round(line_end, 3)
        planned = [float((shots.get(sid) or {}).get("target_seconds") or 0.0) for sid in shot_ids]
        last_shot_start = sum(planned[:-1])
        if sum(planned) > 0:
            last_shot_start = max(last_shot_start, last_shot_start * original / sum(planned))
        # The 0.5 s tail never reaches into the next ASR segment: after the matched line it is the
        # babble itself (Holmes E01-VU-009: line ends 4.32, "all in lust..." starts 4.32).
        later = [float(s.get("start") or 0.0) for s in segs[segs.index(hit) + 1:]]
        tail_end = max(line_end, min([line_end + TAIL_SECONDS, *later]))
        row["tail_capped_by_next_speech"] = tail_end < line_end + TAIL_SECONDS
        kept = min(original, max(tail_end, MIN_UNIT_SECONDS, last_shot_start))
        frames = (unit_energy or {}).get(uid)
        capped_cut = bool(row["tail_capped_by_next_speech"]) and kept == tail_end  # cut at the babble onset
        if frames and original - kept >= MIN_TRIM_SECONDS and not capped_cut:
            loud, quiet_at = speech_after(frames, kept, line_end)
            row["energy_checked"] = True
            if loud:
                if quiet_at is None:
                    row["reason"] = "SPEECH_ENERGY_AT_CUT"
                    continue
                row["energy_extended_seconds"] = round(quiet_at - kept, 3)
                kept = tail_end = min(original, quiet_at)
        if original - kept < MIN_TRIM_SECONDS:
            row["reason"] = "LINE_FILLS_SLOT"
            continue
        row.update({"kept_seconds": round(kept, 3), "trimmed": True,
                    "trimmed_seconds": round(original - kept, 3),
                    "reason": ("TRIMMED_AT_LINE_END" if kept == tail_end else
                               "TRIMMED_AT_LAST_SHOT_START" if kept == last_shot_start else
                               "TRIMMED_AT_MIN_LENGTH")})
    trimmed = [r for r in rows if r["trimmed"]]
    return {"schema": SCHEMA, "episode": contract.get("episode"), "tail_seconds": TAIL_SECONDS,
            "min_unit_seconds": MIN_UNIT_SECONDS, "match_threshold": MATCH_THRESHOLD,
            "trimmed_units": len(trimmed),
            "removed_seconds": round(sum(r["trimmed_seconds"] for r in trimmed), 3),
            "units": rows}


def trim_unit_asr(unit_asr: dict[str, Any], report: dict[str, Any] | None) -> dict[str, Any]:
    """Drop the segments after the matched line (the babble, even the part inside the 0.5 s tail) and
    clamp ends to the cut; untrimmed units unchanged."""
    rows = {str(r["unit_id"]): r for r in (report or {}).get("units") or [] if r.get("trimmed")}
    out: dict[str, Any] = {}
    for uid, segs in unit_asr.items():
        row = rows.get(uid)
        if row is None:
            out[uid] = segs
            continue
        end, line_end = float(row["kept_seconds"]), float(row["line_end_seconds"])
        out[uid] = [dict(s, end=min(float(s["end"]), end)) for s in segs
                    if float(s.get("start") or 0.0) < min(end, line_end)]
    return out
