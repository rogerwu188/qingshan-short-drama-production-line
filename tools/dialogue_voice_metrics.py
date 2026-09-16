#!/usr/bin/env python3
"""Per-line voice metrics for a rendered episode: F0 median, RMS, duration, window LUFS.

The nalu line has no TTS stage and no dialogue stem: dialogue is voiced natively by the
video model inside a single mixed track.  The only place character/voice binding can be
measured is therefore the final cut, line by line.  This module turns ASR speech windows
into numbers that ``tools/voice_cast_gate.py`` compares against ``voice_cast.json``.

Pure functions (``estimate_f0_median``, ``rms_dbfs``, ``measure_segments``) accept numpy
arrays so tests can use synthetic tones; ffmpeg / soundfile / faster-whisper are imported
lazily and only by the media-facing helpers.

Method (no new dependencies):
  * audio is extracted with ffmpeg to a 48 kHz mono float temp wav and read via soundfile;
  * F0 per line = median over voiced 40 ms frames (10 ms hop) of the normalised
    autocorrelation peak lag inside 70-450 Hz; a frame is voiced when its energy is above a
    fraction of the window's loudest frame and the autocorrelation peak is clear;
  * fewer than three voiced frames -> ``None`` (never a fabricated number);
  * RMS in dBFS over the whole window; optional integrated LUFS per window via
    ``ffmpeg -af ebur128``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Sequence

SCHEMA = "qingshan.dialogue_voice_metrics.v1"

DEFAULT_SAMPLE_RATE = 48000
FRAME_MS = 40.0
HOP_MS = 10.0
F0_MIN_HZ = 70.0
F0_MAX_HZ = 450.0
MIN_VOICED_FRAMES = 3
VOICED_ENERGY_RATIO = 0.25       # frame RMS relative to the loudest frame in the window
VOICED_ABS_FLOOR = 1e-4          # absolute RMS floor (about -80 dBFS)
VOICED_AUTOCORR_MIN = 0.5        # normalised autocorrelation peak needed to call a frame voiced
SUBHARMONIC_GUARD = 0.9          # prefer the shortest lag whose peak is >= this * best peak
MIN_LUFS_WINDOW_SECONDS = 0.4    # ebur128 integrated needs at least one 400 ms block


# --------------------------------------------------------------------------- pure numerics

def _np():
    import numpy as np  # local import keeps module importable without numpy at import time

    return np


def rms_dbfs(samples: Sequence[float]) -> float | None:
    """RMS of a float PCM window in dBFS (1.0 full scale). ``None`` for an empty/silent window."""
    np = _np()
    x = np.asarray(samples, dtype=np.float64)
    if x.size == 0:
        return None
    rms = float(np.sqrt(np.mean(x * x)))
    if rms <= 0.0:
        return None
    return round(20.0 * math.log10(rms), 3)


def _frame_f0(frame, sr: int, lag_min: int, lag_max: int) -> tuple[float | None, float]:
    """Return (f0_hz or None, normalised autocorrelation peak) for one frame."""
    np = _np()
    x = frame - float(np.mean(frame))
    n = x.size
    window = np.hanning(n)
    x = x * window
    size = 1
    while size < 2 * n:
        size *= 2
    spectrum = np.fft.rfft(x, size)
    ac = np.fft.irfft(spectrum * np.conj(spectrum), size)[:n]
    if ac[0] <= 0.0:
        return None, 0.0
    ac = ac / ac[0]
    hi = min(lag_max, n - 2)
    if hi <= lag_min + 1:
        return None, 0.0
    region = ac[lag_min:hi + 1]
    # local maxima only, so we never sit on the flank of the zero-lag peak
    interior = region[1:-1]
    is_peak = (interior > region[:-2]) & (interior >= region[2:])
    peak_idx = np.nonzero(is_peak)[0] + 1
    if peak_idx.size == 0:
        return None, float(region.max())
    peak_vals = region[peak_idx]
    best = float(peak_vals.max())
    if best < VOICED_AUTOCORR_MIN:
        return None, best
    # shortest lag among peaks comparable to the best one guards against octave-down errors
    candidates = peak_idx[peak_vals >= SUBHARMONIC_GUARD * best]
    lag = int(candidates.min()) + lag_min
    # parabolic interpolation around the chosen lag
    if 1 <= lag < n - 1:
        y0, y1, y2 = float(ac[lag - 1]), float(ac[lag]), float(ac[lag + 1])
        denom = (y0 - 2.0 * y1 + y2)
        if denom != 0.0:
            lag = lag + 0.5 * (y0 - y2) / denom
    if lag <= 0:
        return None, best
    return float(sr) / float(lag), best


def estimate_f0_median(
    samples: Sequence[float],
    sr: int,
    *,
    frame_ms: float = FRAME_MS,
    hop_ms: float = HOP_MS,
    fmin: float = F0_MIN_HZ,
    fmax: float = F0_MAX_HZ,
    min_voiced_frames: int = MIN_VOICED_FRAMES,
) -> float | None:
    """Median F0 (Hz) over voiced frames of ``samples``; ``None`` when fewer than
    ``min_voiced_frames`` frames are voiced."""
    np = _np()
    x = np.asarray(samples, dtype=np.float64)
    frame_len = int(round(sr * frame_ms / 1000.0))
    hop = max(1, int(round(sr * hop_ms / 1000.0)))
    if x.size < frame_len or frame_len < 8:
        return None
    lag_min = max(2, int(math.floor(sr / fmax)))
    lag_max = int(math.ceil(sr / fmin))
    starts = range(0, x.size - frame_len + 1, hop)
    frames = [x[s:s + frame_len] for s in starts]
    energies = np.array([float(np.sqrt(np.mean(f * f))) for f in frames])
    if energies.size == 0 or float(energies.max()) <= VOICED_ABS_FLOOR:
        return None
    threshold = max(VOICED_ABS_FLOOR, VOICED_ENERGY_RATIO * float(energies.max()))
    voiced: list[float] = []
    for frame, energy in zip(frames, energies):
        if energy < threshold:
            continue
        f0, _peak = _frame_f0(frame, sr, lag_min, lag_max)
        if f0 is None or not (fmin <= f0 <= fmax):
            continue
        voiced.append(f0)
    if len(voiced) < min_voiced_frames:
        return None
    return round(float(np.median(np.array(voiced))), 2)


def measure_segments(samples: Sequence[float], sr: int, segments: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pure per-segment metrics from an in-memory mono signal. Copies ``speaker``/``emotion``/``scene``
    through untouched; never copies ``text``."""
    np = _np()
    x = np.asarray(samples, dtype=np.float64)
    rows: list[dict[str, Any]] = []
    for seg in segments:
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", start))
        a = max(0, int(round(start * sr)))
        b = min(x.size, int(round(end * sr)))
        window = x[a:b] if b > a else x[0:0]
        row: dict[str, Any] = {
            "start": round(start, 3),
            "end": round(end, 3),
            "duration_s": round(max(0.0, end - start), 3),
            "f0_median_hz": estimate_f0_median(window, sr) if window.size else None,
            "rms_dbfs": rms_dbfs(window),
        }
        for key in ("speaker", "emotion", "scene", "index"):
            if key in seg:
                row[key] = seg[key]
        rows.append(row)
    return rows


