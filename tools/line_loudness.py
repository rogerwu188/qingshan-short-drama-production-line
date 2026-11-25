#!/usr/bin/env python3
"""Per-line dialogue loudness on the finished mix (S7; device 1101 E27 deep review 2026-11-25, LOUDNESS_JUMP).

E27 shipped with consecutive lines up to 6 LU apart (-21.2 -> -15.1 -> -21.2 LUFS) although every unit had been
levelled line by line on its own clip: the later S7 steps (V.O., BGM, release levelling, the bed) and the clip-level
measurement left the lines as heard in the final mix spread over ~9 LU.  This module measures each line window ON
THE MIX and pulls the outliers to the episode's median line loudness:

* loudness: ITU-R BS.1770 K-weighting + 400 ms / 75 % blocks, absolute gate -70 LUFS, relative gate -10 LU
  (a line shorter than one block is measured on its whole span);
* plan: a line within ``TOLERANCE_LU`` of the median keeps its level; any other line goes to the median, the gain
  clamped to +-``MAX_GAIN_DB``; a line quieter than ``QUIET_FLOOR_LUFS`` is no speech and is left alone;
* apply: the gain holds over the line window and ramps (raised cosine, ``RAMP_S``) back to unity outside it, so the
  gaps between lines -- the room tone and the music level -- are not moved.

Pure numpy / scipy; ``NALU_S7_LINE_LOUDNESS=off`` disables it in the callers.
"""
from __future__ import annotations

import math
import os
from typing import Any

import numpy as np

ENV_SWITCH = "NALU_S7_LINE_LOUDNESS"
TOLERANCE_LU = 1.0
MAX_GAIN_DB = 8.0
QUIET_FLOOR_LUFS = -45.0
RAMP_S = 0.06
MIN_LINE_S = 0.25
BLOCK_S = 0.4
OVERLAP = 0.75


def enabled(environ: dict[str, str] | None = None) -> bool:
    raw = str((os.environ if environ is None else environ).get(ENV_SWITCH) or "").strip().lower()
    return raw not in ("0", "off", "false", "no")


def _k_filter_sos(sr: int) -> np.ndarray:
    """BS.1770 K-weighting (shelving pre-filter + RLB high-pass) as second-order sections for ``sr``."""
    # pre-filter (Annex 1, derived for any sample rate)
    f0, g, q = 1681.974450955533, 3.999843853973347, 0.7071752369554196
    k = math.tan(math.pi * f0 / sr)
    vh = 10 ** (g / 20.0)
    vb = vh ** 0.4996667741545416
    a0 = 1.0 + k / q + k * k
    b_pre = [(vh + vb * k / q + k * k) / a0, 2.0 * (k * k - vh) / a0, (vh - vb * k / q + k * k) / a0]
    a_pre = [1.0, 2.0 * (k * k - 1.0) / a0, (1.0 - k / q + k * k) / a0]
    f0, q = 38.13547087602444, 0.5003270373238773
    k = math.tan(math.pi * f0 / sr)
    a0 = 1.0 + k / q + k * k
    b_rlb = [1.0, -2.0, 1.0]
    a_rlb = [1.0, 2.0 * (k * k - 1.0) / a0, (1.0 - k / q + k * k) / a0]
    return np.array([b_pre + a_pre, b_rlb + a_rlb], dtype=np.float64)


def k_weight(audio: np.ndarray, sr: int) -> np.ndarray:
    from scipy.signal import sosfilt
    x = np.asarray(audio, dtype=np.float64)
    return sosfilt(_k_filter_sos(sr), x, axis=0)


def gated_loudness(weighted: np.ndarray, sr: int) -> float:
    """Integrated loudness (LUFS) of already K-weighted samples ([n] or [n, ch]); -inf when silent."""
    x = weighted if weighted.ndim == 2 else weighted[:, None]
    n = len(x)
    if n == 0:
        return float("-inf")
    block, hop = int(BLOCK_S * sr), max(1, int(BLOCK_S * (1 - OVERLAP) * sr))
    if n < block:
        power = float(np.sum(np.mean(x ** 2, axis=0)))
        return -0.691 + 10.0 * math.log10(power) if power > 0 else float("-inf")
    powers = np.array([float(np.sum(np.mean(x[i:i + block] ** 2, axis=0))) for i in range(0, n - block + 1, hop)])
    with np.errstate(divide="ignore"):
        lk = -0.691 + 10.0 * np.log10(np.maximum(powers, 1e-20))
    kept = powers[lk > -70.0]
    if not len(kept):
        return float("-inf")
    rel = -0.691 + 10.0 * math.log10(float(np.mean(kept))) - 10.0
    kept = powers[(lk > -70.0) & (lk > rel)]
    if not len(kept):
        return float("-inf")
    return -0.691 + 10.0 * math.log10(float(np.mean(kept)))


