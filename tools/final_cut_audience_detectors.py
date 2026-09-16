#!/usr/bin/env python3
"""FINAL-CUT-AUDIENCE-DETECTORS: objective audience-facing checks on a rendered episode.

Detectors (report §三 D, PLAN §D):
  hook_present        first ASR speech <= --hook-seconds OR a shot-cut spike (frame difference
                      minus its local motion baseline) >= --cut-threshold inside that window
  dialogue_coverage   ASR speech seconds / duration >= --min-coverage
  silence_gap_max     largest leading/inter-line gap <= --max-silent-run (action windows use
                      --max-silent-run-action)
  voice_distinctness  per-line F0 vs voice cast band + per-scene speaker collision (needs
                      --voice-cast and a speaker map; else UNVERIFIED)
  emotion_dynamics    plead|fear|threat lines >= 6 dB above the same speaker's calm baseline
                      (needs emotions in the speaker map; else UNVERIFIED)
  lexicon_violation   forbidden terms / non-canonical name spellings in ASR text, .ass subtitles
                      and RapidOCR of frames sampled every 2.5 s (needs --lexicon; else UNVERIFIED)
  mascot_in_story     OpenCV template match of --brand-dir first frames against story-segment
                      frames sampled every 1 s (needs --brand-dir and --story-segments; else UNVERIFIED)
  loudness            ebur128 integrated within --release-lufs +-1, true peak <= --release-tp,
                      per-line window LUFS inside (-18, -12) and adjacent-line delta <= 6 LU
  state_machine / count_consistency / creature_locomotion  NOT_IMPLEMENTED (human review questions)

Every detector reports {status, measured, threshold, evidence}; a detector that lacked its
inputs is UNVERIFIED with a reason, never PASS.  Overall: FAIL if any FAIL, else UNVERIFIED if
any UNVERIFIED/NOT_IMPLEMENTED, else PASS.  ASR text is dropped from the output unless
--keep-asr-text is passed (evidence files may be committed).

The decision functions are pure so tests and the E04 regression fixture can drive them without
media; media access (ffmpeg, faster-whisper, cv2, RapidOCR) is imported lazily.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Sequence

import sys as _sys
from pathlib import Path as _P
_sys.path.insert(0, str(_P(__file__).resolve().parents[1]))  # direct invocation: repo root on sys.path
from tools import dialogue_voice_metrics as dvm
from tools import voice_cast_gate as vcg

SCHEMA = "qingshan.final_cut_audience_detectors.v1"
GATE_ID = "FINAL-CUT-AUDIENCE-DETECTORS"

DETECTOR_ORDER = (
    "hook_present", "dialogue_coverage", "silence_gap_max", "voice_distinctness", "emotion_dynamics",
    "lexicon_violation", "mascot_in_story", "loudness", "state_machine", "count_consistency", "creature_locomotion",
)
HUMAN_REVIEW_DETECTORS = ("state_machine", "count_consistency", "creature_locomotion")

DEFAULTS: dict[str, Any] = {
    "hook_seconds": 5.0,
    "cut_threshold": 25.0,          # 0-255 mean-abs grey difference spike
    "max_silent_run": 15.0,
    "max_silent_run_action": 25.0,
    "min_coverage": 0.35,
    "release_lufs": -14.0,
    "release_lufs_tolerance": 1.0,
    "release_tp": -1.0,
    "window_lufs_range": (-18.0, -12.0),
    "adjacent_delta_max_lu": 6.0,
    "mascot_score_threshold": 0.85,
    "ocr_every_seconds": 2.5,
    "mascot_every_seconds": 1.0,
    "ocr_min_confidence": 0.5,
    "speaker_map_tolerance_s": 0.6,
}

STATUS_RANK = {"PASS": 0, "NOT_IMPLEMENTED": 1, "UNVERIFIED": 1, "FAIL": 2}


def detector(status: str, *, measured: Any = None, threshold: Any = None, evidence: Any = None,
             reason: str | None = None, failures: Sequence[str] | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {"status": status, "measured": measured, "threshold": threshold,
                           "evidence": evidence if evidence is not None else {}}
    if reason:
        row["reason"] = reason
    if failures:
        row["failures"] = list(failures)
    return row


# --------------------------------------------------------------------------- pure decisions

def decide_hook(first_speech_s: float | None, max_cut_spike: float | None, *, hook_seconds: float,
                cut_threshold: float, max_frame_diff: float | None = None) -> dict[str, Any]:
    threshold = {"hook_seconds": hook_seconds, "cut_spike_threshold_0_255": cut_threshold}
    measured = {"first_speech_s": first_speech_s, "max_cut_spike": max_cut_spike, "max_frame_diff": max_frame_diff}
    if first_speech_s is None and max_cut_spike is None:
        return detector("UNVERIFIED", measured=measured, threshold=threshold, reason="no ASR and no frame analysis")
    fired: list[str] = []
    if first_speech_s is not None and first_speech_s <= hook_seconds:
        fired.append("dialogue")
    if max_cut_spike is not None and max_cut_spike >= cut_threshold:
        fired.append("shock_cut")
    evidence = {"fired": fired,
                "note": "dialogue = first ASR window starts inside the hook window; shock_cut = frame-difference "
                        "spike above local motion baseline (a hard cut), raw max frame difference reported for context"}
    if fired:
        return detector("PASS", measured=measured, threshold=threshold, evidence=evidence)
    return detector("FAIL", measured=measured, threshold=threshold, evidence=evidence,
                    failures=["HOOK_MISSING"])


def speech_seconds(segments: Sequence[dict[str, Any]]) -> float:
    total = 0.0
    for seg in segments:
        total += max(0.0, float(seg.get("end", 0.0)) - float(seg.get("start", 0.0)))
    return round(total, 3)


def decide_coverage(segments: Sequence[dict[str, Any]], duration_s: float | None, *, min_coverage: float) -> dict[str, Any]:
    if not duration_s or duration_s <= 0:
        return detector("UNVERIFIED", threshold={"min_coverage": min_coverage}, reason="duration unknown")
    speech = speech_seconds(segments)
    coverage = round(speech / float(duration_s), 4)
    measured = {"speech_seconds": speech, "duration_s": duration_s, "coverage": coverage, "lines": len(segments)}
    if coverage >= min_coverage:
        return detector("PASS", measured=measured, threshold={"min_coverage": min_coverage})
    return detector("FAIL", measured=measured, threshold={"min_coverage": min_coverage},
                    failures=[f"DIALOGUE_STARVATION:coverage={coverage}"])


def speech_gaps(segments: Sequence[dict[str, Any]], duration_s: float | None) -> list[dict[str, Any]]:
    """Leading, inter-line and trailing gaps between ASR windows."""
    rows = sorted(({"start": float(s["start"]), "end": float(s["end"])} for s in segments), key=lambda r: r["start"])
    gaps: list[dict[str, Any]] = []
    if not rows:
        if duration_s:
            gaps.append({"kind": "leading", "start": 0.0, "end": float(duration_s), "gap_s": round(float(duration_s), 3)})
        return gaps
    if rows[0]["start"] > 0:
        gaps.append({"kind": "leading", "start": 0.0, "end": rows[0]["start"], "gap_s": round(rows[0]["start"], 3)})
    for prev, nxt in zip(rows, rows[1:]):
        gap = nxt["start"] - prev["end"]
        if gap > 0:
            gaps.append({"kind": "between", "start": prev["end"], "end": nxt["start"], "gap_s": round(gap, 3)})
    if duration_s and float(duration_s) > rows[-1]["end"]:
        gaps.append({"kind": "trailing", "start": rows[-1]["end"], "end": float(duration_s),
                     "gap_s": round(float(duration_s) - rows[-1]["end"], 3)})
    return gaps


def _inside_windows(start: float, end: float, windows: Sequence[Sequence[float]] | None) -> bool:
    if not windows:
        return False
    mid = (start + end) / 2.0
    return any(float(w[0]) <= mid <= float(w[1]) for w in windows)


def decide_silence_gaps(segments: Sequence[dict[str, Any]], duration_s: float | None, *, max_run: float,
                        max_run_action: float, action_windows: Sequence[Sequence[float]] | None = None) -> dict[str, Any]:
    threshold = {"max_silent_run_s": max_run, "max_silent_run_action_s": max_run_action,
                 "action_windows": [list(map(float, w)) for w in (action_windows or [])]}
    if not segments and not duration_s:
        return detector("UNVERIFIED", threshold=threshold, reason="no ASR windows and no duration")
    gaps = speech_gaps(segments, duration_s)
    judged = [g for g in gaps if g["kind"] != "trailing"]   # the end card / outro is not a dialogue starvation
    failures: list[str] = []
    for gap in judged:
        limit = max_run_action if _inside_windows(gap["start"], gap["end"], action_windows) else max_run
        gap["limit_s"] = limit
        if gap["gap_s"] > limit:
            failures.append(f"SILENT_RUN:{gap['start']:.1f}-{gap['end']:.1f}:{gap['gap_s']:.1f}s>{limit:g}s")
    largest = max((g["gap_s"] for g in judged), default=0.0)
    largest_gap = max(judged, key=lambda g: g["gap_s"]) if judged else None
    measured = {"largest_gap_s": largest, "largest_gap": largest_gap,
                "gaps_over_limit": len(failures), "trailing_gap_s": next((g["gap_s"] for g in gaps if g["kind"] == "trailing"), 0.0)}
    evidence = {"gaps": sorted(judged, key=lambda g: -g["gap_s"])[:10]}
    if failures:
        return detector("FAIL", measured=measured, threshold=threshold, evidence=evidence, failures=failures)
    return detector("PASS", measured=measured, threshold=threshold, evidence=evidence)


def decide_voice_distinctness(cast: dict[str, Any] | None, segments: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not cast:
        return detector("UNVERIFIED", reason="no --voice-cast supplied")
    if not any(seg.get("speaker") for seg in segments):
        return detector("UNVERIFIED", reason="no speaker attribution (supply --speaker-map)")
    result = vcg.postcheck(cast, segments)
    measured = result.get("measurements") or {}
    row = detector(result["status"], measured={k: v for k, v in measured.items() if k != "lines"},
                   threshold={"band": "voice_cast f0_band_hz per speaker", "collision_ratio": vcg.COLLISION_RATIO},
                   evidence={"lines": measured.get("lines", []), "unverified": result.get("unverified", [])},
                   failures=result.get("failures"))
    if result["status"] == "UNVERIFIED":
        row["reason"] = ";".join(result.get("unverified", [])) or "voice cast gate could not decide"
    return row


def decide_emotion_dynamics(segments: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not any(seg.get("emotion") for seg in segments):
        return detector("UNVERIFIED", reason="no emotion annotation (supply --speaker-map with emotion)")
    result = vcg.emotion_dynamics(segments)
    row = detector(result["status"], measured=result.get("measurements"),
                   threshold={"delta_db": vcg.EMOTION_DELTA_DB, "emotive": sorted(vcg.EMOTIVE)},
                   evidence={"unverified": result.get("unverified", [])}, failures=result.get("failures"))
    if result["status"] == "UNVERIFIED":
        row["reason"] = ";".join(result.get("unverified", []))
    return row


_KEEP = {"Lo", "Ll", "Lu", "Nd", "Nl", "No"}


def normalise_text(text: str) -> str:
    """Pinyin-free normalisation: NFKC, lower case, keep only letters/digits (drops spaces & punctuation)."""
    folded = unicodedata.normalize("NFKC", str(text or "")).lower()
    return "".join(ch for ch in folded if unicodedata.category(ch) in _KEEP)


def decide_lexicon(lexicon: dict[str, Any] | None, *, asr_texts: Sequence[dict[str, Any]] | None,
                   subtitle_texts: Sequence[str] | None, ocr_texts: Sequence[dict[str, Any]] | None) -> dict[str, Any]:
    """``asr_texts``/``ocr_texts`` rows: {time, text}. Only the matched term (never the text) is written to evidence."""
    if not lexicon:
        return detector("UNVERIFIED", reason="no --lexicon supplied")
    forbidden = [str(t) for t in (lexicon.get("forbidden_terms") or []) if str(t).strip()]
    variants: dict[str, str] = {}
    for canonical, alts in (lexicon.get("canonical_names") or {}).items():
        for alt in alts or []:
            if str(alt) and str(alt) != str(canonical):
                variants[str(alt)] = str(canonical)
    if asr_texts is None and subtitle_texts is None and ocr_texts is None:
        return detector("UNVERIFIED", threshold={"forbidden_terms": len(forbidden), "name_variants": len(variants)},
                        reason="no ASR text, subtitles or OCR available")
    hits: list[dict[str, Any]] = []
    visible_terms: set[str] = set()
    for source, rows in (("subtitle", [{"text": t} for t in (subtitle_texts or [])]), ("ocr", list(ocr_texts or []))):
        for row in rows:
            norm = normalise_text(row.get("text", ""))
            for term in forbidden:
                if normalise_text(term) and normalise_text(term) in norm:
                    hits.append({"source": source, "kind": "forbidden_term", "term": term, "time": row.get("time")})
                    visible_terms.add(term)
            for alt, canonical in variants.items():
                if normalise_text(alt) in norm:
                    hits.append({"source": source, "kind": "name_variant", "term": alt, "canonical": canonical,
                                 "time": row.get("time")})
    for row in asr_texts or []:
        norm = normalise_text(row.get("text", ""))
        for term in forbidden:
            key = normalise_text(term)
            if key and key in norm:
                hits.append({"source": "asr", "kind": "forbidden_term", "term": term, "time": row.get("start", row.get("time")),
                             "asr_only": term not in visible_terms})
    failures: list[str] = []
    for hit in hits:
        if hit["kind"] == "forbidden_term":
            code = f"LEXICON_FORBIDDEN:{hit['term']}:{hit['source']}"
        else:
            code = f"NAME_VARIANT:{hit['term']}:{hit['source']}"
        if code not in failures:
            failures.append(code)
    measured = {"hits": len(hits), "asr_windows": len(asr_texts or []), "subtitle_lines": len(subtitle_texts or []),
                "ocr_frames": len(ocr_texts or [])}
    threshold = {"forbidden_terms": len(forbidden), "name_variants": len(variants),
                 "note": "ASR compared after pinyin-free normalisation (exact substring); name variants judged on visible text only"}
    if failures:
        return detector("FAIL", measured=measured, threshold=threshold, evidence={"hits": hits}, failures=failures)
    return detector("PASS", measured=measured, threshold=threshold, evidence={"hits": hits})


def decide_mascot(scores: Sequence[dict[str, Any]] | None, *, threshold: float, brand_available: bool,
                  story_available: bool) -> dict[str, Any]:
    if not brand_available:
        return detector("UNVERIFIED", threshold={"score": threshold}, reason="no --brand-dir supplied")
    if not story_available:
        return detector("UNVERIFIED", threshold={"score": threshold}, reason="no --story-segments supplied")
    if scores is None:
        return detector("UNVERIFIED", threshold={"score": threshold}, reason="no frames sampled")
    hits = [s for s in scores if float(s.get("score", 0.0)) >= threshold]
    best = max((float(s.get("score", 0.0)) for s in scores), default=0.0)
    measured = {"frames": len(scores), "best_score": round(best, 4), "hits": len(hits)}
    if hits:
        return detector("FAIL", measured=measured, threshold={"score": threshold}, evidence={"hits": hits[:20]},
                        failures=[f"MASCOT_IN_STORY:{h['template']}:{float(h['time']):.1f}" for h in hits[:20]])
    return detector("PASS", measured=measured, threshold={"score": threshold}, evidence={"top": sorted(scores, key=lambda s: -float(s.get("score", 0.0)))[:5]})


def decide_loudness(integrated_lufs: float | None, true_peak_dbtp: float | None, window_lufs: Sequence[dict[str, Any]], *,
                    release_lufs: float, tolerance: float, release_tp: float, window_range: Sequence[float],
                    adjacent_delta_max: float) -> dict[str, Any]:
    threshold = {"integrated_lufs": [release_lufs - tolerance, release_lufs + tolerance], "true_peak_dbtp_max": release_tp,
                 "window_lufs_range": list(window_range), "adjacent_delta_max_lu": adjacent_delta_max}
    if integrated_lufs is None and true_peak_dbtp is None:
        return detector("UNVERIFIED", threshold=threshold, reason="no ebur128 measurement")
    failures: list[str] = []
    if integrated_lufs is None:
        failures.append("LOUDNESS_INTEGRATED_UNMEASURED")
    elif not (release_lufs - tolerance <= integrated_lufs <= release_lufs + tolerance):
        failures.append(f"LOUDNESS_INTEGRATED_OUT_OF_BAND:{integrated_lufs}")
    if true_peak_dbtp is None:
        failures.append("TRUE_PEAK_UNMEASURED")
    elif true_peak_dbtp > release_tp:
        failures.append(f"TRUE_PEAK_OVER:{true_peak_dbtp}")
    lo, hi = float(window_range[0]), float(window_range[1])
    measured_windows = [w for w in window_lufs if w.get("lufs_window") is not None]
    out_of_range = [w for w in measured_windows if not (lo <= float(w["lufs_window"]) <= hi)]
    for w in out_of_range:
        failures.append(f"WINDOW_LUFS_OUT_OF_RANGE:{float(w['start']):.1f}:{w['lufs_window']}")
    deltas: list[dict[str, Any]] = []
    for prev, nxt in zip(measured_windows, measured_windows[1:]):
        delta = round(abs(float(nxt["lufs_window"]) - float(prev["lufs_window"])), 2)
        deltas.append({"from": prev["start"], "to": nxt["start"], "delta_lu": delta})
        if delta > adjacent_delta_max:
            failures.append(f"ADJACENT_LINE_DELTA:{float(prev['start']):.1f}->{float(nxt['start']):.1f}:{delta}LU")
    values = [float(w["lufs_window"]) for w in measured_windows]
    measured = {"integrated_lufs": integrated_lufs, "true_peak_dbtp": true_peak_dbtp,
                "windows_measured": len(measured_windows), "windows_out_of_range": len(out_of_range),
                "window_lufs_min": min(values) if values else None, "window_lufs_max": max(values) if values else None,
                "max_adjacent_delta_lu": max((d["delta_lu"] for d in deltas), default=0.0)}
    evidence = {"windows_out_of_range": [{"start": w["start"], "end": w["end"], "lufs_window": w["lufs_window"]} for w in out_of_range][:20],
                "adjacent_deltas_over": [d for d in deltas if d["delta_lu"] > adjacent_delta_max][:20]}
    if not measured_windows:
        evidence["note"] = "no per-line LUFS windows measured; only programme loudness judged"
    if failures:
        return detector("FAIL", measured=measured, threshold=threshold, evidence=evidence, failures=failures)
    return detector("PASS", measured=measured, threshold=threshold, evidence=evidence)


def overall_status(detectors: dict[str, dict[str, Any]]) -> tuple[str, list[str]]:
    unverified = [name for name, row in detectors.items() if row.get("status") in ("UNVERIFIED", "NOT_IMPLEMENTED")]
    if any(row.get("status") == "FAIL" for row in detectors.values()):
        return "FAIL", unverified
    if unverified:
        return "UNVERIFIED", unverified
    return "PASS", unverified


def apply_speaker_map(segments: Sequence[dict[str, Any]], speaker_map: Sequence[dict[str, Any]] | None,
                      *, tolerance_s: float = DEFAULTS["speaker_map_tolerance_s"]) -> list[dict[str, Any]]:
    """Attach speaker/emotion/scene to ASR windows. Map rows carry ``index`` or ``time`` (seconds)."""
    rows = [dict(seg) for seg in segments]
    unmatched: list[dict[str, Any]] = []
    for entry in speaker_map or []:
        target = None
        if entry.get("index") is not None:
            idx = int(entry["index"])
            target = rows[idx] if 0 <= idx < len(rows) else None
        elif entry.get("time") is not None:
            t = float(entry["time"])
            containing = [r for r in rows if float(r["start"]) - tolerance_s <= t <= float(r["end"]) + tolerance_s]
            if containing:
                target = min(containing, key=lambda r: abs(float(r["start"]) - t))
        if target is None:
            unmatched.append(entry)
            continue
        for key in ("speaker", "emotion", "scene"):
            if entry.get(key):
                target[key] = entry[key]
    if unmatched:
        rows_unmatched = [{"time": e.get("time"), "index": e.get("index"), "speaker": e.get("speaker")} for e in unmatched]
        for row in rows:
            row.setdefault("_speaker_map_unmatched", rows_unmatched)
    return rows


def evaluate_from_measurements(m: dict[str, Any], options: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the full report from already-measured inputs (no media access).

    ``m`` keys: duration_s, segments (ASR windows with f0_median_hz / rms_dbfs / lufs_window and optional
    speaker / emotion / scene / text), max_cut_spike, max_frame_diff, integrated_lufs, true_peak_dbtp,
    voice_cast, lexicon, subtitle_texts, ocr_texts, mascot_scores, brand_available, story_available,
    action_windows.
    """
    opts = dict(DEFAULTS)
    opts.update(options or {})
    segments = list(m.get("segments") or [])
    duration = m.get("duration_s")
    first_speech = min((float(s["start"]) for s in segments), default=None)
    detectors: dict[str, dict[str, Any]] = {
        "hook_present": decide_hook(first_speech, m.get("max_cut_spike"), hook_seconds=opts["hook_seconds"],
                                    cut_threshold=opts["cut_threshold"], max_frame_diff=m.get("max_frame_diff")),
        "dialogue_coverage": decide_coverage(segments, duration, min_coverage=opts["min_coverage"]),
        "silence_gap_max": decide_silence_gaps(segments, duration, max_run=opts["max_silent_run"],
                                               max_run_action=opts["max_silent_run_action"],
                                               action_windows=m.get("action_windows")),
        "voice_distinctness": decide_voice_distinctness(m.get("voice_cast"), segments),
        "emotion_dynamics": decide_emotion_dynamics(segments),
        "lexicon_violation": decide_lexicon(m.get("lexicon"), asr_texts=[s for s in segments if "text" in s] if m.get("lexicon") else None,
                                            subtitle_texts=m.get("subtitle_texts"), ocr_texts=m.get("ocr_texts")),
        "mascot_in_story": decide_mascot(m.get("mascot_scores"), threshold=opts["mascot_score_threshold"],
                                         brand_available=bool(m.get("brand_available")),
                                         story_available=bool(m.get("story_available"))),
        "loudness": decide_loudness(m.get("integrated_lufs"), m.get("true_peak_dbtp"), segments,
                                    release_lufs=opts["release_lufs"], tolerance=opts["release_lufs_tolerance"],
                                    release_tp=opts["release_tp"], window_range=opts["window_lufs_range"],
                                    adjacent_delta_max=opts["adjacent_delta_max_lu"]),
    }
    for name in HUMAN_REVIEW_DETECTORS:
        detectors[name] = detector("NOT_IMPLEMENTED", reason="human review question")
    if "lexicon_violation" in detectors and m.get("lexicon") and not any("text" in s for s in segments) \
            and m.get("subtitle_texts") is None and m.get("ocr_texts") is None:
        detectors["lexicon_violation"] = detector("UNVERIFIED", reason="lexicon given but no ASR text, subtitles or OCR available")
    status, unverified = overall_status(detectors)
    failures = [f for row in detectors.values() for f in row.get("failures", [])]
    return {
        "schema": SCHEMA,
        "gate_id": GATE_ID,
        "status": status,
        "failures": failures,
        "unverified": unverified,
        "thresholds": {k: (list(v) if isinstance(v, tuple) else v) for k, v in opts.items()},
        "detectors": {name: detectors[name] for name in DETECTOR_ORDER},
    }


