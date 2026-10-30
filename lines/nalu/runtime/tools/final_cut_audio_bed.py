#!/usr/bin/env python3
"""final_cut_audio_bed.py — whole-film ambient bed + under-score for a finished cut, free and deterministic.

Roger 2026-10-30 (E12 成片审看, item 1b): 全片环境底噪 + 音乐；任何地方不得低于 −50 dBFS 的静音；落在死寂里的
剪辑点 47 % → 0；同时保持发行响度 −14 LUFS ±1 / TP ≤ −1 dBTP、台词窗 (−18, −12) LUFS、相邻台词差 ≤ 6 LU
(tools/final_cut_audience_detectors.py: loudness / silence_gap_max).

Why the cut is silent today: MiniMax-H3 delivers each unit with a noise-gated track (between words the
signal drops to ≈ −60 dBFS or below), and the assembly butt-joins 53 such units.  E12 candidate: 17 % of
the runtime sits below −50 dBFS in 10 ms frames, 309 silent runs, and 21 of 52 internal cuts have at least
one silent 10 ms frame within ±150 ms (Roger's "47 %").  No library of ambience exists in this deployment
and paid ambience generation is not authorised, so the bed is synthesised here — deterministic noise
shaped per location class — and the music under the film is built only from the episode's own three paid
cues (no new generation).

Method (numpy/scipy mix, picture stream copied bit-exact)
  1. decode the input's audio (48 kHz stereo float32).
  2. AMBIENT BED, one class per location (contract ``scene_states[].location_id`` through the grouping
     plan's unit → scene map; the class is chosen by id substrings, see ``LOCATION_CLASSES``):
        EXT_SNOW_WIND   brown noise, 40–600 Hz, gust LFO (0.05 + 0.13 Hz, depth 0.35)  −43 dBFS RMS
        EXT_STREET      pink noise, 80–3000 Hz, light LFO (0.09 Hz, depth 0.25)         −44 dBFS RMS
        INT_HALL        pink noise, 60–1500 Hz, LFO 0.07 Hz depth 0.2 (room + murmur)   −45 dBFS RMS
        INT_SMALL_ROOM  brown noise, 40–300 Hz, no LFO (closed room tone)                −45 dBFS RMS
        DEFAULT         INT_HALL
     plus, under every class, a constant broadband pink floor at −44.5 dBFS (100–6000 Hz).  Levels: the
     −50 dBFS criterion is judged on 10 ms frames; a narrow low band swings ±8 dB between frames, the
     broadband floor only ±1.5 dB, so the floor — not the character layer — is what keeps every frame
     above −50 (measured on the bed alone: min frame ≈ −49 dBFS).  Classes change with a 1.0 s
     equal-power crossfade centred on the unit boundary; the bed runs through every cut unbroken, which is
     what removes "cut in dead silence" (a cut is no longer a step from signal into digital nothing).  The
     bed is generated with a seeded RNG (``--seed``), so the same inputs give the same bytes.
  3. MUSIC under the whole film (``--music-mode wall_to_wall``, default): outside the three paid cue
     regions a PAD is derived from the cue sources themselves — the cue that comes next on the timeline
     (foreshadowing; after the last cue, that cue) low-passed at 500 Hz and looped with 4 s equal-power
     crossfades — at −36 dBFS RMS (≈ 12 dB under the cue level the plan mixed), muted inside the cue
     regions with 1.5 s fades so the paid cue is never doubled.  ``cues_only`` skips the pad.
  4. DUCKING of the pad under speech: a peak envelope of the native mix (attack 150 ms, release 600 ms)
     drives a gain of −(env_dB − (−30 dBFS)) × 0.95, capped at −14 dB (attack/release = time to 90 % of a step).  Speech on this line peaks at
     ≈ −16 dBFS, so a spoken line ducks the pad by ≈ 13 dB (Roger's −12…−18 dB band); the ambient bed is
     NOT ducked — it is the floor that keeps every frame above −50 dBFS.
  5. SUM native + bed + pad, then ONE static programme gain (−14 − I of the mix, held back so TP stays
     ≤ −1.5 dBTP; same constants as tools/level_native_release_audio.py, detector limit −1.0) — and NO
     gain at all when the summed mix is already within ±0.5 LU of −14 with TP ≤ −1.0 (the normal case
     after the leveller), so the line windows the leveller produced are left untouched.  Not
     loudnorm: on an input already at −14.0 / −1.2 dBTP its "linear" mode cannot apply the tiny residual
     gain under the TP ceiling and silently switches to dynamic normalisation (seen on E12), which pumps and
     moves the per-line windows.  A static gain shifts every window by the same amount, nothing else.
  6. REPORT (``--report``): input/output sha256, video stream md5 equality, before/after for every target:
     silence (<−50 dBFS 10 ms frames: share, runs, seconds, longest run, digital-zero seconds), cut points
     (two definitions: mean RMS of ±150 ms < −50 dBFS, and ANY 10 ms frame < −50 dBFS within ±150 ms),
     programme loudness (ebur128 I / TP / LRA), line-window LUFS via the detector's own
     ``decide_loudness`` on the line windows CLIPPED TO THEIR UNIT'S RELEASE SPAN (E12's
     FINAL_CUT_ASR_WINDOWS carries 13 windows wholly outside and 37 partly outside their unit — built on
     pre-trim offsets — and the two WINDOW_LUFS_OUT_OF_RANGE failures at 128.6 s and 166.5 s are such
     windows measuring a gap, not a line; the clipped windows are written to ``--windows-out``).

Idempotent: refuses to overwrite ``--out`` / ``--report``; no network; nothing written outside the paths
given.  Free: no provider call.

Usage
  final_cut_audio_bed.py --input <levelled.mp4> --timeline <EP>_release_timeline.json
      --grouping <EP>_VIDEO_UNIT_GROUPING_PLAN_V1.json --contract <EP>_GENERATION_CONTRACT_v1.json
      --bgm-plan <EP>_BGM_PLAN.json --bgm-selection <EP>_BGM_SELECTION.json
      --line-windows <EP>_FINAL_CUT_ASR_WINDOWS.json --out <mp4> --report <json>
      [--windows-out <json>] [--stems-dir <dir>] [--music-mode wall_to_wall|cues_only] [--seed 12]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nalu_paths as _np  # noqa: E402
sys.path.insert(0, str(Path(f"{_np.ENGINE_ROOT}")))
from tools import dialogue_voice_metrics as dvm  # noqa: E402
from tools.final_cut_audience_detectors import DEFAULTS as DETECTOR_DEFAULTS, decide_loudness  # noqa: E402

SCHEMA = "nalu.final_cut_audio_bed.v1"
SR = 48000
FRAME_MS = 10
SILENCE_DBFS = -50.0
CUT_WINDOW_S = 0.150
RELEASE_LUFS = -14.0
LOUDNORM_TP = -1.5
RELEASE_TP_LIMIT = -1.0          # detector limit (final_cut_audience_detectors release_tp)
ON_TARGET_TOLERANCE_LU = 0.5     # programme already within this of −14 LUFS → no gain applied
BED_XFADE_S = 1.0
FLOOR_DBFS = -44.5   # broadband pink floor under every class (see shaped_noise); bed-alone min 10 ms frame ≈ −49 dBFS
PAD_LOOP_XFADE_S = 4.0
PAD_EDGE_FADE_S = 1.5
PAD_LOWPASS_HZ = 500.0
PAD_LEVEL_DBFS = -36.0
DUCK_THRESHOLD_DBFS = -30.0
DUCK_RATIO = 20.0
DUCK_MAX_DB = 14.0
DUCK_ATTACK_S = 0.150
DUCK_RELEASE_S = 0.600

# location-id substring → bed class (first match wins; checked in order)
LOCATION_CLASSES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("SNOW", "ROAD", "FOREST", "MOUNTAIN", "FIELD", "WILD"), "EXT_SNOW_WIND"),
    (("STREET", "MARKET", "TOWN", "COURTYARD", "GATE", "SQUARE"), "EXT_STREET"),
    (("ROOM", "CHAMBER", "CELL", "CABIN"), "INT_SMALL_ROOM"),
    (("BAR", "HALL", "INN", "TAVERN", "SHOP", "HOUSE", "TEMPLE"), "INT_HALL"),
)
BED_SPECS: dict[str, dict[str, Any]] = {
    "EXT_SNOW_WIND": {"noise": "brown", "band": (40.0, 600.0), "lfo": ((0.05, 0.13), 0.35), "level_dbfs": -43.0},
    "EXT_STREET": {"noise": "pink", "band": (80.0, 3000.0), "lfo": ((0.09,), 0.25), "level_dbfs": -44.0},
    "INT_HALL": {"noise": "pink", "band": (60.0, 1500.0), "lfo": ((0.07,), 0.2), "level_dbfs": -45.0},
    "INT_SMALL_ROOM": {"noise": "brown", "band": (40.0, 300.0), "lfo": ((), 0.0), "level_dbfs": -45.0},
}
DEFAULT_CLASS = "INT_HALL"


# ----------------------------------------------------------------------------- small helpers
def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def ensure_fresh_output(path: Path) -> None:
    """Idempotence guard: an existing output is evidence of an earlier run and is never overwritten."""
    if path.exists():
        raise SystemExit(f"OUTPUT_EXISTS_REFUSING_TO_OVERWRITE:{path}")


def db_to_lin(db: float) -> float:
    return 10.0 ** (db / 20.0)


def lin_to_db(x: float) -> float:
    return 20.0 * math.log10(max(float(x), 1e-12))


def run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(a) for a in argv], text=True, capture_output=True, check=False)


def decode_audio(path: Path, *, channels: int = 2, sr: int = SR) -> np.ndarray:
    """float32 array shape (n, channels)."""
    res = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", str(channels), "-ar", str(sr),
                          "-f", "f32le", "-"], capture_output=True, check=False)
    if res.returncode:
        raise RuntimeError("ffmpeg decode failed: " + res.stderr.decode("utf-8", "replace")[-2000:])
    x = np.frombuffer(res.stdout, dtype=np.float32)
    return x.reshape(-1, channels) if channels > 1 else x.reshape(-1, 1)


def video_stream_md5(path: Path) -> str:
    res = run(["ffmpeg", "-v", "error", "-i", path, "-map", "0:v:0", "-c", "copy", "-f", "md5", "-"])
    return res.stdout.strip()


# ----------------------------------------------------------------------------- pure measurement
def frame_rms_db(mono: np.ndarray, *, sr: int = SR, frame_ms: int = FRAME_MS) -> np.ndarray:
    hop = sr * frame_ms // 1000
    n = len(mono) // hop
    if n == 0:
        return np.zeros(0)
    frames = mono[: n * hop].reshape(n, hop)
    return 20.0 * np.log10(np.sqrt(np.mean(frames ** 2, axis=1)) + 1e-12)


def silence_runs(rms_db: np.ndarray, *, threshold: float = SILENCE_DBFS, frame_s: float = FRAME_MS / 1000.0) -> list[tuple[float, float]]:
    runs: list[tuple[float, float]] = []
    silent = rms_db < threshold
    i, n = 0, len(silent)
    while i < n:
        if silent[i]:
            j = i
            while j < n and silent[j]:
                j += 1
            runs.append((round(i * frame_s, 3), round(j * frame_s, 3)))
            i = j
        else:
            i += 1
    return runs


def silence_stats(mono: np.ndarray, *, sr: int = SR) -> dict[str, Any]:
    rms = frame_rms_db(mono, sr=sr)
    runs = silence_runs(rms)
    long_runs = [r for r in runs if r[1] - r[0] >= 0.05]
    return {
        "threshold_dbfs": SILENCE_DBFS, "frame_ms": FRAME_MS,
        "silent_frame_share": round(float(np.mean(rms < SILENCE_DBFS)), 4) if len(rms) else 0.0,
        "silence_runs": len(runs), "silence_runs_ge_50ms": len(long_runs),
        "silence_seconds": round(sum(b - a for a, b in runs), 3),
        "longest_run": max(runs, key=lambda r: r[1] - r[0]) if runs else None,
        "min_frame_dbfs": round(float(rms.min()), 1) if len(rms) else None,
        "digital_zero_seconds": round(int(np.sum(np.abs(mono) < 1e-6)) / sr, 3),
    }


def cut_silence_stats(mono: np.ndarray, cuts: list[float], *, sr: int = SR, window_s: float = CUT_WINDOW_S,
                      threshold: float = SILENCE_DBFS) -> dict[str, Any]:
    """Two readings per internal cut: mean RMS of [c-w, c+w] (dead when < threshold) and ANY 10 ms frame
    < threshold inside [c-w, c+w] (the stricter, perceptual reading: a gap is heard even when the mean is
    lifted by the words either side)."""
    rms = frame_rms_db(mono, sr=sr)
    fps = 1000 // FRAME_MS
    rows = []
    for c in cuts:
        a, b = max(0, int((c - window_s) * sr)), min(len(mono), int((c + window_s) * sr))
        mean_db = lin_to_db(math.sqrt(float(np.mean(mono[a:b] ** 2)))) if b > a else None
        fa, fb = max(0, int((c - window_s) * fps)), min(len(rms), int((c + window_s) * fps) + 1)
        min_frame = float(rms[fa:fb].min()) if fb > fa else None
        rows.append({"t": round(float(c), 3), "mean_rms_dbfs_pm150": None if mean_db is None else round(mean_db, 1),
                     "min_frame_dbfs_pm150": None if min_frame is None else round(min_frame, 1),
                     "dead_mean": bool(mean_db is not None and mean_db < threshold),
                     "dead_any_frame": bool(min_frame is not None and min_frame < threshold)})
    n = len(rows)
    return {"cuts": n, "window_s": window_s, "threshold_dbfs": threshold,
            "dead_mean_count": sum(r["dead_mean"] for r in rows),
            "dead_any_frame_count": sum(r["dead_any_frame"] for r in rows),
            "dead_any_frame_share": round(sum(r["dead_any_frame"] for r in rows) / n, 4) if n else 0.0,
            "rows": rows}


def clip_windows_to_units(windows: list[dict[str, Any]], segments: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Clip every line window to its unit's release span; windows wholly outside are dropped (they measure a
    different unit's audio).  Returns (windows, {kept, clipped, dropped})."""
    spans = {s["unit_id"]: (float(s["output_start"]), float(s["output_end"])) for s in segments}
    kept: list[dict[str, Any]] = []
    stats = {"kept": 0, "clipped": 0, "dropped": 0}
    for w in windows:
        span = spans.get(w.get("unit_id"))
        s, e = float(w["start"]), float(w["end"])
        if span is None:
            kept.append(dict(w)); stats["kept"] += 1
            continue
        a, b = span
        if e <= a or s >= b:
            stats["dropped"] += 1
            continue
        ns, ne = max(s, a), min(e, b)
        row = dict(w)
        if (ns, ne) != (s, e):
            row.update({"start": round(ns, 3), "end": round(ne, 3), "clipped_from": [s, e]})
            stats["clipped"] += 1
        else:
            stats["kept"] += 1
        kept.append(row)
    return kept, stats


