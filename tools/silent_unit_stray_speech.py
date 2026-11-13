#!/usr/bin/env python3
"""Stray speech in a silent MiniMax-H3 unit: measured at S6, muted locally at S7 (free; no reroll, no gate).

A unit whose script carries no dialogue is generated with ``generate_audio: true`` (the native ambience, cloth and
foley are the unit's sound) and the prompt already says nobody speaks (``h3_provider_prompt_renderer.NO_VOICE_SILENT``
/ the V2 "Dialogue: none." block).  H3 still murmurs in some of those clips: lab 2026-10/11, 13 of ~150 silent units
across 夜无疆 / 化缘 / Holmes kept a real-speech ASR segment after the D-18b re-verification (no_speech_prob < 0.5,
avg_logprob > -1.0), e.g. 「我等无疆菜沙」 0.34-1.80 s, "This must be bad and some backs" 0.00-1.08 s.  The fleet
(2026-11-13, 10 devices) reported the same code ``dialogue:unexpected_native_(mandarin_)speech_present``.  Every lab
case was then admitted by a line-owner order, so the murmur shipped; the alternative was a paid reroll of the same
prompt, which the provider ignores.

Owner decision (cost first, fewer gates): the stray speech windows are muted on the rendered native cut at S7 with
short ramps, exactly like the leading vocal burst (``dialogue_leading_burst``); ambience outside the windows is kept.
S6 therefore records the finding instead of rejecting, as long as the murmur is a minority of the clip
(``MAX_SPEECH_FRACTION``).  A clip that is mostly speech keeps the existing reject: muting it would leave dead air.

Pure functions; the S6 runner calls :func:`assess`, the S7 caller supplies QA records, clip hashes and the AgentCut
project and runs the ffmpeg mix with :func:`mix_filter`.
"""

from __future__ import annotations

from typing import Any, Callable

SCHEMA = "nalu.silent_unit_stray_speech_mute.v1"
ADJUDICATION_TYPE = "SILENT_UNIT_STRAY_SPEECH_MUTED_AT_S7"
UNEXPECTED_SPEECH_CODES = ("unexpected_native_speech_present", "unexpected_native_mandarin_speech_present")
#: whisper segment bounds are coarse; the window is widened by this much on both sides
PAD_SECONDS = 0.08
#: windows closer than this are muted as one (no 0.1 s ambience blip between two murmured words)
MERGE_GAP_SECONDS = 0.25
#: above this share of the clip the unit is mostly talking: muting would leave dead air, so S6 keeps its reject
MAX_SPEECH_FRACTION = 0.6
FADE_OUT_SECONDS = 0.03
FADE_IN_SECONDS = 0.03


