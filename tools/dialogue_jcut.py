#!/usr/bin/env python3
"""Dialogue J-cut between two speakers (S7, CAMERA_GRAMMAR_V1 performance cut; device 1101 E27 deep review 2026-11-25).

Why: every line ended 0.15-0.25 s before its cut, the next speaker started 0.15 s after it, and nothing sounded in
between but a faint bed -- the dialogue read like a queue of people reading aloud ("排队朗读").  Human-cut dialogue
lets the next speaker's voice come in a moment BEFORE the picture cuts to them.

What (lip sync kept: the next unit's audio and picture stay locked to the same source time):

* the picture cut stays where the performance cut put it -- on the frame after the previous line's tail guard;
* the next unit's in-point moves to ``line_start + overlap`` (``overlap`` = ``NALU_S7_JCUT_SECONDS``, default
  0.15 s, clamped 0.1-0.2 s), so its first ``overlap`` seconds of speech are not shown in its own picture...
* ...and are played instead UNDER the previous shot's tail: the renderer
  (``render_portable_timeline``, project ``metadata.audio_jcut``) starts the next unit's audio ``preroll`` =
  ``overlap + FADE_IN_SECONDS`` early, from the same source (``[in - preroll, in]``), fading in over
  ``FADE_IN_SECONDS`` in the pre-line silence, while the previous unit's audio plays on to the cut and fades out
  over ``FADE_OUT_SECONDS`` (20-40 ms, no dip, no click).  Timeline shrinks by ``lead + overlap`` per J-cut (the
  dead pre-line lead the head trim kept is gone).

Only between two SPEAKING units (performance-cut rows ``MATCHED``) whose speakers differ, and only when the
previous line has already ended: its sound end (the tail guard's energy-measured ``speech_end``, else the word end
+ the tail guard -- conservative) lies at least ``MIN_VOICE_GAP_SECONDS`` + the fade before the next voice enters,
so two voices' words never overlap and the last syllable is never cut (DIALOGUE_TAIL_GUARD unchanged: the picture
cut and the previous audio's end do not move).  Units carrying V.O. narration, re-cut units and units without a
line onset are skipped; so is a J-cut that would leave the next unit shorter than ``MIN_KEEP_SECONDS``.

Pure functions; ``plan`` returns the report rows and ``apply_to_performance_cut`` folds the in-point shift into
the performance-cut rows BEFORE they are merged into the head-trim report, so the build, captions, unit ASR,
speaker map and levelling all see the same in-point.  ``NALU_S7_JCUT=off`` disables it (the cut is then exactly
as before).  Never a gate: an unusable pair is recorded with its reason.
"""
from __future__ import annotations

import os
from typing import Any

SCHEMA = "nalu.dialogue_jcut.v1"
ENV_SWITCH = "NALU_S7_JCUT"
ENV_SECONDS = "NALU_S7_JCUT_SECONDS"
DEFAULT_OVERLAP_SECONDS = 0.15
MIN_OVERLAP_SECONDS = 0.10
MAX_OVERLAP_SECONDS = 0.20
#: silence kept between the previous voice's last sound and the incoming pre-roll (the fade starts after it)
MIN_VOICE_GAP_SECONDS = 0.04
FADE_IN_SECONDS = 0.03
FADE_OUT_SECONDS = 0.03
MIN_KEEP_SECONDS = 1.2
#: fallback when the tail guard measured no energy decay: assume the sound lasts this long past the word end
WORD_END_SOUND_SECONDS = 0.25
VOICE_ONLY_MODE = "VOICE_ONLY_NO_PLATE"


def enabled(environ: dict[str, str] | None = None) -> bool:
    raw = str((os.environ if environ is None else environ).get(ENV_SWITCH) or "").strip().lower()
    return raw not in ("0", "off", "false", "no")


def overlap_seconds(environ: dict[str, str] | None = None) -> float:
    """The target overlap (seconds of the next line under the previous picture), clamped to 0.1-0.2 s."""
    raw = str((os.environ if environ is None else environ).get(ENV_SECONDS) or "").strip()
    try:
        value = float(raw) if raw else DEFAULT_OVERLAP_SECONDS
    except ValueError:
        value = DEFAULT_OVERLAP_SECONDS
    if value != value:
        value = DEFAULT_OVERLAP_SECONDS
    return round(min(MAX_OVERLAP_SECONDS, max(MIN_OVERLAP_SECONDS, value)), 3)


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None


