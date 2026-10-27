#!/usr/bin/env python3
"""Leading vocal burst at unit start (CAMERA_GRAMMAR_V1 episodes only; line owner 2026-10-23).

A MiniMax-H3 unit that continues from the previous unit's tail frame (mouth open) can open with a
~0.1 s loud vocal burst ("衣") followed by near-digital silence before its line starts (lab urban
E03-VU-002/006/007: -10…-17 dBFS in the first 50-100 ms, then <= -74 dBFS, line at +1.4…1.9 s).
At S7 the burst is muted on the rendered native cut with short fades; the video stream is copied
and the duration is unchanged.

Detection per unit clip (source seconds): some 10 ms window inside the first ``BURST_MAX_SECONDS``
is above ``BURST_DBFS`` and is followed, no later than ``BURST_MAX_SECONDS``, by at least
``SILENCE_MIN_SECONDS`` entirely below ``SILENCE_DBFS``.  A line is never touched: the unit's ASR
must place its first line after that silence.  faster-whisper (VAD) snaps a first segment that
follows a short leading noise to 0.0 s, so a segment starting inside the burst counts as "after the
silence" only when it ends after the silence AND speech energy (>= ``ONSET_DBFS``) resumes after the
silence; otherwise the unit is left alone and the reason is recorded.

Pure functions plus one ffmpeg PCM read; the S7 caller supplies the clips, the unit ASR and the
AgentCut project and runs the mix.
"""

from __future__ import annotations

import math
import subprocess
from pathlib import Path
from typing import Any

SCHEMA = "nalu.dialogue_leading_burst.v1"
SAMPLE_RATE = 16000
WINDOW_SECONDS = 0.01
BURST_MAX_SECONDS = 0.25
BURST_DBFS = -30.0
SILENCE_DBFS = -55.0
SILENCE_MIN_SECONDS = 0.25
ONSET_DBFS = -40.0
FADE_OUT_SECONDS = 0.02
FADE_IN_SECONDS = 0.03
#: whisper start timestamps are coarse; a segment starting this close to the silence end is after it
ASR_START_TOLERANCE = 0.05


def window_dbfs(samples: Any, rate: int = SAMPLE_RATE, window: float = WINDOW_SECONDS) -> list[float]:
    """RMS dBFS per non-overlapping window of mono float samples."""
    n = max(1, int(round(rate * window)))
    out: list[float] = []
    for start in range(0, len(samples) - n + 1, n):
        chunk = samples[start:start + n]
        rms = math.sqrt(sum(float(v) * float(v) for v in chunk) / n)
        out.append(20.0 * math.log10(rms) if rms > 1e-9 else -180.0)
    return out


def detect(db: list[float], window: float = WINDOW_SECONDS) -> dict[str, Any] | None:
    """Leading burst + silence on a per-window dBFS envelope, or None."""
    max_burst = int(round(BURST_MAX_SECONDS / window))
    silence_n = int(round(SILENCE_MIN_SECONDS / window))
    for end in range(1, min(max_burst, len(db)) + 1):
        head = db[:end]
        if max(head) <= BURST_DBFS:
            continue
        tail = db[end:end + silence_n]
        if len(tail) < silence_n or max(tail) >= SILENCE_DBFS:
            continue
        silence_end = end + silence_n
        while silence_end < len(db) and db[silence_end] < SILENCE_DBFS:
            silence_end += 1
        onset = next((i for i in range(silence_end, len(db)) if db[i] >= ONSET_DBFS), None)
        return {"burst_end_seconds": round(end * window, 3),
                "burst_peak_dbfs": round(max(head), 1),
                "silence_end_seconds": round(silence_end * window, 3),
                "silence_max_dbfs": round(max(db[end:silence_end]), 1),
                "speech_onset_seconds": round(onset * window, 3) if onset is not None else None}
    return None