def merged_windows(segments: list[dict[str, Any]], duration: float | None = None, *,
                   pad: float = PAD_SECONDS, gap: float = MERGE_GAP_SECONDS) -> list[list[float]]:
    """Padded, merged ``[start, end]`` source-second windows of the given ASR segments (clamped to the clip)."""
    spans = []
    for seg in segments or []:
        try:
            a, b = float(seg["start"]), float(seg["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if b <= a:
            continue
        a, b = max(0.0, a - pad), b + pad
        if duration:
            b = min(float(duration), b)
        if b > a:
            spans.append([a, b])
    spans.sort()
    out: list[list[float]] = []
    for a, b in spans:
        if out and a - out[-1][1] <= gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [[round(a, 3), round(b, 3)] for a, b in out]


def assess(real_speech_segments: list[dict[str, Any]], duration: float | None) -> dict[str, Any]:
    """Whether the stray speech of one silent unit is muted at S7 (True) or keeps the S6 reject (False)."""
    windows = merged_windows(real_speech_segments, duration)
    seconds = round(sum(b - a for a, b in windows), 3)
    row: dict[str, Any] = {"type": ADJUDICATION_TYPE, "mute_source_windows": windows, "speech_seconds": seconds,
                           "duration_seconds": duration, "max_speech_fraction": MAX_SPEECH_FRACTION,
                           "pad_seconds": PAD_SECONDS}
    if not windows:
        return {**row, "mutable": False, "reason": "NO_REAL_SPEECH_WINDOW"}
    if not duration or float(duration) <= 0:
        return {**row, "mutable": False, "reason": "CLIP_DURATION_UNKNOWN"}
    fraction = seconds / float(duration)
    row["speech_fraction"] = round(fraction, 3)
    if fraction > MAX_SPEECH_FRACTION:
        return {**row, "mutable": False, "reason": "STRAY_SPEECH_COVERS_MOST_OF_THE_CLIP"}
    return {**row, "mutable": True, "reason": "MUTED_AT_S7_NATIVE_AMBIENCE_KEPT_OUTSIDE_THE_WINDOWS",
            "rule": "a silent unit's murmur is muted on the native cut at S7 (free); the S6 reject is recorded, "
                    "not raised, while the murmur covers at most max_speech_fraction of the clip"}


def windows_from_record(record: dict[str, Any]) -> tuple[list[list[float]], str]:
    """(source windows to mute, reason) from one unit's ``*_POST_GENERATION_QA.json``.

    Only a unit with no expected dialogue line qualifies.  A record written by this engine carries the S6
    adjudication; an older record (or one admitted by a line-owner order) is re-assessed from its D-18b
    real-speech segments with the same rule, so a murmur that shipped before is muted too."""
    dq = record.get("dialogue_qa") or {}
    if int(dq.get("expected_line_count") or 0) != 0:
        return [], "UNIT_HAS_DIALOGUE"
    rows = [r for r in dq.get("machine_adjudications") or [] if isinstance(r, dict)]
    stamped = next((r for r in rows if r.get("type") == ADJUDICATION_TYPE), None)
    if stamped is not None:
        return ((stamped.get("mute_source_windows") or []) if stamped.get("mutable") else [],
                str(stamped.get("reason") or ""))
    verify = next((r for r in rows if r.get("type") == "ASR_NO_SPEECH_VERIFICATION"), None)
    segments = (verify or {}).get("real_speech_segments") or []
    if not segments:
        return [], "NO_REAL_SPEECH_SEGMENTS"
    result = assess(segments, record_duration(record))
    return (result["mute_source_windows"] if result["mutable"] else []), result["reason"]


def record_duration(record: dict[str, Any]) -> float | None:
    """The measured clip duration a QA record carries (dialogue gate probe, else the technical duration check)."""
    for value in ((record.get("dialogue_qa") or {}).get("duration_seconds"),
                  (((record.get("technical_qa") or {}).get("checks") or {}).get("duration") or {}).get(
                      "measured_seconds")):
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
    return None


def plan(clips: dict[str, Any], records: dict[str, dict[str, Any]],
         sha_fn: Callable[[Any], str]) -> dict[str, Any]:
    """One row per clip: the windows muted and why.  A record is used only when it measured THIS clip
    (``media_sha256`` equals the clip on disk now); a rerolled or replaced clip is left alone."""
    rows: list[dict[str, Any]] = []
    for uid, clip in sorted(clips.items()):
        record = records.get(uid)
        row: dict[str, Any] = {"unit_id": uid, "clip": str(clip), "muted": False}
        if not isinstance(record, dict):
            rows.append({**row, "reason": "NO_POSTGEN_QA_RECORD"})
            continue
        windows, reason = windows_from_record(record)
        if not windows:
            rows.append({**row, "reason": reason})
            continue
        try:
            clip_sha = sha_fn(clip)
        except Exception as exc:  # noqa: BLE001 -- a hashing failure only leaves the unit untouched
            rows.append({**row, "reason": f"CLIP_HASH_FAILED:{type(exc).__name__}"})
            continue
        if clip_sha != record.get("media_sha256"):
            rows.append({**row, "reason": "QA_RECORD_MEASURED_ANOTHER_CLIP", "clip_sha256": clip_sha,
                         "record_media_sha256": record.get("media_sha256")})
            continue
        rows.append({**row, "muted": True, "reason": reason, "mute_source_windows": windows,
                     "clip_sha256": clip_sha})
    return {"schema": SCHEMA, "pad_seconds": PAD_SECONDS, "merge_gap_seconds": MERGE_GAP_SECONDS,
            "max_speech_fraction": MAX_SPEECH_FRACTION, "fade_out_seconds": FADE_OUT_SECONDS,
            "fade_in_seconds": FADE_IN_SECONDS, "muted_units": sum(1 for r in rows if r["muted"]), "units": rows}


def timeline_windows(report: dict[str, Any], project: dict[str, Any]) -> list[dict[str, Any]]:
    """Map each muted unit's source windows onto the rendered native cut through its audio clip(s).

    A re-cut unit (derived clip, other timing) and a visual-replacement clip are skipped; a window is clamped to
    the part of the source the clip actually plays (head/tail trims)."""
    wanted = {str(r["unit_id"]): r for r in report.get("units") or [] if r.get("muted")}
    out: list[dict[str, Any]] = []
    for track in (project.get("timeline") or {}).get("audioTracks") or []:
        for clip in track.get("clips") or []:
            meta = clip.get("metadata") or {}
            row = wanted.get(str(meta.get("source_id")))
            if row is None or meta.get("unit_recut") or meta.get("visual_replacement_only") \
                    or meta.get("reused_for_silent_visual"):
                continue
            start, source_in = float(clip.get("start") or 0.0), float(clip.get("in") or 0.0)
            length = float(clip.get("duration") or 0.0)
            for a, b in row.get("mute_source_windows") or []:
                lo, hi = max(float(a), source_in), float(b)
                if length > 0:
                    hi = min(hi, source_in + length)
                if hi - lo <= 0.0:
                    continue
                out.append({"unit_id": row["unit_id"], "start_seconds": round(start + lo - source_in, 6),
                            "end_seconds": round(start + hi - source_in, 6)})
    return sorted(out, key=lambda w: w["start_seconds"])


def gain_expression(windows: list[dict[str, Any]], fade_out: float = FADE_OUT_SECONDS,
                    fade_in: float = FADE_IN_SECONDS) -> str:
    """ffmpeg volume expression: 0 inside each window, linear ramps of ``fade_out`` before it and ``fade_in``
    after it, 1 elsewhere."""
    terms = []
    for w in windows:
        a, b = float(w["start_seconds"]), float(w["end_seconds"])
        terms.append(f"min(1,max(0,max(({a:.6f}-t)/{fade_out:g},(t-{b:.6f})/{fade_in:g})))")
    return "*".join(terms) or "1"


def mix_filter(windows: list[dict[str, Any]]) -> str:
    """-af chain for the native cut; small audio frames so ``t`` resolves the ramps."""
    return f"asetnsamples=n=64:p=0,volume='{gain_expression(windows)}':eval=frame"