# ----------------------------------------------------------------------------- bed planning
def classify_location(location_id: str | None) -> str:
    text = str(location_id or "").upper()
    for needles, cls in LOCATION_CLASSES:
        if any(n in text for n in needles):
            # INT/EXT sanity: an id that says EXT never gets a room class and vice versa
            if cls.startswith("INT") and "EXT" in text and "INT" not in text:
                return "EXT_STREET"
            if cls.startswith("EXT") and "INT" in text and "EXT" not in text:
                return "INT_HALL"
            return cls
    if "EXT" in text:
        return "EXT_STREET"
    return DEFAULT_CLASS


def plan_bed_classes(segments: list[dict[str, Any]], unit_scene: dict[str, str], scene_location: dict[str, str | None],
                     total_s: float) -> list[dict[str, Any]]:
    """[{start, end, class, location_id, units}] — consecutive units of the same class merged; the tail
    (end card) continues the last class."""
    plan: list[dict[str, Any]] = []
    for seg in segments:
        loc = scene_location.get(unit_scene.get(seg["unit_id"], ""), None)
        cls = classify_location(loc)
        s, e = float(seg["output_start"]), float(seg["output_end"])
        if plan and plan[-1]["class"] == cls:
            plan[-1]["end"] = e
            plan[-1]["units"].append(seg["unit_id"])
        else:
            plan.append({"start": s, "end": e, "class": cls, "location_id": loc, "units": [seg["unit_id"]]})
    if plan:
        plan[-1]["end"] = max(plan[-1]["end"], total_s)
    return plan


