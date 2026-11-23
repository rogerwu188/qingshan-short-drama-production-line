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

S7 (device 1101 E24, 2026-11-23) no longer depends on the S6 record: :func:`plan` measures the clip actually placed in
the AgentCut timeline with a VAD (silero from faster-whisper, else a speech-band energy VAD), mutes every speech
window of a unit with no on-screen scripted line; ``NALU_S7_SILENT_UNIT_AUDIO`` = speech_only (default) | ambience
(the whole unit also plays with the speech band removed) | off.

The S6 runner calls :func:`assess`; the S7 caller runs the ffmpeg mix with :func:`ambience_filter_complex`.
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


# ------------------------------------------------------------------------------------------------ S7 (placed clip)
#: device 1101 E24 (2026-11-23): voices in five silent shots (27.0 / 35.2 / 44.4 / 49.5 / 54.9 s) shipped although
#: S6 had recorded nothing -- whisper-small + VAD dropped the low-confidence murmur, and the old S7 mute needed an S6
#: real-speech segment AND the QA record's sha to equal the clip on disk.  S7 now measures the clip it actually
#: placed in the timeline (AgentCut audio clip source, in-point, duration) with a VAD of its own and mutes every VAD
#: speech window of a unit with no scripted on-screen line (default ``speech_only``: the full band, foley included,
#: plays elsewhere).  ``ambience`` also replaces the whole unit by its speech band removed version
#: (``AMBIENCE_LOWPASS_HZ`` / ``AMBIENCE_HIGHPASS_HZ``).
SILENT_AUDIO_ENV = "NALU_S7_SILENT_UNIT_AUDIO"
SILENT_AUDIO_MODES = ("speech_only", "ambience", "off")  # speech windows muted / + speech band removed / untouched
VAD_THRESHOLD = 0.35          # silero speech probability; below the whisper VAD default 0.5 so a murmur is caught
VAD_MIN_SPEECH_SECONDS = 0.15
VAD_MIN_SILENCE_SECONDS = 0.1
VAD_PAD_SECONDS = 0.03
FLAG_SPEECH_SECONDS = 0.3     # one VAD run this long in a silent unit is a flagged stray voice
AMBIENCE_LOWPASS_HZ = 180.0
AMBIENCE_HIGHPASS_HZ = 5500.0
ENERGY_FRAME_SECONDS = 0.02
ENERGY_BAND_HZ = (300.0, 3400.0)
ENERGY_MERGE_GAP_SECONDS = 0.2   # the gaps between syllables of one murmur
ENERGY_OVER_FLOOR_DB = 12.0
ENERGY_MIN_DBFS = -50.0
ENERGY_BAND_RATIO = 0.2   # a voice keeps much of its energy in the fundamental (< 300 Hz)
SAMPLE_RATE = 16000


def silent_audio_mode(environ: dict[str, str] | None = None) -> str:
    import os
    raw = str((os.environ if environ is None else environ).get(SILENT_AUDIO_ENV) or "").strip().lower()
    return raw if raw in SILENT_AUDIO_MODES else "speech_only"


def _runs(flags: Any, hop: float, *, min_run: float, max_gap: float) -> list[list[float]]:
    """Boolean frames -> [start, end] seconds runs (gaps <= max_gap filled, runs < min_run dropped)."""
    spans: list[list[float]] = []
    start = None
    for i, on in enumerate(list(flags) + [False]):
        if on and start is None:
            start = i
        elif not on and start is not None:
            spans.append([start * hop, i * hop])
            start = None
    merged: list[list[float]] = []
    for a, b in spans:
        if merged and a - merged[-1][1] <= max_gap:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    return [[round(a, 3), round(b, 3)] for a, b in merged if b - a >= min_run - 1e-9]