# --------------------------------------------------------------------------- media measurement

def first_window_cut_spike(media: Path, seconds: float, *, size: tuple[int, int] = (90, 160),
                           neighbourhood: int = 6) -> dict[str, float | None]:
    """Max raw mean-abs grey frame difference and max cut spike (difference minus the median of the
    +-``neighbourhood`` surrounding differences) within the first ``seconds`` of ``media``."""
    import cv2
    import numpy as np

    cap = cv2.VideoCapture(str(media))
    prev = None
    diffs: list[float] = []
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            pos = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            if pos > seconds:
                break
            grey = cv2.cvtColor(cv2.resize(frame, size), cv2.COLOR_BGR2GRAY).astype(np.float32)
            if prev is not None:
                diffs.append(float(np.abs(grey - prev).mean()))
            prev = grey
    finally:
        cap.release()
    if not diffs:
        return {"max_frame_diff": None, "max_cut_spike": None, "frames": 0}
    raw = np.array(diffs)
    spikes = []
    for i in range(raw.size):
        lo, hi = max(0, i - neighbourhood), min(raw.size, i + neighbourhood + 1)
        nb = np.concatenate([raw[lo:i], raw[i + 1:hi]])
        spikes.append(float(raw[i] - np.median(nb)) if nb.size else 0.0)
    return {"max_frame_diff": round(float(raw.max()), 3), "max_cut_spike": round(max(spikes), 3), "frames": int(raw.size)}