def unit_speakers(contract: dict[str, Any], grouping: dict[str, Any]) -> dict[str, dict[str, str]]:
    """unit -> {"first": speaker of its first on-screen line, "last": speaker of its last one} (V.O.-only speakers
    excluded).  A unit without an on-screen line is absent."""
    voice_only = {str(e.get("character_id")) for e in contract.get("character_entities") or []
                  if str((e.get("identity_source") or {}).get("mode") or "") == VOICE_ONLY_MODE}
    by_shot: dict[str, list[str]] = {}
    for row in (contract.get("audio_contract") or {}).get("dialogue_units") or []:
        speaker = str(row.get("speaker_id") or row.get("character_id") or "")
        if speaker and speaker not in voice_only:
            by_shot.setdefault(str(row.get("shot_id") or ""), []).append(speaker)
    out: dict[str, dict[str, str]] = {}
    for unit in grouping.get("units") or []:
        speakers = [sp for sid in unit.get("editorial_shot_ids") or [] for sp in by_shot.get(str(sid), [])]
        if speakers:
            out[str(unit.get("unit_id"))] = {"first": speakers[0], "last": speakers[-1]}
    return out


def _sound_end(row: dict[str, Any]) -> float | None:
    """Where the previous unit's last line stops sounding (source seconds), conservative."""
    guard = row.get("tail_guard") if isinstance(row.get("tail_guard"), dict) else {}
    word_end = _num(guard.get("word_end"))
    if word_end is None:
        word_end = _num(row.get("line_end_seconds"))
    if word_end is None:
        return None
    measured = _num(guard.get("speech_end"))
    if measured is not None and measured >= word_end:
        return measured
    return word_end + WORD_END_SOUND_SECONDS


