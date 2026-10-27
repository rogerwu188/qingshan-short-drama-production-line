#!/usr/bin/env python3
"""Dialogue head trim (CAMERA_GRAMMAR_V1 episodes only; line owner 2026-10-26, lab Holmes E05).

MiniMax-H3 sometimes speaks a few invented words before a unit's scripted line ("Ha!", "That.",
"Closh key").  At assembly each unit whose FIRST shot carries an on-screen line is cut at its head to
``HEAD_LEAD_SECONDS`` before the first scripted word, so the extra speech never reaches the viewer.
Picture and sound are cut together (the AgentCut build moves both clips' source in-point, like the
tail trim moves their out-point), so the release timeline stays in sync.

The line start comes from the per-unit ASR word timestamps (faster-whisper ``word_timestamps``, the
same local S7 pass): the first ASR word position whose next words fuzzy-match the line's first words
and from which the whole line matches with good confidence.  When the line already starts at the first
heard word nothing is cut (internal repeats such as "It was, it was clamped" are never touched: the cut
is only ever before the first matching occurrence, and leading words that repeat the line's own first
words are a false start of the line, not extra speech).  The cut is never inside the line, never leaves a
unit shorter than ``MIN_UNIT_SECONDS`` and never runs into a later shot; when the line start cannot be
matched confidently the unit stays untrimmed and the reason is recorded.

Pure functions only: the S7 caller supplies the contract, grouping plan, unit ASR (with words), clip
durations and the tail-trim report, passes the plan to the AgentCut build (``--dialogue-head-trim``)
and shifts the unit ASR (``shift_unit_asr``) so captions, V.O., BGM and the release timeline follow.
"""

from __future__ import annotations

import difflib
import re
from typing import Any

SCHEMA = "nalu.dialogue_head_trim.v1"
HEAD_LEAD_SECONDS = 0.15
MIN_UNIT_SECONDS = 1.5
MIN_TRIM_SECONDS = 0.05
START_WORDS = 3
WORD_MATCH = 0.75
START_MATCH = 0.75
LINE_MATCH = 0.6
VOICE_ONLY_MODE = "VOICE_ONLY_NO_PLATE"


def _norm(word: str) -> str:
    return re.sub(r"[^0-9a-z一-鿿]+", "", str(word).lower().replace("'", "").replace("’", ""))


def _line_tokens(text: str) -> list[str]:
    """Scripted line -> tokens (en words; zh characters).  A leading ``Speaker：`` is not part of the line."""
    body = re.split(r"[：:]", str(text), maxsplit=1)[-1] if re.match(r"^[^：:]{1,24}[：:]", str(text)) else str(text)
    if re.search(r"[一-鿿]", body) and not re.search(r"[A-Za-z]", body):
        return [ch for ch in body if "一" <= ch <= "鿿"]
    return [w for w in (_norm(w) for w in re.split(r"\s+|[-—–]", body)) if w]


def asr_words(segments: list[dict[str, Any]], cjk_mode: bool = False) -> list[dict[str, Any]]:
    """Flatten per-segment ASR words to [{start, end, word, norm}] (zh words split to characters)."""
    out: list[dict[str, Any]] = []
    for seg in segments or []:
        for word in seg.get("words") or []:
            if word.get("start") is None or word.get("end") is None:
                continue
            text = str(word.get("word") or "").strip()
            if cjk_mode:
                chars = [ch for ch in text if "一" <= ch <= "鿿"]
                for ch in chars:
                    out.append({"start": float(word["start"]), "end": float(word["end"]), "word": ch, "norm": ch})
                continue
            norm = _norm(text)
            if norm:
                out.append({"start": float(word["start"]), "end": float(word["end"]), "word": text, "norm": norm})
    return out


def _ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def line_start(want: list[str], heard: list[dict[str, Any]]) -> tuple[int | None, float, float]:
    """(index of the first heard word that starts the scripted line, start score, whole-line score)."""
    if not want or not heard:
        return None, 0.0, 0.0
    k = min(START_WORDS, len(want))
    head = "".join(want[:k])
    whole = "".join(want)
    best = (None, 0.0, 0.0)
    for i, word in enumerate(heard):
        if _ratio(want[0], word["norm"]) < WORD_MATCH:
            continue
        start = _ratio(head, "".join(w["norm"] for w in heard[i:i + k]))
        line = _ratio(whole, "".join(w["norm"] for w in heard[i:i + len(want) + 1]))
        if start >= START_MATCH and line >= LINE_MATCH:
            return i, start, line
        if start > best[1]:
            best = (None, start, line)
    return best