def _pink_fast(n: int, rng: np.random.Generator) -> np.ndarray:
    """Vectorised pink noise via the Voss-McCartney-like spectral shaping (1/f amplitude) — used for long beds."""
    white = rng.standard_normal(n)
    spec = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(n, d=1.0 / SR)
    scale = np.ones_like(freqs)
    scale[1:] = 1.0 / np.sqrt(freqs[1:])
    scale[0] = 0.0
    pink = np.fft.irfft(spec * scale, n=n)
    return pink / (np.std(pink) + 1e-12)


def _brown_fast(n: int, rng: np.random.Generator) -> np.ndarray:
    white = rng.standard_normal(n)
    spec = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(n, d=1.0 / SR)
    scale = np.zeros_like(freqs)
    scale[1:] = 1.0 / freqs[1:]
    brown = np.fft.irfft(spec * scale, n=n)
    return brown / (np.std(brown) + 1e-12)


def shaped_noise(spec: dict[str, Any], n: int, rng: np.random.Generator) -> np.ndarray:
    from scipy.signal import butter, sosfiltfilt
    base = _pink_fast(n, rng) if spec["noise"] == "pink" else _brown_fast(n, rng)
    lo, hi = spec["band"]
    sos = butter(4, [lo, min(hi, SR / 2 - 1)], btype="bandpass", fs=SR, output="sos")
    y = sosfiltfilt(sos, base)
    freqs, depth = spec["lfo"]
    if freqs and depth > 0:
        t = np.arange(n) / SR
        lfo = np.zeros(n)
        for k, f in enumerate(freqs):
            lfo += np.sin(2 * math.pi * f * t + 0.7 * k)
        lfo /= max(len(freqs), 1)
        y = y * (1.0 - depth * 0.5 * (1.0 + lfo))  # between (1-depth) and 1
    rms = math.sqrt(float(np.mean(y ** 2))) + 1e-12
    character = y / rms * db_to_lin(spec["level_dbfs"])
    # Broadband floor under the character layer: a narrow low band (wind, room rumble) swings ±8 dB
    # between 10 ms frames and the gust LFO adds up to −6 dB, so the character layer alone dips under
    # −50 dBFS in single frames.  A constant pink floor at FLOOR_DBFS (100–6000 Hz, frame variance
    # ≈ ±1.5 dB) is what guarantees the "no frame below −50 dBFS" criterion.
    floor = _pink_fast(n, np.random.default_rng(int(rng.integers(0, 2**31 - 1))))
    sos_f = butter(2, [100.0, 6000.0], btype="bandpass", fs=SR, output="sos")
    floor = sosfiltfilt(sos_f, floor)
    floor = floor / (math.sqrt(float(np.mean(floor ** 2))) + 1e-12) * db_to_lin(FLOOR_DBFS)
    return (character + floor).astype(np.float32)