def sample_frames(media: Path, times: Sequence[float]):
    """Yield (time, BGR frame) for the requested timestamps."""
    import cv2

    cap = cv2.VideoCapture(str(media))
    try:
        for t in times:
            cap.set(cv2.CAP_PROP_POS_MSEC, float(t) * 1000.0)
            ok, frame = cap.read()
            if ok:
                yield float(t), frame
    finally:
        cap.release()


def _sample_times(windows: Sequence[Sequence[float]], every: float) -> list[float]:
    times: list[float] = []
    for start, end in windows:
        t = float(start)
        while t < float(end):
            times.append(round(t, 3))
            t += every
    return times


def ocr_frames(media: Path, duration_s: float, *, every: float, min_confidence: float) -> list[dict[str, Any]]:
    from rapidocr_onnxruntime import RapidOCR

    engine = RapidOCR()
    rows: list[dict[str, Any]] = []
    for t, frame in sample_frames(media, _sample_times([(0.0, duration_s)], every)):
        result, _elapsed = engine(frame)
        texts = [str(text).strip() for _box, text, conf in (result or []) if float(conf) >= min_confidence and str(text).strip()]
        if texts:
            rows.append({"time": t, "text": " ".join(texts)})
    return rows


UNIFORM_TEMPLATE_STD_MIN = 12.0