def plan(contract: dict[str, Any], grouping: dict[str, Any], unit_asr: dict[str, Any],
         clip_seconds: dict[str, float], tail_report: dict[str, Any] | None = None) -> dict[str, Any]:
    """Per-unit head-trim plan: rows of {unit_id, head_cut_seconds, trimmed, removed_text, reason, ...}."""
    language = str(contract.get("dialogue_language") or "zh").lower()
    shots = {str(s.get("shot_id")): s for s in contract.get("shots") or []}
    voice_only = {str(e.get("character_id")) for e in contract.get("character_entities") or []
                  if str((e.get("identity_source") or {}).get("mode") or "") == VOICE_ONLY_MODE}
    lines_by_shot: dict[str, list[dict[str, Any]]] = {}
    for row in (contract.get("audio_contract") or {}).get("dialogue_units") or []:
        lines_by_shot.setdefault(str(row.get("shot_id") or ""), []).append(row)
    tail_end = {str(r["unit_id"]): float(r["kept_seconds"]) for r in (tail_report or {}).get("units") or []
                if r.get("trimmed") and r.get("kept_seconds") is not None}
    rows: list[dict[str, Any]] = []
    for unit in grouping.get("units") or []:
        uid = str(unit.get("unit_id"))
        shot_ids = [str(s) for s in unit.get("editorial_shot_ids") or []]
        original = clip_seconds.get(uid)
        row: dict[str, Any] = {"unit_id": uid, "original_seconds": original, "head_cut_seconds": 0.0,
                               "trimmed": False}
        rows.append(row)
        if not original or original <= 0:
            row["reason"] = "CLIP_DURATION_UNKNOWN"
            continue
        first_lines = lines_by_shot.get(shot_ids[0], []) if shot_ids else []
        if not first_lines:
            row["reason"] = "NO_DIALOGUE_IN_FIRST_SHOT"
            continue
        if any(str(line.get("speaker_id") or "") in voice_only for line in first_lines):
            row["reason"] = "FIRST_SHOT_HAS_VOICE_OVER"
            continue
        expected = str(first_lines[0].get("text") or "")
        row["expected_text"] = expected
        cjk_mode = language.startswith("zh") or (bool(re.search(r"[一-鿿]", expected))
                                                 and not re.search(r"[A-Za-z]", expected))
        want = _line_tokens(expected)
        heard = asr_words(unit_asr.get(uid) or [], cjk_mode)
        if not heard:
            row["reason"] = "NO_ASR_WORDS"
            continue
        index, start_score, line_score = line_start(want, heard)
        row.update({"start_match_score": round(start_score, 3), "line_match_score": round(line_score, 3),
                    "heard_text": " ".join(w["word"] for w in heard)})
        if index is None:
            row["reason"] = "LINE_START_NOT_MATCHED"
            continue
        first = heard[index]
        row["line_start_seconds"] = round(first["start"], 3)
        if index == 0:
            row["reason"] = "NO_EXTRA_SPEECH_BEFORE_LINE"
            continue
        before = [w["norm"] for w in heard[:index]]
        if _ratio("".join(before), "".join(want[:len(before)])) >= WORD_MATCH:
            # a false start repeating the line's own first words ("It was, it was clamped") is the line
            row["reason"] = "LEADING_WORDS_REPEAT_LINE_START"
            continue
        cut = min(first["start"], max(heard[index - 1]["end"], first["start"] - HEAD_LEAD_SECONDS))
        row["removed_text"] = " ".join(w["word"] for w in heard[:index])
        end = tail_end.get(uid, float(original))
        planned = [float((shots.get(sid) or {}).get("target_seconds") or 0.0) for sid in shot_ids]
        first_shot_end = planned[0] * float(original) / sum(planned) if sum(planned) > 0 and len(planned) > 1 \
            else float(original)
        if cut < MIN_TRIM_SECONDS:
            row["reason"] = "EXTRA_SPEECH_TOO_SHORT_TO_CUT"
            continue
        if end - cut < MIN_UNIT_SECONDS:
            row["reason"] = "MIN_UNIT_LENGTH"
            continue
        if cut >= first_shot_end:
            row["reason"] = "CUT_BEYOND_FIRST_SHOT"
            continue
        row.update({"head_cut_seconds": round(cut, 3), "trimmed": True, "kept_seconds": round(end - cut, 3),
                    "reason": "TRIMMED_BEFORE_LINE_START"})
    trimmed = [r for r in rows if r["trimmed"]]
    return {"schema": SCHEMA, "episode": contract.get("episode"), "head_lead_seconds": HEAD_LEAD_SECONDS,
            "min_unit_seconds": MIN_UNIT_SECONDS, "trimmed_units": len(trimmed),
            "removed_seconds": round(sum(r["head_cut_seconds"] for r in trimmed), 3), "units": rows}


def shift_unit_asr(unit_asr: dict[str, Any], report: dict[str, Any] | None) -> dict[str, Any]:
    """Head-trimmed units: drop the words/segments before the cut, rebuild a segment's text from its kept
    words, and shift times so they are relative to the new clip start; other units unchanged."""
    cuts = {str(r["unit_id"]): float(r["head_cut_seconds"]) for r in (report or {}).get("units") or []
            if r.get("trimmed")}
    out: dict[str, Any] = {}
    for uid, segs in unit_asr.items():
        cut = cuts.get(uid)
        if not cut:
            out[uid] = segs
            continue
        kept = []
        for seg in segs:
            if float(seg.get("end") or 0.0) <= cut:
                continue
            row = dict(seg)
            words = [w for w in seg.get("words") or [] if w.get("start") is not None and float(w["start"]) >= cut]
            if seg.get("words") and float(seg.get("start") or 0.0) < cut:
                if not words:
                    continue
                row["text"] = "".join(str(w.get("word") or "") for w in words).strip()
            if "words" in seg:
                row["words"] = [dict(w, start=round(float(w["start"]) - cut, 3), end=round(float(w["end"]) - cut, 3))
                                for w in words]
            row["start"] = round(max(0.0, float(seg.get("start") or 0.0) - cut), 3)
            row["end"] = round(float(seg["end"]) - cut, 3)
            kept.append(row)
        out[uid] = kept
    return out


def strip_words(unit_asr: dict[str, Any]) -> dict[str, Any]:
    """The segment-only ASR shape every later S7 consumer was built for."""
    return {uid: [{k: v for k, v in seg.items() if k != "words"} for seg in segs] for uid, segs in unit_asr.items()}