def equal_power_ramp(n: int) -> tuple[np.ndarray, np.ndarray]:
    t = np.linspace(0.0, 1.0, n, endpoint=False)
    return np.cos(t * math.pi / 2), np.sin(t * math.pi / 2)


def render_bed(plan: list[dict[str, Any]], total_n: int, rng_seed: int) -> np.ndarray:
    """Stereo bed (n, 2): per class one long deterministic texture, crossfaded at class boundaries."""
    classes = sorted({row["class"] for row in plan})
    textures: dict[str, np.ndarray] = {}
    for i, cls in enumerate(classes):
        rng = np.random.default_rng(rng_seed * 1000 + i)
        left = shaped_noise(BED_SPECS[cls], total_n, rng)
        rng2 = np.random.default_rng(rng_seed * 1000 + i + 500)
        right = shaped_noise(BED_SPECS[cls], total_n, rng2)
        # mostly correlated image: 70 % shared, 30 % independent per side
        shared = 0.7 * left + 0.3 * right
        textures[cls] = np.stack([0.85 * shared + 0.15 * left, 0.85 * shared + 0.15 * right], axis=1)
    bed = np.zeros((total_n, 2), dtype=np.float32)
    half = int(BED_XFADE_S * SR / 2)
    for idx, row in enumerate(plan):
        s, e = int(row["start"] * SR), min(int(row["end"] * SR), total_n)
        bed[s:e] = textures[row["class"]][s:e]
    for prev, nxt in zip(plan, plan[1:]):
        if prev["class"] == nxt["class"]:
            continue
        c = int(nxt["start"] * SR)
        a, b = max(0, c - half), min(total_n, c + half)
        if b <= a:
            continue
        down, up = equal_power_ramp(b - a)
        bed[a:b] = (textures[prev["class"]][a:b] * down[:, None] + textures[nxt["class"]][a:b] * up[:, None])
    return bed