def load_brand_templates(brand_dir: Path, *, width: int = 240):
    """First frame of every image/video in ``brand_dir`` as a grey template scaled to ``width``."""
    import cv2

    templates = []
    for path in sorted(brand_dir.iterdir()):
        if path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
            frame = cv2.imread(str(path))
        elif path.suffix.lower() in (".mp4", ".mov", ".m4v"):
            # the MIDDLE frame: brand cards fade in from black, and a black first frame would
            # match every dark story frame (E04 backtest: 200 false hits at score 1.0)
            cap = cv2.VideoCapture(str(path))
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            if total > 2:
                cap.set(cv2.CAP_PROP_POS_FRAMES, total // 2)
            ok, frame = cap.read()
            cap.release()
            if not ok:
                continue
        else:
            continue
        if frame is None:
            continue
        h, w = frame.shape[:2]
        scale = width / float(w)
        grey = cv2.cvtColor(cv2.resize(frame, (width, max(1, int(round(h * scale))))), cv2.COLOR_BGR2GRAY)
        if float(grey.std()) < UNIFORM_TEMPLATE_STD_MIN:
            # a near-uniform template (black/white card) matches anything; it is not evidence
            continue
        templates.append((path.name, grey))
    return templates


def mascot_scores(media: Path, brand_dir: Path, story_windows: Sequence[Sequence[float]], *, every: float,
                  width: int = 240) -> list[dict[str, Any]]:
    import cv2

    templates = load_brand_templates(brand_dir, width=width)
    rows: list[dict[str, Any]] = []
    if not templates:
        return rows
    for t, frame in sample_frames(media, _sample_times(story_windows, every)):
        h, w = frame.shape[:2]
        grey = cv2.cvtColor(cv2.resize(frame, (width, max(1, int(round(h * width / float(w)))))), cv2.COLOR_BGR2GRAY)
        for name, template in templates:
            tpl = template
            if tpl.shape[0] > grey.shape[0] or tpl.shape[1] > grey.shape[1]:
                scale = min(grey.shape[0] / tpl.shape[0], grey.shape[1] / tpl.shape[1])
                tpl = cv2.resize(tpl, (max(1, int(tpl.shape[1] * scale)), max(1, int(tpl.shape[0] * scale))))
            score = float(cv2.matchTemplate(grey, tpl, cv2.TM_CCOEFF_NORMED).max())
            rows.append({"time": t, "template": name, "score": round(score, 4)})
    return rows


_ASS_TAG = re.compile(r"\{[^}]*\}")


def parse_ass_texts(path: Path) -> list[str]:
    texts: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("Dialogue:"):
            continue
        parts = line.split(",", 9)
        if len(parts) < 10:
            continue
        text = _ASS_TAG.sub("", parts[9]).replace("\\N", " ").replace("\\n", " ").strip()
        if text:
            texts.append(text)
    return texts


def load_story_windows(path: Path) -> tuple[list[list[float]], list[list[float]]]:
    """(story_windows, action_windows) from a release_timeline.json (rows with ``type`` are authoritative;
    untyped unit rows count as story, clipped to ``content_runtime_seconds``) or a plain [[s, e], ...] list."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    story: list[list[float]] = []
    action: list[list[float]] = []
    if isinstance(payload, list):
        for row in payload:
            if isinstance(row, (list, tuple)) and len(row) == 2:
                story.append([float(row[0]), float(row[1])])
        return story, action
    limit = payload.get("content_runtime_seconds")
    for row in payload.get("segments") or []:
        start = row.get("output_start", row.get("start"))
        end = row.get("output_end", row.get("end"))
        if start is None or end is None:
            continue
        start, end = float(start), float(end)
        if limit is not None:
            end = min(end, float(limit))
        if end <= start:
            continue
        kind = str(row.get("type") or "story")
        if kind == "story":
            story.append([start, end])
        if kind == "action" or str(row.get("beat_type") or "") == "action":
            story.append([start, end])
            action.append([start, end])
    return story, action


def _load_json(path: Path | None) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path else None


def _segments_from_json(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        payload = payload.get("segments") or []
    return [dict(seg) for seg in payload if isinstance(seg, dict)]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Objective audience-facing detectors on a final cut.")
    parser.add_argument("--media", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--asr-json", type=Path, help="precomputed ASR windows [{start,end,text?}] (skips faster-whisper)")
    parser.add_argument("--asr-model", default="small")
    parser.add_argument("--lexicon", type=Path)
    parser.add_argument("--subtitles", type=Path, help=".ass subtitle file")
    parser.add_argument("--voice-cast", type=Path)
    parser.add_argument("--speaker-map", type=Path, help="{lines:[{time|index, speaker, emotion?, scene?}]}")
    parser.add_argument("--brand-dir", type=Path)
    parser.add_argument("--story-segments", type=Path, help="release_timeline.json or [[start,end],...]")
    parser.add_argument("--action-windows", type=Path, help="[[start,end],...] windows judged with --max-silent-run-action")
    parser.add_argument("--hook-seconds", type=float, default=DEFAULTS["hook_seconds"])
    parser.add_argument("--cut-threshold", type=float, default=DEFAULTS["cut_threshold"])
    parser.add_argument("--max-silent-run", type=float, default=DEFAULTS["max_silent_run"])
    parser.add_argument("--max-silent-run-action", type=float, default=DEFAULTS["max_silent_run_action"])
    parser.add_argument("--min-coverage", type=float, default=DEFAULTS["min_coverage"])
    parser.add_argument("--release-lufs", type=float, default=DEFAULTS["release_lufs"])
    parser.add_argument("--release-tp", type=float, default=DEFAULTS["release_tp"])
    parser.add_argument("--mascot-score", type=float, default=DEFAULTS["mascot_score_threshold"])
    parser.add_argument("--no-window-lufs", action="store_true", help="skip per-line ebur128 windows")
    parser.add_argument("--keep-asr-text", action="store_true", help="write ASR text into --out (off by default)")
    args = parser.parse_args(argv)

    media = args.media
    duration = dvm.probe_duration(media)
    if args.asr_json:
        segments = _segments_from_json(_load_json(args.asr_json))
        asr_source = f"asr_json:{args.asr_json.name}"
    else:
        segments = dvm.transcribe_segments(media, model=args.asr_model)
        asr_source = f"faster_whisper:{args.asr_model}"
    texts = [seg.get("text") for seg in segments]
    measured = dvm.measure_media(media, segments, with_lufs=not args.no_window_lufs)
    for row, text in zip(measured, texts):
        if text is not None:
            row["text"] = text

    speaker_payload = _load_json(args.speaker_map)
    speaker_map = (speaker_payload.get("lines") if isinstance(speaker_payload, dict) else speaker_payload) or []
    measured = apply_speaker_map(measured, speaker_map)

    cut = first_window_cut_spike(media, args.hook_seconds)
    lexicon = _load_json(args.lexicon)
    subtitle_texts = parse_ass_texts(args.subtitles) if args.subtitles else None
    ocr_texts = ocr_frames(media, duration or 0.0, every=DEFAULTS["ocr_every_seconds"],
                           min_confidence=DEFAULTS["ocr_min_confidence"]) if (lexicon and duration) else None
    story_windows, action_windows = load_story_windows(args.story_segments) if args.story_segments else ([], [])
    if args.action_windows:
        action_windows = [[float(a), float(b)] for a, b in _load_json(args.action_windows)]
    scores = None
    if args.brand_dir and story_windows:
        scores = mascot_scores(media, args.brand_dir, story_windows, every=DEFAULTS["mascot_every_seconds"])
    loud = dvm.measure_program_loudness(media)

    report = evaluate_from_measurements({
        "duration_s": duration,
        "segments": measured,
        "max_cut_spike": cut["max_cut_spike"],
        "max_frame_diff": cut["max_frame_diff"],
        "integrated_lufs": loud["integrated_lufs"],
        "true_peak_dbtp": loud["true_peak_dbtp"],
        "voice_cast": _load_json(args.voice_cast),
        "lexicon": lexicon,
        "subtitle_texts": subtitle_texts,
        "ocr_texts": ocr_texts,
        "mascot_scores": scores,
        "brand_available": bool(args.brand_dir),
        "story_available": bool(story_windows),
        "action_windows": action_windows,
    }, {
        "hook_seconds": args.hook_seconds, "cut_threshold": args.cut_threshold,
        "max_silent_run": args.max_silent_run, "max_silent_run_action": args.max_silent_run_action,
        "min_coverage": args.min_coverage, "release_lufs": args.release_lufs, "release_tp": args.release_tp,
        "mascot_score_threshold": args.mascot_score,
    })
    evidence_segments = measured if args.keep_asr_text else dvm.strip_text(measured)
    for row in evidence_segments:
        row.pop("_speaker_map_unmatched", None)
    report["inputs"] = {
        "media": media.name, "media_sha256": dvm.media_sha256(media), "duration_s": duration, "asr_source": asr_source,
        "asr_text_kept": bool(args.keep_asr_text), "speaker_map_lines": len(speaker_map),
        "speaker_map_unmatched": next((r.get("_speaker_map_unmatched") for r in measured if r.get("_speaker_map_unmatched")), []),
        "subtitles": args.subtitles.name if args.subtitles else None, "lexicon": args.lexicon.name if args.lexicon else None,
        "brand_dir": str(args.brand_dir.name) if args.brand_dir else None, "story_windows": len(story_windows),
        "loudness_range_lu": loud.get("loudness_range_lu"),
    }
    report["segments"] = evidence_segments
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "failures": report["failures"], "unverified": report["unverified"],
                      "out": str(args.out)}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    import os
    import sys

    _rc = main()
    # faster-whisper (ctranslate2/av) and OpenCV ship duplicate libavdevice builds; when both are loaded
    # in one process the interpreter can abort during teardown (recursive_mutex lock failed, exit 134)
    # after the report is already written.  Flush and exit hard so the gate's exit code survives.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(_rc)