def read_pcm(path: Path, ffmpeg: str = "ffmpeg", seconds: float = 3.0) -> list[float]:
    """First ``seconds`` of the clip's first audio stream, mono 16 kHz float."""
    import array
    run = subprocess.run([ffmpeg, "-v", "error", "-i", str(path), "-map", "0:a:0", "-t", f"{seconds:g}",
                          "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "f32le", "-"],
                         capture_output=True, check=False)
    if run.returncode != 0:
        raise RuntimeError(f"PCM_READ_FAILED:{path}:{run.stderr[-200:]!r}")
    data = array.array("f")
    data.frombytes(run.stdout[:len(run.stdout) // 4 * 4])
    return list(data)


def judge(found: dict[str, Any] | None, segments: list[dict[str, Any]]) -> tuple[bool, str]:
    """(mute?, reason) for one unit's detection and its ASR segments."""
    if found is None:
        return False, "NO_LEADING_BURST"
    segs = sorted((s for s in segments or [] if str(s.get("text") or "").strip() and s.get("start") is not None),
                  key=lambda s: float(s["start"]))
    if not segs:
        return True, "MUTED_NO_LINE_IN_UNIT"
    first = segs[0]
    silence_end = float(found["silence_end_seconds"])
    if float(first["start"]) >= silence_end - ASR_START_TOLERANCE:
        return True, "MUTED_LINE_STARTS_AFTER_SILENCE"
    onset = found.get("speech_onset_seconds")
    if float(first.get("end") or 0.0) > silence_end and onset is not None:
        return True, "MUTED_ASR_START_SNAPPED_SPEECH_RESUMES_AFTER_SILENCE"
    return False, "LINE_STARTS_AT_UNIT_START"


def plan(clips: dict[str, Path], unit_asr: dict[str, Any], *, ffmpeg: str = "ffmpeg") -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for uid, clip in sorted(clips.items()):
        row: dict[str, Any] = {"unit_id": uid, "clip": str(clip), "muted": False}
        try:
            found = detect(window_dbfs(read_pcm(clip, ffmpeg)))
        except Exception as exc:  # noqa: BLE001 -- a measurement failure only leaves the unit untouched
            row["reason"] = f"MEASUREMENT_FAILED:{type(exc).__name__}"
            rows.append(row)
            continue
        mute, reason = judge(found, unit_asr.get(uid) or [])
        first = next((s for s in sorted(unit_asr.get(uid) or [], key=lambda s: float(s.get("start") or 0))
                      if str(s.get("text") or "").strip()), None)
        row.update({"muted": mute, "reason": reason, "detection": found,
                    "asr_first_segment": ({"start": first.get("start"), "end": first.get("end")} if first else None)})
        if mute:
            row["mute_source_seconds"] = [0.0, found["burst_end_seconds"]]
        rows.append(row)
    return {"schema": SCHEMA, "burst_max_seconds": BURST_MAX_SECONDS, "burst_dbfs": BURST_DBFS,
            "silence_dbfs": SILENCE_DBFS, "silence_min_seconds": SILENCE_MIN_SECONDS,
            "fade_out_seconds": FADE_OUT_SECONDS, "fade_in_seconds": FADE_IN_SECONDS,
            "muted_units": sum(1 for r in rows if r["muted"]), "units": rows}


def timeline_windows(report: dict[str, Any], project: dict[str, Any]) -> list[dict[str, Any]]:
    """Map each muted unit's source window onto the rendered native cut through its audio clip."""
    clips = {str((c.get("metadata") or {}).get("source_id")): c
             for track in (project.get("timeline") or {}).get("audioTracks") or [] for c in track.get("clips") or []}
    out = []
    for row in report.get("units") or []:
        clip = clips.get(str(row.get("unit_id")))
        if not row.get("muted") or clip is None:
            continue
        start, source_in = float(clip.get("start") or 0.0), float(clip.get("in") or 0.0)
        a = start
        b = start + float(row["mute_source_seconds"][1]) - source_in
        if b - a <= 0.0:
            continue
        out.append({"unit_id": row["unit_id"], "start_seconds": round(a, 6), "end_seconds": round(b, 6)})
    return out


def gain_expression(windows: list[dict[str, Any]], fade_out: float = FADE_OUT_SECONDS,
                    fade_in: float = FADE_IN_SECONDS) -> str:
    """ffmpeg volume expression: 0 inside each window, linear ramps of ``fade_out`` before it and
    ``fade_in`` after it (the fade-in lies in the measured silence), 1 elsewhere."""
    terms = []
    for w in windows:
        a, b = float(w["start_seconds"]), float(w["end_seconds"])
        terms.append(f"min(1,max(0,max(({a:.6f}-t)/{fade_out:g},(t-{b:.6f})/{fade_in:g})))")
    return "*".join(terms) or "1"


def mix_filter(windows: list[dict[str, Any]]) -> str:
    """-af chain for the native cut; small audio frames so ``t`` resolves the 20-30 ms ramps."""
    return (f"asetnsamples=n=64:p=0,volume='{gain_expression(windows)}':eval=frame")