# --------------------------------------------------------------------------- media helpers

def _ffmpeg(binary: str | None = None) -> str:
    found = binary or shutil.which("ffmpeg")
    if not found:
        raise RuntimeError("ffmpeg not found on PATH")
    return found


def media_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_mono_wav(media: Path, out_wav: Path, *, sr: int = DEFAULT_SAMPLE_RATE, ffmpeg: str | None = None) -> Path:
    command = [
        _ffmpeg(ffmpeg), "-hide_banner", "-nostats", "-loglevel", "error", "-y",
        "-i", str(media), "-map", "0:a:0", "-vn", "-ac", "1", "-ar", str(sr),
        "-c:a", "pcm_f32le", str(out_wav),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(f"ffmpeg audio extraction failed: {result.stderr[-2000:]}")
    return out_wav


def load_audio(media: Path, *, sr: int = DEFAULT_SAMPLE_RATE, ffmpeg: str | None = None):
    """Return (float64 mono numpy array, sample_rate) for any ffmpeg-readable media."""
    import soundfile as sf

    with tempfile.TemporaryDirectory(prefix="qingshan_dvm_") as tmp:
        wav = extract_mono_wav(Path(media), Path(tmp) / "audio.wav", sr=sr, ffmpeg=ffmpeg)
        data, rate = sf.read(str(wav), dtype="float64", always_2d=False)
    np = _np()
    data = np.asarray(data)
    if data.ndim > 1:
        data = data.mean(axis=1)
    return data, int(rate)


_EBUR_I = re.compile(r"I:\s*(-?[0-9.]+|nan|-inf)\s*LUFS", re.IGNORECASE)
_EBUR_TP = re.compile(r"True peak:\s*\n\s*Peak:\s*(-?[0-9.]+|nan|-inf)\s*dBFS", re.IGNORECASE)
_EBUR_LRA = re.compile(r"LRA:\s*([0-9.]+|nan)\s*LU", re.IGNORECASE)


def _parse_float(token: str) -> float | None:
    try:
        value = float(token)
    except ValueError:
        return None
    if math.isnan(value) or math.isinf(value):
        return None
    return value


def measure_window_lufs(media: Path, start: float, end: float, *, ffmpeg: str | None = None) -> float | None:
    """Integrated LUFS of ``[start, end)`` via ``ffmpeg -ss <start> -t <end-start> -i <media> -af ebur128``.
    ``None`` when the window is shorter than one 400 ms block or ffmpeg reports no level."""
    duration = float(end) - float(start)
    if duration < MIN_LUFS_WINDOW_SECONDS:
        return None
    command = [
        _ffmpeg(ffmpeg), "-hide_banner", "-nostats",
        "-ss", f"{float(start):.6f}", "-t", f"{duration:.6f}",
        "-i", str(media), "-map", "0:a:0", "-af", "ebur128", "-f", "null", "-",
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        return None
    hits = _EBUR_I.findall(result.stderr)
    if not hits:
        return None
    value = _parse_float(hits[-1])
    if value is None or value <= -60.0:
        return None
    return round(value, 2)


def measure_program_loudness(media: Path, *, ffmpeg: str | None = None) -> dict[str, float | None]:
    """Whole-programme EBU R128: integrated LUFS, true peak dBTP, LRA."""
    command = [
        _ffmpeg(ffmpeg), "-hide_banner", "-nostats", "-i", str(media),
        "-map", "0:a:0", "-af", "ebur128=peak=true", "-f", "null", "-",
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(f"ffmpeg ebur128 failed: {result.stderr[-2000:]}")
    integrated = _EBUR_I.findall(result.stderr)
    peak = _EBUR_TP.findall(result.stderr)
    lra = _EBUR_LRA.findall(result.stderr)
    return {
        "integrated_lufs": _parse_float(integrated[-1]) if integrated else None,
        "true_peak_dbtp": _parse_float(peak[-1]) if peak else None,
        "loudness_range_lu": _parse_float(lra[-1]) if lra else None,
    }


def probe_duration(media: Path, *, ffprobe: str | None = None) -> float | None:
    binary = ffprobe or shutil.which("ffprobe")
    if not binary:
        return None
    result = subprocess.run(
        [binary, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(media)],
        capture_output=True, text=True, check=False,
    )
    try:
        return round(float(result.stdout.strip()), 3)
    except ValueError:
        return None


def transcribe_segments(media: Path, model: str = "small", *, language: str = "zh") -> list[dict[str, Any]]:
    """faster-whisper speech windows: [{start, end, text, no_speech_prob}]. Callers that write
    evidence to disk must drop ``text`` unless they are explicitly allowed to keep it."""
    from faster_whisper import WhisperModel  # lazy: optional dependency

    engine = WhisperModel(model, device="cpu", compute_type="int8")
    segments, _info = engine.transcribe(str(media), language=language, vad_filter=True, beam_size=1)
    rows: list[dict[str, Any]] = []
    for seg in segments:
        rows.append({
            "start": round(float(seg.start), 3),
            "end": round(float(seg.end), 3),
            "text": str(seg.text or "").strip(),
            "no_speech_prob": round(float(getattr(seg, "no_speech_prob", 0.0) or 0.0), 4),
        })
    return rows


def strip_text(segments: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: v for k, v in seg.items() if k != "text"} for seg in segments]


def measure_media(
    media: Path,
    segments: Sequence[dict[str, Any]],
    *,
    with_lufs: bool = True,
    ffmpeg: str | None = None,
) -> list[dict[str, Any]]:
    """F0 / RMS / duration (+ window LUFS) for every ASR window of ``media``."""
    samples, sr = load_audio(media, ffmpeg=ffmpeg)
    rows = measure_segments(samples, sr, segments)
    for row in rows:
        row["lufs_window"] = (
            measure_window_lufs(media, row["start"], row["end"], ffmpeg=ffmpeg) if with_lufs else None
        )
    return rows


# --------------------------------------------------------------------------- CLI

def _load_segments(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("segments") or []
    if not isinstance(payload, list):
        raise SystemExit("segments json must be a list or {\"segments\": [...]}")
    return [seg for seg in payload if isinstance(seg, dict)]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Per-line F0 / RMS / LUFS metrics for a rendered episode.")
    parser.add_argument("--media", required=True, type=Path)
    parser.add_argument("--segments-json", type=Path, help="ASR windows [{start,end,speaker?}]; omit with --transcribe")
    parser.add_argument("--transcribe", action="store_true", help="run faster-whisper when --segments-json is absent")
    parser.add_argument("--model", default="small")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--no-lufs", action="store_true", help="skip per-window ebur128 (faster)")
    parser.add_argument("--keep-asr-text", action="store_true", help="write transcribed text into --out (off by default)")
    args = parser.parse_args(argv)

    if args.segments_json:
        segments = _load_segments(args.segments_json)
        source = "segments_json"
    elif args.transcribe:
        segments = transcribe_segments(args.media, model=args.model)
        source = f"faster_whisper:{args.model}"
    else:
        raise SystemExit("either --segments-json or --transcribe is required")

    rows = measure_media(args.media, segments, with_lufs=not args.no_lufs)
    if args.keep_asr_text:
        for row, seg in zip(rows, segments):
            if "text" in seg:
                row["text"] = seg["text"]
    payload = {
        "schema": SCHEMA,
        "media": args.media.name,
        "media_sha256": media_sha256(args.media),
        "duration_s": probe_duration(args.media),
        "segments_source": source,
        "method": {
            "f0": "numpy autocorrelation, 40 ms frames / 10 ms hop, voiced 70-450 Hz, median of voiced frames",
            "rms": "RMS dBFS of the ASR window",
            "lufs_window": None if args.no_lufs else "ffmpeg ebur128 integrated per window (>=0.4 s)",
        },
        "segments": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"segments": len(rows), "out": str(args.out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
