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


def plan(contract: dict[str, Any], grouping: dict[str, Any], unit_asr: dict[str, Any],
         clip_seconds: dict[str, float]) -> dict[str, Any]:
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