# ----------------------------------------------------------------------------- music pad
def plan_pad_regions(cues: list[dict[str, Any]], content_end: float, total_s: float) -> list[dict[str, Any]]:
    """Gaps between cue regions on the timeline, each with the source key of the NEXT cue (foreshadow);
    the region after the last cue uses the last cue and runs to the end of the file (end card fades out)."""
    cues_sorted = sorted(cues, key=lambda c: float(c["timeline_start"]))
    regions: list[dict[str, Any]] = []
    cursor = 0.0
    for cue in cues_sorted:
        s = float(cue["timeline_start"]); e = s + float(cue["duration"])
        if s - cursor > PAD_EDGE_FADE_S * 2:
            regions.append({"start": cursor, "end": s, "source_key": cue["source_key"], "after_cue": None, "before_cue": cue["cue_id"]})
        cursor = max(cursor, e)
    if cues_sorted and total_s - cursor > PAD_EDGE_FADE_S * 2:
        last = cues_sorted[-1]
        regions.append({"start": cursor, "end": total_s, "source_key": last["source_key"], "after_cue": last["cue_id"], "before_cue": None})
    return regions


def loop_to_length(x: np.ndarray, n: int) -> np.ndarray:
    """Loop a stereo signal to n samples with equal-power crossfades of PAD_LOOP_XFADE_S."""
    if len(x) >= n:
        return x[:n]
    xf = int(PAD_LOOP_XFADE_S * SR)
    out = np.zeros((n, x.shape[1]), dtype=np.float32)
    pos = 0
    first = True
    while pos < n:
        seg = x if first else x
        take = min(len(seg), n - pos)
        if first:
            out[pos:pos + take] = seg[:take]
            pos += take
            first = False
        else:
            start = pos - xf
            m = min(xf, len(seg), n - start)
            down, up = equal_power_ramp(m)
            out[start:start + m] = out[start:start + m] * down[:, None] + seg[:m] * up[:, None]
            rest = min(len(seg) - m, n - (start + m))
            if rest > 0:
                out[start + m:start + m + rest] = seg[m:m + rest]
            pos = start + m + max(rest, 0)
            if rest <= 0:
                break
    return out


def make_pad_source(cue_audio: np.ndarray) -> np.ndarray:
    from scipy.signal import butter, sosfiltfilt
    sos = butter(4, PAD_LOWPASS_HZ, btype="lowpass", fs=SR, output="sos")
    y = sosfiltfilt(sos, cue_audio.astype(np.float64), axis=0)
    rms = math.sqrt(float(np.mean(y ** 2))) + 1e-12
    return (y / rms * db_to_lin(PAD_LEVEL_DBFS)).astype(np.float32)