def energy_vad(samples: Any, sr: int = SAMPLE_RATE) -> list[list[float]]:
    """Speech-band energy VAD (no model): a 20 ms frame is voiced when its 300-3400 Hz energy is at least
    ``ENERGY_OVER_FLOOR_DB`` over the clip's own floor (20th percentile), above ``ENERGY_MIN_DBFS``, and holds at least
    ``ENERGY_BAND_RATIO`` of the frame's energy.  Seconds from the first sample."""
    import numpy as np
    x = np.asarray(samples, dtype=np.float64).reshape(-1)
    n = max(1, int(round(sr * ENERGY_FRAME_SECONDS)))
    frames = len(x) // n
    if frames == 0:
        return []
    blocks = x[: frames * n].reshape(frames, n) * np.hanning(n)
    power = np.abs(np.fft.rfft(blocks, axis=1)) ** 2
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    band = (freqs >= ENERGY_BAND_HZ[0]) & (freqs <= ENERGY_BAND_HZ[1])
    band_e = power[:, band].sum(axis=1) + 1e-20
    total_e = power.sum(axis=1) + 1e-20
    # band energy in dBFS of an equivalent full-scale sine through the same window
    ref = (np.hanning(n).sum() / 2.0) ** 2 * 2
    band_db = 10 * np.log10(band_e / ref)
    floor = float(np.percentile(band_db, 20))
    voiced = (band_db >= max(floor + ENERGY_OVER_FLOOR_DB, ENERGY_MIN_DBFS)) & (band_e / total_e >= ENERGY_BAND_RATIO)
    return _runs(voiced, ENERGY_FRAME_SECONDS, min_run=VAD_MIN_SPEECH_SECONDS, max_gap=ENERGY_MERGE_GAP_SECONDS)


def silero_vad(samples: Any, sr: int = SAMPLE_RATE) -> list[list[float]] | None:
    """The silero VAD that ships with faster-whisper (offline onnx), tuned for a murmur; None when unavailable."""
    try:
        import numpy as np
        from faster_whisper.vad import VadOptions, get_speech_timestamps  # type: ignore
    except Exception:  # noqa: BLE001 -- the energy VAD stands in
        return None
    opts = VadOptions(threshold=VAD_THRESHOLD, min_speech_duration_ms=int(VAD_MIN_SPEECH_SECONDS * 1000),
                      min_silence_duration_ms=int(VAD_MIN_SILENCE_SECONDS * 1000),
                      speech_pad_ms=int(VAD_PAD_SECONDS * 1000))
    rows = get_speech_timestamps(np.asarray(samples, dtype=np.float32).reshape(-1), opts, sampling_rate=sr)
    return [[round(r["start"] / sr, 3), round(r["end"] / sr, 3)] for r in rows if r["end"] > r["start"]]


