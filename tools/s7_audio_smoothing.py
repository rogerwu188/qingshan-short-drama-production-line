#!/usr/bin/env python3
"""S7 sound smoothing for CAMERA_GRAMMAR_V1 episodes (line owner 2026-10-27, lab Holmes E07).

Owner, watching lab E07: "background music is sometimes not continuous between shots, and the sound goes
louder/quieter".  Measured causes and the three free fixes in this module (stamped episodes only; every other
episode keeps the previous S7 path byte-for-byte):

1. BGM ducking pumped.  A -8 dB duck with 0.25 s ramps toggled on and off at almost every short line, so the bed
   swung -25..-46 dB second to second.  ``smooth_duck_expr``: dialogue windows closer than ``DUCK_MERGE_GAP_S``
   merge into one duck, raised-cosine ramps (``DUCK_ATTACK_S`` down, ``DUCK_RELEASE_S`` up) and a lighter duck
   (``STAMPED_DUCK_DB``, -6 dB: the shallow edge of the bgm_authenticity_gate -6..-10 dB contract).
2. Per-unit native loudness jumped at cuts (every H3 clip carries its own room tone / dialogue level); one gain
   per unit still left whole lines ~6 dB hot (device 1101 E24), so dialogue units are matched LINE by line
   (``LINE_TARGET_LUFS`` -16 +- ``LINE_TOLERANCE_LU``, clamp +-``MAX_LINE_GAIN_DB``).
   ``build_levelling_report``: before the AgentCut build each unit's integrated loudness is measured (dialogue
   units on their ASR speech windows, other units over the whole cut window) and a static gain toward the
   release role target (native_audio_loudness_contract.ROLE_TARGETS_LUFS) is applied, clamped to
   +-``MAX_UNIT_GAIN_DB``, followed by an oversampled peak limiter.  Picture untouched, duration unchanged: the
   levelled unit is a remux (video stream copied bit-exact, the unit's own audio levelled) that the AgentCut picture
   and sound clips both point at (same in/out).  Report ``<EP>_UNIT_AUDIO_LEVELLING.json``.  The release leveller then stages no second per-unit gain
   (``level_native_release_audio --pre-levelled-units``).
3. Hard audio cuts.  ``crossfade_plan``: an equal-power crossfade of ``CUT_CROSSFADE_S`` at every cut, built
   from the clips' own handles (the outgoing sound runs on, the incoming sound starts early) so the timeline and
   lip sync do not move.  A cut without handles (most H3 clips are used whole) fades through instead: a short
   equal-power fade-out / fade-in on each side (``FADE_THROUGH_HALF_S``), so ambience changes do not click; the
   BGM bed is mixed later and runs on.  Authored sound bridges (L-cuts) keep their hard cut and their own mix.

Nothing here blocks S7: a failure skips the step (recorded) and the cut keeps its previous sound.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Callable
try:
    from ffmpeg_caps import alimiter_latency as _alimiter_latency
except ImportError:  # pragma: no cover - imported as tools.<module>
    from tools.ffmpeg_caps import alimiter_latency as _alimiter_latency

SCHEMA = "nalu.unit_audio_levelling.v1"

# --- 1. BGM ducking ------------------------------------------------------------------------------------------
DUCK_MERGE_GAP_S = 2.5
DUCK_ATTACK_S = 0.4
DUCK_RELEASE_S = 1.2
#: device 1101 E24 (2026-11-23): at -10 dB (owner 2026-11-19) the music vanished under every line and surfaced only in
#: the gaps; the duck is -6 dB again, now with merged windows and slow raised-cosine ramps so it no longer toggles
#: per line (lines/nalu/runtime/tools/bgm_cue_shaping.DUCK_DB; bgm_authenticity_gate accepts -6..-10)
STAMPED_DUCK_DB = -6.0

# --- 2. per-unit levelling -----------------------------------------------------------------------------------
#: device 1101 E24 (2026-11-23): Lingyao / Meng lines ~6 dB over their neighbours (unit medians -9.8 / -9.6 / -10.9
#: LUFS vs -15.5) after a +-6 dB unit clamp; the clamp is +-9 dB and dialogue is matched LINE by line
MAX_UNIT_GAIN_DB = 9.0
#: per-line match: every spoken line (an ASR row of a dialogue unit) to LINE_TARGET_LUFS; a line already within
#: LINE_TOLERANCE_LU keeps its level; gains clamped to +-MAX_LINE_GAIN_DB; LINE_RAMP_S ramps between lines
LINE_TARGET_LUFS = -16.0
LINE_TOLERANCE_LU = 1.5
MAX_LINE_GAIN_DB = 9.0
MIN_LINE_SECONDS = 0.4
LINE_RAMP_S = 0.08
LINE_QUIET_FLOOR_LUFS = -45.0
UNIT_TRUE_PEAK_CEILING_DBTP = -1.5
MIN_SPEECH_SECONDS = 0.5
UNCHANGED_BELOW_DB = 0.25

# --- 3. cut crossfades ---------------------------------------------------------------------------------------
CUT_CROSSFADE_S = 0.08
#: a crossfade needs real handles; with less than this much material beyond the cut the cut fades through instead
MIN_CROSSFADE_S = 0.04
#: fade-through (no handles: H3 clips are mostly used whole): the outgoing sound fades out over its last
#: FADE_THROUGH_HALF_S and the incoming one fades in over its first FADE_THROUGH_HALF_S (equal-power curves)
FADE_THROUGH_HALF_S = 0.03
CROSSFADE_CURVE = "qsin"  # acrossfade c1=c2=qsin: equal power


# ============================================================================================================
# 1. BGM ducking
# ============================================================================================================
def merge_windows(windows: list[dict[str, Any]], gap: float = DUCK_MERGE_GAP_S) -> list[tuple[float, float]]:
    """Dialogue windows [{start, end}] -> sorted (start, end) with every pair closer than ``gap`` merged."""
    spans = sorted((float(w["start"]), float(w["end"])) for w in windows or [] if float(w["end"]) > float(w["start"]))
    merged: list[list[float]] = []
    for start, end in spans:
        if merged and start - merged[-1][1] < gap:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(round(a, 3), round(b, 3)) for a, b in merged]


def duck_shape(cue_windows: list[dict[str, Any]]) -> dict[str, Any]:
    """The stamped duck shape recorded on a BGM plan cue (release-timeline seconds)."""
    return {"policy": "CAMERA_GRAMMAR_V1_SMOOTH_DUCK", "merge_gap_s": DUCK_MERGE_GAP_S,
            "attack_s": DUCK_ATTACK_S, "release_s": DUCK_RELEASE_S, "curve": "raised_cosine",
            "windows": [{"start": a, "end": b} for a, b in merge_windows(cue_windows)]}


def smooth_duck_expr(cue: dict[str, Any]) -> str:
    """ffmpeg volume expression (t relative to the cue): 1 outside the merged duck windows, 10^(duck/20) inside,
    raised-cosine ramps that reach the full duck at the window start and leave it over ``release_s``."""
    shape = cue["duck_shape"]
    lin = 10 ** (float(cue["dialogue_duck_db"]) / 20.0)
    attack, release = float(shape["attack_s"]), float(shape["release_s"])
    t0 = float(cue["timeline_start"])
    parts = []
    for w in shape["windows"]:
        s, e = float(w["start"]) - t0, float(w["end"]) - t0
        x = f"min(clip((t-({s - attack:.3f}))/{attack:g},0,1),clip(({e + release:.3f}-t)/{release:g},0,1))"
        parts.append(f"(0.5-0.5*cos(PI*{x}))")
    if not parts:
        return "1"
    env = parts[0]
    for part in parts[1:]:
        env = f"max({env},{part})"
    return f"1-(1-{lin:.4f})*{env}"


# ============================================================================================================
# 2. per-unit levelling
# ============================================================================================================
def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def speech_windows(rows: list[dict[str, Any]] | None, cut: tuple[float, float]) -> list[tuple[float, float]]:
    """Unit ASR rows (seconds from the cut's in-point) -> source-time speech spans inside the cut window."""
    t_in, t_out = cut
    out = []
    for row in rows or []:
        a, b = t_in + float(row["start"]), t_in + float(row["end"])
        a, b = max(a, t_in), min(b, t_out)
        if b - a > 0.05:
            out.append((round(a, 3), round(b, 3)))
    return out


def line_spans(spans: list[tuple[float, float]], min_seconds: float = MIN_LINE_SECONDS) -> list[tuple[float, float]]:
    """Speech spans -> measurable lines: a span shorter than ``min_seconds`` joins its nearest neighbour."""
    lines = [list(s) for s in sorted(spans)]
    changed = True
    while changed and len(lines) > 1:
        changed = False
        for i, (a, b) in enumerate(lines):
            if b - a >= min_seconds:
                continue
            j = i - 1 if i == len(lines) - 1 or (i > 0 and a - lines[i - 1][1] <= lines[i + 1][0] - b) else i + 1
            lo, hi = min(i, j), max(i, j)
            lines[lo] = [min(lines[lo][0], lines[hi][0]), max(lines[lo][1], lines[hi][1])]
            del lines[hi]
            changed = True
            break
    return [(round(a, 3), round(b, 3)) for a, b in lines]


def plan_line_gain(measured_lufs: float, target_lufs: float = LINE_TARGET_LUFS,
                   tolerance_lu: float = LINE_TOLERANCE_LU, max_gain_db: float = MAX_LINE_GAIN_DB) -> dict[str, Any]:
    """One line's gain: 0 inside target +- tolerance, else to the target, clamped."""
    desired = float(target_lufs) - float(measured_lufs)
    # a "line" this quiet is no speech (ASR phantom / gated out): never pump the room tone up
    wanted = 0.0 if abs(desired) <= tolerance_lu or float(measured_lufs) < LINE_QUIET_FLOOR_LUFS else desired
    gain = max(-max_gain_db, min(max_gain_db, wanted))
    return {"measured_lufs": round(float(measured_lufs), 3), "desired_gain_db": round(desired, 3),
            "gain_db": round(gain, 3), "clamped": abs(gain - wanted) > 1e-6,
            "predicted_lufs": round(float(measured_lufs) + gain, 3)}


def line_gain_expression(lines: list[dict[str, Any]], ramp: float = LINE_RAMP_S) -> str:
    """ffmpeg volume expression (t = source seconds of the unit clip): each line's gain from the midpoint after the
    previous line to the midpoint before the next one, linear ``ramp`` between; the first / last line's gain holds
    before / after.  Gains in dB, applied as amplitude."""
    rows = sorted(lines, key=lambda r: r["span"][0])
    if not rows:
        return "1"
    terms = [f"{float(rows[0]['gain_db']):.3f}"]
    for prev, nxt in zip(rows, rows[1:]):
        step = float(nxt["gain_db"]) - float(prev["gain_db"])
        if abs(step) < 1e-6:
            continue
        mid = (float(prev["span"][1]) + float(nxt["span"][0])) / 2.0
        half = min(ramp, max(1e-3, float(nxt["span"][0]) - float(prev["span"][1]))) / 2.0
        terms.append(f"({step:.3f})*clip((t-{mid - half:.4f})/{2 * half:.4f},0,1)")
    return f"pow(10,({'+'.join(terms)})/20)"


def plan_gain(measured_lufs: float, target_lufs: float, max_gain_db: float = MAX_UNIT_GAIN_DB) -> dict[str, Any]:
    desired = float(target_lufs) - float(measured_lufs)
    gain = max(-max_gain_db, min(max_gain_db, desired))
    return {"desired_gain_db": round(desired, 3), "gain_db": round(gain, 3),
            "clamped": abs(gain - desired) > 1e-6,
            "predicted_lufs": round(float(measured_lufs) + gain, 3)}


_I_RE = re.compile(r"Integrated loudness:\s*\n\s*I:\s*(-?[0-9.]+) LUFS")
_TP_RE = re.compile(r"True peak:\s*\n\s*Peak:\s*(-?inf|-?[0-9.]+) dBFS", re.IGNORECASE)


def measure_spans(path: Path, spans: list[tuple[float, float]], *, ffmpeg: str = "ffmpeg") -> dict[str, float]:
    """EBU R128 integrated loudness + true peak of the concatenated source spans of one file."""
    if not spans:
        raise ValueError("no spans to measure")
    chains = [f"[0:a:0]atrim=start={a:.6f}:end={b:.6f},asetpts=PTS-STARTPTS,aresample=48000,"
              f"aformat=sample_fmts=fltp:channel_layouts=stereo[s{i}]" for i, (a, b) in enumerate(spans)]
    joined = "".join(f"[s{i}]" for i in range(len(spans)))
    graph = ";".join(chains + [f"{joined}concat=n={len(spans)}:v=0:a=1,ebur128=peak=true[m]"])
    run = subprocess.run([ffmpeg, "-hide_banner", "-nostats", "-i", str(path), "-filter_complex", graph,
                          "-map", "[m]", "-f", "null", "-"], capture_output=True, text=True, check=False)
    if run.returncode:
        raise RuntimeError(run.stderr[-1500:])
    integrated, peak = _I_RE.findall(run.stderr), _TP_RE.findall(run.stderr)
    if not integrated or not peak:
        raise RuntimeError(f"could not parse EBU R128 metrics for {path}")
    tp = peak[-1]
    return {"integrated_loudness_lufs": float(integrated[-1]),
            "true_peak_dbtp": -120.0 if tp.lower().endswith("inf") else float(tp)}


def render_levelled(source: Path, picture: Path, out: Path, gain_db: float | str, *, ffmpeg: str = "ffmpeg",
                    ceiling_dbtp: float = UNIT_TRUE_PEAK_CEILING_DBTP) -> dict[str, Any]:
    """Remux: ``picture``'s video stream copied bit-exact + ``source``'s whole audio stream with a static gain and a
    4x-oversampled peak limiter (48 kHz PCM, .mov).  ``gain_db`` may be a per-line volume expression
    (:func:`line_gain_expression`, amplitude, evaluated per 256-sample frame).  One file carries the unit's picture and sound, as the speaking
    unit audio contract requires (audio_postproduction_contract SPEAKING_AUDIO_VIDEO_SOURCE_MISMATCH)."""
    limit = 10 ** (ceiling_dbtp / 20.0)
    volume = (f"asetnsamples=n=256:p=0,volume='{gain_db}':eval=frame" if isinstance(gain_db, str)
              else f"volume={float(gain_db):.3f}dB")
    chain = (f"aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,{volume},"
             f"aresample=192000,alimiter=limit={limit:.6f}:attack=5:release=50:level=false{_alimiter_latency(ffmpeg)},aresample=48000")
    out.parent.mkdir(parents=True, exist_ok=True)
    run = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(picture), "-i", str(source),
                          "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-af", chain,
                          "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(out)],
                         capture_output=True, text=True, check=False)
    if run.returncode or not out.is_file():
        raise RuntimeError(run.stderr[-1500:])
    return {"filter": chain}