def render_pad(regions: list[dict[str, Any]], sources: dict[str, np.ndarray], total_n: int, content_end: float) -> np.ndarray:
    pad = np.zeros((total_n, 2), dtype=np.float32)
    fade_n = int(PAD_EDGE_FADE_S * SR)
    for region in regions:
        s, e = int(region["start"] * SR), min(int(region["end"] * SR), total_n)
        if e - s <= 2 * fade_n:
            continue
        chunk = loop_to_length(sources[region["source_key"]], e - s).copy()
        ramp_in = np.sin(np.linspace(0, math.pi / 2, fade_n))
        chunk[:fade_n] *= ramp_in[:, None]
        tail_fade = fade_n
        if region["before_cue"] is None:
            # the last region: fade out over the end card (content_end → total)
            tail_fade = max(fade_n, min(e - s, e - int(content_end * SR)))
        ramp_out = np.cos(np.linspace(0, math.pi / 2, tail_fade))
        chunk[-tail_fade:] *= ramp_out[:, None]
        pad[s:e] = chunk
    return pad


# ----------------------------------------------------------------------------- ducking
def envelope_db(mono: np.ndarray, *, sr: int = SR, attack_s: float = DUCK_ATTACK_S, release_s: float = DUCK_RELEASE_S,
                hop_ms: int = 5) -> tuple[np.ndarray, int]:
    """Peak envelope in dBFS at hop resolution (one-pole attack/release on block peaks)."""
    hop = sr * hop_ms // 1000
    n = len(mono) // hop
    peaks = np.max(np.abs(mono[: n * hop].reshape(n, hop)), axis=1)
    # attack/release are stated as the time to cover 90 % of a step (what a mixer reads on a compressor),
    # so the one-pole time constant is t / ln(10)
    a_att = math.exp(-hop * math.log(10.0) / (attack_s * sr))
    a_rel = math.exp(-hop * math.log(10.0) / (release_s * sr))
    env = np.empty(n)
    cur = 0.0
    for i in range(n):
        p = peaks[i]
        cur = a_att * cur + (1 - a_att) * p if p > cur else a_rel * cur + (1 - a_rel) * p
        env[i] = cur
    return 20.0 * np.log10(env + 1e-9), hop


def duck_gain_db(env_db: np.ndarray, *, threshold_db: float = DUCK_THRESHOLD_DBFS, ratio: float = DUCK_RATIO,
                 max_db: float = DUCK_MAX_DB) -> np.ndarray:
    over = np.maximum(env_db - threshold_db, 0.0)
    return -np.minimum(over * (1.0 - 1.0 / ratio), max_db)


def apply_gain_curve(x: np.ndarray, gain_db: np.ndarray, hop: int) -> np.ndarray:
    g = db_to_lin(0.0) * np.power(10.0, gain_db / 20.0)
    per_sample = np.repeat(g, hop)
    if len(per_sample) < len(x):
        per_sample = np.concatenate([per_sample, np.full(len(x) - len(per_sample), per_sample[-1] if len(per_sample) else 1.0)])
    return (x * per_sample[: len(x), None]).astype(np.float32)


# ----------------------------------------------------------------------------- loudnorm + mux
def write_wav(path: Path, audio: np.ndarray) -> None:
    import wave
    data = np.clip(audio, -1.0, 1.0)
    pcm = (data * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(audio.shape[1]); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def write_wav_f32(path: Path, audio: np.ndarray) -> None:
    res = subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", str(audio.shape[1]), "-i", "-",
                          "-c:a", "pcm_f32le", str(path)], input=audio.astype(np.float32).tobytes(), capture_output=True, check=False)
    if res.returncode:
        raise RuntimeError("wav write failed: " + res.stderr.decode("utf-8", "replace")[-1000:])


def static_program_gain_render(mix_wav: Path, video: Path, out: Path) -> dict[str, Any]:
    """One static programme gain (no dynamics): gain = −14 − I_mix, reduced so that TP stays ≤ LOUDNORM_TP.
    Why not loudnorm: the levelled input already sits at −14.0 LUFS / −1.2 dBTP, so loudnorm's linear mode
    cannot apply even a +0.05 dB gain without breaching TP=−1.5 and silently falls back to its DYNAMIC
    normaliser (observed on E12: second pass reported normalization_type=dynamic) — which pumps and alters the
    per-line window band the leveller produced.  A static gain keeps every window at exactly (its level +
    gain), which is what makes the before/after window table comparable."""
    measured = dvm.measure_program_loudness(mix_wav)
    i_in = float(measured["integrated_lufs"]); tp_in = float(measured["true_peak_dbtp"])
    gain = RELEASE_LUFS - i_in
    limited_by_tp = False
    already_on_target = abs(gain) <= ON_TARGET_TOLERANCE_LU and tp_in <= RELEASE_TP_LIMIT
    if already_on_target:
        # the leveller already put the programme on target; a residual ±0.3 dB would only move every
        # line window (and the bed floor) for nothing — leave the mix exactly as summed
        gain = 0.0
    elif tp_in + gain > LOUDNORM_TP:
        gain = LOUDNORM_TP - tp_in
        limited_by_tp = True
    render = run(["ffmpeg", "-hide_banner", "-nostats", "-y", "-i", video, "-i", mix_wav, "-map", "0:v:0", "-map", "1:a:0",
                  "-c:v", "copy", "-af", f"volume={gain:.3f}dB", "-ar", str(SR), "-c:a", "aac", "-b:a", "192k",
                  "-movflags", "+faststart", out])
    if render.returncode or not out.is_file():
        raise RuntimeError("render failed: " + render.stderr[-2000:])
    return {"mode": "STATIC_PROGRAM_GAIN", "mix_integrated_lufs": i_in, "mix_true_peak_dbtp": tp_in,
            "gain_db": round(gain, 3), "gain_limited_by_true_peak": limited_by_tp, "already_on_target": already_on_target, "target_lufs": RELEASE_LUFS, "tp_ceiling_dbtp": LOUDNORM_TP}