def measure_lines(audio: np.ndarray, sr: int, windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """[{start, end, lufs}] for every window at least MIN_LINE_S long (sorted by start)."""
    weighted = k_weight(audio, sr)
    rows = []
    for w in sorted(windows or [], key=lambda r: float(r["start"])):
        a, b = float(w["start"]), float(w["end"])
        if b - a < MIN_LINE_S:
            continue
        i0, i1 = max(0, int(round(a * sr))), min(len(weighted), int(round(b * sr)))
        if i1 - i0 <= 0:
            continue
        rows.append({"start": round(a, 3), "end": round(b, 3), "lufs": round(gated_loudness(weighted[i0:i1], sr), 2),
                     **({"unit_id": w.get("unit_id")} if w.get("unit_id") else {})})
    return rows


def plan_gains(rows: list[dict[str, Any]], *, tolerance_lu: float = TOLERANCE_LU,
               max_gain_db: float = MAX_GAIN_DB) -> dict[str, Any]:
    """Each line's gain toward the median line loudness (outliers only, clamped)."""
    levels = sorted(r["lufs"] for r in rows if math.isfinite(r["lufs"]) and r["lufs"] >= QUIET_FLOOR_LUFS)
    if not levels:
        return {"target_lufs": None, "lines": [dict(r, gain_db=0.0) for r in rows]}
    target = levels[len(levels) // 2] if len(levels) % 2 else (levels[len(levels) // 2 - 1] + levels[len(levels) // 2]) / 2
    out = []
    for r in rows:
        gain = 0.0
        if math.isfinite(r["lufs"]) and r["lufs"] >= QUIET_FLOOR_LUFS and abs(target - r["lufs"]) > tolerance_lu:
            gain = max(-max_gain_db, min(max_gain_db, target - r["lufs"]))
        out.append(dict(r, gain_db=round(gain, 2), predicted_lufs=round(r["lufs"] + gain, 2)
                        if math.isfinite(r["lufs"]) else r["lufs"]))
    return {"target_lufs": round(target, 2), "tolerance_lu": tolerance_lu, "max_gain_db": max_gain_db, "lines": out}


def gain_curve(n: int, sr: int, lines: list[dict[str, Any]], ramp_s: float = RAMP_S) -> np.ndarray:
    """Linear gain per sample: each line's gain over its window, raised-cosine ramps of ``ramp_s`` outside it back
    to unity (a ramp never crosses the midpoint to the neighbouring line)."""
    curve_db = np.zeros(n, dtype=np.float64)
    rows = sorted((r for r in lines if abs(float(r.get("gain_db") or 0.0)) > 1e-6), key=lambda r: r["start"])
    all_rows = sorted(lines, key=lambda r: r["start"])
    for r in rows:
        idx = all_rows.index(r)
        prev_end = all_rows[idx - 1]["end"] if idx > 0 else None
        next_start = all_rows[idx + 1]["start"] if idx + 1 < len(all_rows) else None
        a, b, g = float(r["start"]), float(r["end"]), float(r["gain_db"])
        up = min(ramp_s, (a - prev_end) / 2.0) if prev_end is not None else ramp_s
        down = min(ramp_s, (next_start - b) / 2.0) if next_start is not None else ramp_s
        up, down = max(up, 0.0), max(down, 0.0)
        i_a, i_b = int(round(a * sr)), int(round(b * sr))
        curve_db[max(0, i_a):min(n, i_b)] = g
        if up > 0:
            i0 = max(0, int(round((a - up) * sr)))
            end = min(i_a, n)
            if end - i0 > 0:
                ramp = 0.5 - 0.5 * np.cos(np.linspace(0, math.pi, i_a - i0, endpoint=False))
                curve_db[i0:end] = g * ramp[: end - i0]
        if down > 0:
            i1 = min(n, int(round((b + down) * sr)))
            m = i1 - i_b
            if m > 0 and i_b >= 0:
                ramp = 0.5 + 0.5 * np.cos(np.linspace(0, math.pi, m, endpoint=False))
                curve_db[i_b:i1] = g * ramp
    return np.power(10.0, curve_db / 20.0)


def level_lines(audio: np.ndarray, sr: int, windows: list[dict[str, Any]]) -> tuple[np.ndarray, dict[str, Any]]:
    """(levelled audio, report).  The report carries before/after per line and the spread."""
    rows = measure_lines(audio, sr, windows)
    planned = plan_gains(rows)
    if not any(abs(r["gain_db"]) > 1e-6 for r in planned["lines"]):
        return audio, {**planned, "status": "UNCHANGED", "applied_lines": 0, "spread_lu": _spread(rows)}
    curve = gain_curve(len(audio), sr, planned["lines"])
    out = (audio * (curve[:, None] if audio.ndim == 2 else curve)).astype(np.float32)
    after = measure_lines(out, sr, windows)
    return out, {**planned, "status": "APPLIED",
                 "applied_lines": sum(1 for r in planned["lines"] if abs(r["gain_db"]) > 1e-6),
                 "spread_lu": {"before": _spread(rows), "after": _spread(after)},
                 "after": after}


def _spread(rows: list[dict[str, Any]]) -> dict[str, float] | None:
    vals = [r["lufs"] for r in rows if math.isfinite(r["lufs"]) and r["lufs"] >= QUIET_FLOOR_LUFS]
    if not vals:
        return None
    jumps = [abs(b - a) for a, b in zip(vals, vals[1:])]
    return {"min": round(min(vals), 2), "max": round(max(vals), 2), "range": round(max(vals) - min(vals), 2),
            "max_adjacent_jump": round(max(jumps), 2) if jumps else 0.0}