def build_levelling_report(
    episode: str, clips: dict[str, Path], windows: dict[str, tuple[float, float]], roles: dict[str, str],
    unit_asr: dict[str, Any] | None, targets: dict[str, float], out_dir: Path, *,
    measure_fn: Callable[[Path, list[tuple[float, float]]], dict[str, float]],
    render_fn: Callable[[Path, Path, Path, float], dict[str, Any]] | None = None,
    pictures: dict[str, Path] | None = None,
) -> dict[str, Any]:
    """Measure, plan and (with ``render_fn(source, picture, out, gain)``) render every unit.  ``pictures``: the clip
    whose video stream the cut uses (push-in compensated clip, else the source).  Never raises per unit: a failing
    unit is recorded as SKIPPED_ERROR and keeps its original sound."""
    units: dict[str, dict[str, Any]] = {}
    for uid in sorted(clips):
        clip, cut = Path(clips[uid]), windows.get(uid)
        role = str(roles.get(uid) or "AMBIENCE").upper()
        row: dict[str, Any] = {"role": role, "source": str(clip), "cut_window": list(cut) if cut else None}
        try:
            if not cut or cut[1] - cut[0] <= 0.05:
                raise ValueError("empty cut window")
            spans = speech_windows((unit_asr or {}).get(uid), cut) if role == "DIALOGUE" else []
            if sum(b - a for a, b in spans) >= MIN_SPEECH_SECONDS:
                method = "SPEECH_WINDOWS"
            else:
                method, spans = "WHOLE_CUT_WINDOW", [cut]
            measured = measure_fn(clip, spans)
            target = float(targets[role])
            plan = plan_gain(measured["integrated_loudness_lufs"], target)
            gain: float | str = plan["gain_db"]
            lines: list[dict[str, Any]] = []
            if method == "SPEECH_WINDOWS":
                # per-line match (device 1101 E24): each line to LINE_TARGET_LUFS, not one gain for the unit
                for span in line_spans(spans):
                    lines.append({"span": list(span), **plan_line_gain(
                        measure_fn(clip, [span])["integrated_loudness_lufs"])})
                gains = sorted(r["gain_db"] for r in lines)
                plan = {**plan, "gain_db": gains[len(gains) // 2], "unit_gain_plan_db": plan["gain_db"]}
                method, gain = "PER_LINE", line_gain_expression(lines)
                row["line_target_lufs"], row["line_tolerance_lu"] = LINE_TARGET_LUFS, LINE_TOLERANCE_LU
            row.update(method=method, spans=[list(s) for s in spans], input=measured, target_lufs=target, **plan)
            if lines:
                row["lines"] = lines
            if (all(abs(r["gain_db"]) < UNCHANGED_BELOW_DB for r in lines) if lines
                    else abs(plan["gain_db"]) < UNCHANGED_BELOW_DB):
                row["status"] = "UNCHANGED"
            elif render_fn is not None:
                target_path = out_dir / f"{uid}.mov"
                target_path.parent.mkdir(parents=True, exist_ok=True)
                picture = Path((pictures or {}).get(uid) or clip)
                rendered = render_fn(clip, picture, target_path, gain)
                after = measure_fn(target_path, spans)
                for line in lines:
                    line["output_lufs"] = measure_fn(target_path, [tuple(line["span"])])["integrated_loudness_lufs"]
                row.update(status="APPLIED", source_sha256=sha256_file(clip), picture_source=str(picture),
                           picture_sha256=sha256_file(picture), output=str(target_path),
                           output_sha256=sha256_file(target_path), render=rendered, output_measured=after)
            else:
                row["status"] = "PLANNED"
        except Exception as exc:  # noqa: BLE001 - one unit never blocks the others
            row["status"] = f"SKIPPED_ERROR:{type(exc).__name__}:{exc}"
        units[uid] = row
    before = [r["input"]["integrated_loudness_lufs"] for r in units.values() if "input" in r]
    after = [(r.get("output_measured") or {}).get("integrated_loudness_lufs", r["input"]["integrated_loudness_lufs"])
             for r in units.values() if "input" in r]
    return {"schema": SCHEMA, "episode": episode, "status": "PASS",
            "policy": {"id": "CAMERA_GRAMMAR_V1_UNIT_AUDIO_LEVELLING", "role_targets_lufs": dict(targets),
                       "max_gain_db": MAX_UNIT_GAIN_DB, "true_peak_ceiling_dbtp": UNIT_TRUE_PEAK_CEILING_DBTP,
                       "dialogue_measure": "ASR speech windows (>= 0.5 s) else the whole cut window",
                       "dialogue_lines": {"target_lufs": LINE_TARGET_LUFS, "tolerance_lu": LINE_TOLERANCE_LU,
                                          "max_gain_db": MAX_LINE_GAIN_DB, "ramp_s": LINE_RAMP_S,
                                          "min_line_s": MIN_LINE_SECONDS},
                       "scope": "static gain + peak limiter on the unit's own native audio; picture untouched; "
                                "duration unchanged"},
            "applied_units": sorted(uid for uid, r in units.items() if r.get("status") == "APPLIED"),
            "spread_lufs": {"before": _spread(before), "after": _spread(after)},
            "units": units}


def _spread(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    mean = sum(values) / len(values)
    std = (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5
    return {"min": round(min(values), 2), "max": round(max(values), 2), "std": round(std, 2)}


def applied_sources(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """unit -> APPLIED row whose levelled remux still exists with the recorded sha (for the AgentCut build)."""
    out = {}
    for uid, row in (report.get("units") or {}).items():
        if row.get("status") != "APPLIED":
            continue
        target = Path(str(row.get("output") or ""))
        if target.is_file() and sha256_file(target) == row.get("output_sha256"):
            out[str(uid)] = row
    return out


# ============================================================================================================
# 3. cut crossfades (render_portable_timeline)
# ============================================================================================================
def crossfade_plan(clips: list[dict[str, Any]], source_seconds: list[float], seconds: float = CUT_CROSSFADE_S
                   ) -> list[dict[str, float]]:
    """Per cut i -> i+1: {"mode", "head": s of clip i+1 played before its in-point, "tail": s of clip i played after
    its out-point, "seconds": head + tail, "fade": fade-through half length}.  Head and tail come from real handles
    of the sources, so the crossfaded track keeps the timeline length and every clip's in-point lands on its cut.
    mode CROSSFADE (>= MIN_CROSSFADE_S of handles), FADE_THROUGH (no handles) or HARD (a cut after a clip with an
    authored sound bridge, metadata.sound_bridge_out)."""
    plan = []
    for i in range(len(clips) - 1):
        out_clip, in_clip = clips[i], clips[i + 1]
        if (out_clip.get("metadata") or {}).get("sound_bridge_out"):
            plan.append({"mode": "HARD", "head": 0.0, "tail": 0.0, "seconds": 0.0, "fade": 0.0})
            continue
        tail_room = max(0.0, float(source_seconds[i]) - float(out_clip.get("in") or 0.0) - float(out_clip["duration"]))
        head_room = max(0.0, float(in_clip.get("in") or 0.0))
        cap = min(float(seconds), float(out_clip["duration"]) / 2.0, float(in_clip["duration"]) / 2.0)
        head = min(cap / 2.0, head_room)
        tail = min(cap - head, tail_room)
        head = min(cap - tail, head_room)
        total = head + tail
        if total < MIN_CROSSFADE_S - 1e-9:
            fade = min(FADE_THROUGH_HALF_S, float(out_clip["duration"]) / 4.0, float(in_clip["duration"]) / 4.0)
            plan.append({"mode": "FADE_THROUGH", "head": 0.0, "tail": 0.0, "seconds": 0.0, "fade": round(fade, 6)})
            continue
        plan.append({"mode": "CROSSFADE", "head": round(head, 6), "tail": round(tail, 6), "seconds": round(total, 6),
                     "fade": 0.0})
    return plan


def main() -> int:  # pragma: no cover - diagnostic
    import argparse
    parser = argparse.ArgumentParser(description="print the stamped duck expression of a BGM plan cue")
    parser.add_argument("plan", type=Path)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    for cue in plan.get("cues") or []:
        windows = cue.get("dialogue_windows") or []
        print(json.dumps(duck_shape(windows), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