def decode_mono(path: Any, start: float, duration: float, *, ffmpeg: str = "ffmpeg", sr: int = SAMPLE_RATE) -> Any:
    import subprocess
    import numpy as np
    run = subprocess.run([ffmpeg, "-v", "error", "-ss", f"{max(0.0, float(start)):.6f}", "-t", f"{float(duration):.6f}",
                          "-i", str(path), "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                         capture_output=True, check=False)
    if run.returncode != 0:
        raise RuntimeError((run.stderr or b"")[-300:].decode("utf-8", "replace"))
    return np.frombuffer(run.stdout, dtype=np.float32)


def measure_placed(path: Any, source_in: float, duration: float, *, ffmpeg: str = "ffmpeg") -> dict[str, Any]:
    """VAD speech windows of the placed part of one clip, in SOURCE seconds."""
    samples = decode_mono(path, source_in, duration, ffmpeg=ffmpeg)
    windows = silero_vad(samples)
    method = "SILERO_VAD"
    if windows is None:
        windows, method = energy_vad(samples), "SPEECH_BAND_ENERGY"
    return {"method": method, "windows": [[round(float(source_in) + a, 3), round(float(source_in) + b, 3)]
                                          for a, b in windows]}


def plan(project: dict[str, Any], measure_fn: Callable[[str, float, float], dict[str, Any]], *,
         speaking_units: set[str] | None = None, mode: str | None = None) -> dict[str, Any]:
    """One row per placed audio clip of the AgentCut project.  A unit is silent when the clip's own
    ``dialogue_classification`` is NON_SPEAKING with no expected text and (when given) it is not one of
    ``speaking_units`` (on-screen scripted lines, from the performance cut / contract).  Each silent clip is measured where it is placed (``measure_fn(source, in,
    duration)`` -> {method, windows: [[a, b] source seconds]}); dialogue units are never touched (the performance cut
    owns their unscripted speech).  Timeline outputs: ``ambience_windows`` (native replaced by ambience only) and
    ``mute_windows`` (VAD speech inside a silent unit, muted outright)."""
    mode = mode or silent_audio_mode()
    rows: list[dict[str, Any]] = []
    ambience: list[dict[str, Any]] = []
    mutes: list[dict[str, Any]] = []
    for track in (project.get("timeline") or {}).get("audioTracks") or []:
        for clip in track.get("clips") or []:
            meta = clip.get("metadata") or {}
            uid = str(meta.get("source_id") or "")
            # both signals must agree: the clip's own classification (contract lines bound by the build) and,
            # when known, the units with an on-screen scripted line -- an unreadable contract never silences a line
            silent = str(meta.get("dialogue_classification") or "") == "NON_SPEAKING" \
                and not str(meta.get("expected_text") or "").strip() \
                and (speaking_units is None or uid not in speaking_units)
            start, source_in = float(clip.get("start") or 0.0), float(clip.get("in") or 0.0)
            length = float(clip.get("duration") or 0.0)
            row: dict[str, Any] = {"unit_id": uid, "clip": str(clip.get("source") or ""), "silent": silent,
                                   "timeline": [round(start, 6), round(start + length, 6)], "source_in": source_in,
                                   "muted": False, "ambience_only": False}
            if not silent or mode == "off" or length <= 0:
                rows.append({**row, "reason": "UNIT_HAS_DIALOGUE" if not silent else
                             ("MODE_OFF" if mode == "off" else "EMPTY_CLIP")})
                continue
            try:
                measured = measure_fn(str(clip.get("source") or ""), source_in, length)
            except Exception as exc:  # noqa: BLE001 -- unmeasured: the ambience replacement still applies
                measured = {"method": f"FAILED:{type(exc).__name__}", "windows": []}
            windows = []
            for a, b in measured.get("windows") or []:
                lo, hi = max(float(a), source_in), min(float(b), source_in + length)
                if hi - lo > 0:
                    windows.append([round(lo, 3), round(hi, 3)])
            speech = round(sum(b - a for a, b in windows), 3)
            flagged = any(b - a >= FLAG_SPEECH_SECONDS - 1e-9 for a, b in windows)
            replace = mode == "ambience"   # speech_only: the speech windows are muted, the full band stays
            row.update(vad_method=measured.get("method"), vad_source_windows=windows, speech_seconds=speech,
                       flagged=flagged, ambience_only=replace, muted=bool(windows),
                       reason=("STRAY_SPEECH_MUTED_AMBIENCE_ONLY" if windows and replace else
                               "STRAY_SPEECH_MUTED" if windows else
                               "AMBIENCE_ONLY" if replace else "NO_SPEECH"))
            if replace:
                ambience.append({"unit_id": uid, "start_seconds": round(start, 6),
                                 "end_seconds": round(start + length, 6)})
            for a, b in windows:
                mutes.append({"unit_id": uid, "start_seconds": round(start + a - source_in, 6),
                              "end_seconds": round(start + b - source_in, 6)})
            rows.append(row)
    return {"schema": SCHEMA, "mode": mode, "vad_threshold": VAD_THRESHOLD,
            "flag_speech_seconds": FLAG_SPEECH_SECONDS, "ambience_band_removed_hz": [AMBIENCE_LOWPASS_HZ,
                                                                                    AMBIENCE_HIGHPASS_HZ],
            "fade_out_seconds": FADE_OUT_SECONDS, "fade_in_seconds": FADE_IN_SECONDS,
            "muted_units": sum(1 for r in rows if r["muted"]), "flagged_units": sum(1 for r in rows if r.get("flagged")),
            "ambience_units": sum(1 for r in rows if r["ambience_only"]),
            "ambience_windows": sorted(ambience, key=lambda w: w["start_seconds"]),
            "mute_windows": sorted(mutes, key=lambda w: w["start_seconds"]), "units": rows}


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


def ambience_filter_complex(mute_windows: list[dict[str, Any]], ambience_windows: list[dict[str, Any]]) -> str:
    """filter_complex for the native cut (input 0) -> ``[aout]``: inside each ambience window the native audio is
    replaced by its speech band removed version (low-pass ``AMBIENCE_LOWPASS_HZ`` + high-pass
    ``AMBIENCE_HIGHPASS_HZ``, 30 ms ramps at the unit edges) and every mute window is silent; elsewhere unchanged."""
    native = gain_expression(ambience_windows)
    amb = f"(1-({native}))*({gain_expression(mute_windows)})" if ambience_windows else "0"
    if not ambience_windows:
        native = gain_expression(mute_windows)
    return ("[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,asetnsamples=n=64:p=0,"
            "asplit=3[nat][lo][hi];"
            f"[lo]lowpass=f={AMBIENCE_LOWPASS_HZ:g},lowpass=f={AMBIENCE_LOWPASS_HZ:g}[lo2];"
            f"[hi]highpass=f={AMBIENCE_HIGHPASS_HZ:g},highpass=f={AMBIENCE_HIGHPASS_HZ:g}[hi2];"
            "[lo2][hi2]amix=inputs=2:normalize=0:duration=first[amb];"
            f"[nat]volume='{native}':eval=frame[natv];"
            f"[amb]volume='{amb}':eval=frame[ambv];"
            "[natv][ambv]amix=inputs=2:normalize=0:duration=first[aout]")