# ----------------------------------------------------------------------------- measurement bundle
def measure_release(media: Path, cuts: list[float], windows: list[dict[str, Any]], *, with_window_lufs: bool = True) -> dict[str, Any]:
    stereo = decode_audio(media)
    mono = stereo.mean(axis=1).astype(np.float32)
    program = dvm.measure_program_loudness(media)
    rows = []
    if with_window_lufs:
        for w in windows:
            rows.append({"start": float(w["start"]), "end": float(w["end"]),
                         "lufs_window": dvm.measure_window_lufs(media, float(w["start"]), float(w["end"]))})
    loud = decide_loudness(program["integrated_lufs"], program["true_peak_dbtp"], rows,
                           release_lufs=DETECTOR_DEFAULTS["release_lufs"], tolerance=DETECTOR_DEFAULTS["release_lufs_tolerance"],
                           release_tp=DETECTOR_DEFAULTS["release_tp"], window_range=DETECTOR_DEFAULTS["window_lufs_range"],
                           adjacent_delta_max=DETECTOR_DEFAULTS["adjacent_delta_max_lu"])
    cut_stats = cut_silence_stats(mono, cuts)
    return {"sha256": sha256_file(media), "duration_s": round(len(mono) / SR, 3), "program_loudness": program,
            "silence": silence_stats(mono), "cuts": {k: v for k, v in cut_stats.items() if k != "rows"},
            "cut_rows": cut_stats["rows"], "line_windows": {"count": len(rows), "lufs": rows},
            "loudness_detector": {"status": loud["status"], "measured": loud.get("measured"), "failures": loud.get("failures", [])}}