def plan(perf: dict[str, Any], contract: dict[str, Any], grouping: dict[str, Any], *,
         order: list[str] | None = None, skip_units: set[str] | None = None,
         environ: dict[str, str] | None = None) -> dict[str, Any]:
    """J-cut rows for every adjacent pair of units (timeline ``order``, default: sorted unit ids, the build's order).

    Each row: from/to unit and speaker, the previous cut (``cut_out``) and sound end, the gap, the next unit's
    ``line_start`` / ``before_in`` / ``after_in``, ``overlap`` (s of the next line before the picture cut),
    ``preroll`` (s of next-unit audio played before the cut), ``shift`` (in-point move) and ``status``
    APPLIED | SKIPPED:<reason>."""
    env = os.environ if environ is None else environ
    rows_by_unit = {str(r.get("unit_id")): r for r in perf.get("units") or []}
    order = list(order) if order is not None else sorted(rows_by_unit)
    speakers = unit_speakers(contract, grouping)
    skip = set(skip_units or ())
    target = overlap_seconds(env)
    on = enabled(env)
    out_rows: list[dict[str, Any]] = []
    for prev_id, next_id in zip(order, order[1:]):
        prev, nxt = rows_by_unit.get(prev_id) or {}, rows_by_unit.get(next_id) or {}
        row: dict[str, Any] = {"from_unit_id": prev_id, "to_unit_id": next_id,
                               "from_speaker": (speakers.get(prev_id) or {}).get("last"),
                               "to_speaker": (speakers.get(next_id) or {}).get("first")}
        out_rows.append(row)

        def skipped(reason: str) -> None:
            row["status"] = f"SKIPPED:{reason}"

        if not on:
            skipped("DISABLED")
            continue
        if prev.get("kind") != "SPEAKING" or nxt.get("kind") != "SPEAKING":
            skipped("NOT_DIALOGUE_TO_DIALOGUE")
            continue
        if prev.get("status") != "MATCHED" or nxt.get("status") != "MATCHED":
            skipped("LINE_NOT_MATCHED")
            continue
        if prev_id in skip or next_id in skip:
            skipped("UNIT_EXCLUDED")
            continue
        if not row["from_speaker"] or not row["to_speaker"]:
            skipped("SPEAKER_UNKNOWN")
            continue
        if row["from_speaker"] == row["to_speaker"]:
            skipped("SAME_SPEAKER")
            continue
        cut_out, sound_end = _num(prev.get("after_out")), _sound_end(prev)
        next_in, line_start = _num(nxt.get("after_in")), _num(nxt.get("line_start_seconds"))
        next_out = _num(nxt.get("after_out"))
        if None in (cut_out, sound_end, next_in, line_start, next_out):
            skipped("TIMING_UNKNOWN")
            continue
        gap = cut_out - sound_end
        lead = line_start - next_in
        row.update(cut_out=round(cut_out, 3), sound_end=round(sound_end, 3), tail_gap=round(gap, 3),
                   before_in=round(next_in, 3), line_start=round(line_start, 3), lead=round(lead, 3))
        if lead < 0:
            skipped("NEXT_LINE_STARTS_BEFORE_IN_POINT")
            continue
        room = gap - MIN_VOICE_GAP_SECONDS - FADE_IN_SECONDS
        overlap = round(min(target, room), 3)
        if overlap < MIN_OVERLAP_SECONDS - 1e-9:
            row["room_seconds"] = round(room, 3)
            skipped("PREVIOUS_LINE_STILL_SOUNDING")
            continue
        preroll = round(overlap + min(FADE_IN_SECONDS, lead), 3)
        after_in = round(line_start + overlap, 3)
        if next_out - after_in < MIN_KEEP_SECONDS:
            skipped("NEXT_UNIT_TOO_SHORT")
            continue
        row.update(status="APPLIED", overlap=overlap, preroll=preroll, after_in=after_in,
                   shift=round(after_in - next_in, 3), fade_in=min(FADE_IN_SECONDS, preroll),
                   fade_out=FADE_OUT_SECONDS)
    applied = [r for r in out_rows if r.get("status") == "APPLIED"]
    return {"schema": SCHEMA, "episode": perf.get("episode"), "enabled": on,
            "rule": {"overlap_seconds": target, "overlap_range": [MIN_OVERLAP_SECONDS, MAX_OVERLAP_SECONDS],
                     "min_voice_gap_seconds": MIN_VOICE_GAP_SECONDS, "fade_in_seconds": FADE_IN_SECONDS,
                     "fade_out_seconds": FADE_OUT_SECONDS, "min_keep_seconds": MIN_KEEP_SECONDS,
                     "word_end_sound_seconds": WORD_END_SOUND_SECONDS,
                     "picture_cut": "unchanged (frame after the previous line's tail guard)",
                     "lip_sync": "next unit audio and picture share one source time; its in-point moves"},
            "applied": len(applied), "removed_seconds": round(sum(r["shift"] for r in applied), 3),
            "rows": out_rows}


def apply_to_performance_cut(perf: dict[str, Any], report: dict[str, Any]) -> list[str]:
    """Move each APPLIED J-cut's next-unit in-point in the performance-cut rows (adds reason ``JCUT_IN``); returns
    the unit ids changed.  Run BEFORE performance_cut.merge so the head-trim report carries the new in-point."""
    rows = {str(r.get("unit_id")): r for r in perf.get("units") or []}
    changed = []
    for jc in report.get("rows") or []:
        if jc.get("status") != "APPLIED":
            continue
        row = rows.get(str(jc["to_unit_id"]))
        if row is None:
            continue
        row["jcut"] = {k: jc[k] for k in ("from_unit_id", "before_in", "after_in", "overlap", "preroll", "shift")}
        row["after_in"] = jc["after_in"]
        if "JCUT_IN" not in row.setdefault("reasons", []):
            row["reasons"].append("JCUT_IN")
        row["changed"] = True
        orig = _num(row.get("after_out"))
        row["kept_seconds"] = round(orig - jc["after_in"], 3) if orig is not None else row.get("kept_seconds")
        changed.append(str(jc["to_unit_id"]))
    if changed:
        perf["changed_units"] = sum(1 for r in perf.get("units") or [] if r.get("changed"))
        perf["after_total_seconds"] = round(sum(float(r.get("after_out") or 0) - float(r.get("after_in") or 0)
                                                for r in perf.get("units") or []), 3)
        perf["removed_seconds"] = round(float(perf.get("before_total_seconds") or 0) - perf["after_total_seconds"], 3)
    return changed


def applied_rows(report: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """to_unit_id -> APPLIED row (the AgentCut build's view)."""
    return {str(r["to_unit_id"]): r for r in (report or {}).get("rows") or [] if r.get("status") == "APPLIED"}