# ----------------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--input", required=True, type=Path, help="levelled final candidate (mp4)")
    ap.add_argument("--timeline", required=True, type=Path)
    ap.add_argument("--grouping", required=True, type=Path, help="<EP>_VIDEO_UNIT_GROUPING_PLAN_V1.json (unit → scene)")
    ap.add_argument("--contract", required=True, type=Path, help="generation contract (scene_states[].location_id)")
    ap.add_argument("--bgm-plan", type=Path, help="<EP>_BGM_PLAN.json (cue regions; wall_to_wall pad avoids them)")
    ap.add_argument("--bgm-selection", type=Path, help="<EP>_BGM_SELECTION.json (selected cue sources for the pad)")
    ap.add_argument("--line-windows", type=Path, help="<EP>_FINAL_CUT_ASR_WINDOWS.json")
    ap.add_argument("--windows-out", type=Path, help="write the unit-clipped line windows here")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--report", required=True, type=Path)
    ap.add_argument("--stems-dir", type=Path, help="also write bed.wav / pad.wav / native.wav (provenance)")
    ap.add_argument("--music-mode", choices=["wall_to_wall", "cues_only"], default="wall_to_wall")
    ap.add_argument("--seed", type=int, default=12)
    ap.add_argument("--no-window-lufs", action="store_true")
    a = ap.parse_args(argv)

    ensure_fresh_output(a.out); ensure_fresh_output(a.report)
    if a.windows_out:
        ensure_fresh_output(a.windows_out)
    timeline = read_json(a.timeline); segments = timeline["segments"]
    grouping = read_json(a.grouping); contract = read_json(a.contract)
    unit_scene = {u["unit_id"]: u.get("scene_id") for u in grouping.get("units", [])}
    scene_location = {s.get("scene_id"): s.get("location_id") for s in contract.get("scene_states", []) if isinstance(s, dict)}
    cuts = [float(s["output_start"]) for s in segments[1:]]
    content_end = float(timeline.get("content_runtime_seconds") or segments[-1]["output_end"])

    native = decode_audio(a.input)
    total_n = len(native); total_s = total_n / SR
    windows_in = read_json(a.line_windows) if a.line_windows else []
    windows, window_stats = clip_windows_to_units(windows_in, segments)
    if a.windows_out:
        a.windows_out.parent.mkdir(parents=True, exist_ok=True)
        a.windows_out.write_text(json.dumps(windows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    before = measure_release(a.input, cuts, windows, with_window_lufs=not a.no_window_lufs)

    bed_plan = plan_bed_classes(segments, unit_scene, scene_location, total_s)
    bed = render_bed(bed_plan, total_n, a.seed)

    pad = np.zeros_like(native)
    pad_regions: list[dict[str, Any]] = []
    pad_sources: dict[str, str] = {}
    if a.music_mode == "wall_to_wall":
        if not (a.bgm_plan and a.bgm_selection):
            raise SystemExit("wall_to_wall needs --bgm-plan and --bgm-selection (the pad is built from the paid cues only)")
        plan = read_json(a.bgm_plan); selection = read_json(a.bgm_selection)
        pad_regions = plan_pad_regions(plan.get("cues", []), content_end, total_s)
        sources: dict[str, np.ndarray] = {}
        for key in {r["source_key"] for r in pad_regions}:
            src = Path(selection["sources"][key]["selected"])
            pad_sources[key] = str(src)
            sources[key] = make_pad_source(decode_audio(src))
        pad = render_pad(pad_regions, sources, total_n, content_end)
        env_db, hop = envelope_db(native.mean(axis=1))
        pad = apply_gain_curve(pad, duck_gain_db(env_db), hop)
        duck_applied = {"threshold_dbfs": DUCK_THRESHOLD_DBFS, "ratio": DUCK_RATIO, "max_db": DUCK_MAX_DB,
                        "attack_s": DUCK_ATTACK_S, "release_s": DUCK_RELEASE_S,
                        "median_duck_db_in_speech": round(float(np.median(duck_gain_db(env_db)[env_db > -24])), 2) if np.any(env_db > -24) else None}
    else:
        duck_applied = None

    mix = (native.astype(np.float32) + bed + pad).astype(np.float32)

    with tempfile.TemporaryDirectory(prefix="audio_bed_") as tmp:
        mix_wav = Path(tmp) / "mix.wav"
        write_wav_f32(mix_wav, mix)
        a.out.parent.mkdir(parents=True, exist_ok=True)
        loudnorm = static_program_gain_render(mix_wav, a.input, a.out)
        if a.stems_dir:
            a.stems_dir.mkdir(parents=True, exist_ok=True)
            write_wav_f32(a.stems_dir / "bed.wav", bed)
            write_wav_f32(a.stems_dir / "pad_ducked.wav", pad)

    if video_stream_md5(a.input) != video_stream_md5(a.out):
        a.out.unlink(missing_ok=True)
        raise SystemExit("VIDEO_STREAM_CHANGED")

    after = measure_release(a.out, cuts, windows, with_window_lufs=not a.no_window_lufs)
    bed_mono = bed.mean(axis=1)
    report = {
        "schema": SCHEMA, "recorded_at": now(), "tool": Path(__file__).name,
        "input": {"path": str(a.input), "sha256": before["sha256"]},
        "output": {"path": str(a.out), "sha256": after["sha256"], "video_stream_bit_exact": True},
        "params": {"seed": a.seed, "music_mode": a.music_mode, "bed_specs": BED_SPECS, "bed_xfade_s": BED_XFADE_S,
                   "pad_level_dbfs": PAD_LEVEL_DBFS, "pad_lowpass_hz": PAD_LOWPASS_HZ, "pad_edge_fade_s": PAD_EDGE_FADE_S,
                   "pad_loop_xfade_s": PAD_LOOP_XFADE_S, "duck": duck_applied, "loudnorm": {"I": RELEASE_LUFS, "TP": LOUDNORM_TP, **loudnorm}},
        "bed_plan": bed_plan, "bed_rms_dbfs": round(lin_to_db(math.sqrt(float(np.mean(bed_mono ** 2)))), 2),
        "bed_min_frame_dbfs": round(float(frame_rms_db(bed_mono).min()), 2),
        "pad_regions": pad_regions, "pad_sources": pad_sources,
        "line_windows": {"source": str(a.line_windows) if a.line_windows else None, **window_stats, "written_to": str(a.windows_out) if a.windows_out else None},
        "before": {k: v for k, v in before.items() if k != "cut_rows"},
        "after": {k: v for k, v in after.items() if k != "cut_rows"},
        "cut_rows_after": after["cut_rows"],
        "targets": {
            "no_silence_below_-50dBFS": after["silence"]["silence_runs"] == 0,
            "cut_points_in_dead_silence_zero": after["cuts"]["dead_any_frame_count"] == 0,
            "release_loudness_pass": after["loudness_detector"]["status"] == "PASS",
        },
    }
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(a.out), "report": str(a.report), "targets": report["targets"],
                      "silence_runs": [before["silence"]["silence_runs"], after["silence"]["silence_runs"]],
                      "cuts_dead_any_frame": [before["cuts"]["dead_any_frame_count"], after["cuts"]["dead_any_frame_count"]],
                      "integrated_lufs": [before["program_loudness"]["integrated_lufs"], after["program_loudness"]["integrated_lufs"]],
                      "true_peak": [before["program_loudness"]["true_peak_dbtp"], after["program_loudness"]["true_peak_dbtp"]],
                      "loudness_detector": [before["loudness_detector"]["status"], after["loudness_detector"]["status"]]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
