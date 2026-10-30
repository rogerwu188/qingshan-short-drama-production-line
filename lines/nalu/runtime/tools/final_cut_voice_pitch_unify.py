#!/usr/bin/env python3
"""final_cut_voice_pitch_unify — free, formant-preserving per-line pitch correction of a
finished cut so every speaker sits in its voice-cast band and co-present speakers stay apart.

Why (E12 成片审看 2026-10-30, Roger item 1c): MiniMax-H3 speaks natively and ignores the bound
2-s reference, so one character's median F0 wandered 101–186 Hz across scenes and the
voice_distinctness detector FAILed (4 collisions, 24 out-of-band lines).  Re-generating units
is paid and does not converge (K130: never the same prompt again).  This is the free repair,
generalising the single-unit WORLD post-fix recorded in
preproduction/reports/qa/postfix/E12-VU-006_voice_pitch_postfix.json (D-30 precedent).

What it does (no provider call, picture bit-exact):
  1. demuxes the input's audio (48 kHz, channels kept)
  2. derives LINE WINDOWS on the release timeline: an ASR of THIS file (faster-whisper, or a
     pre-computed --asr-json with the same shape) → each segment is assigned to the unit whose
     release-timeline span contains its midpoint, clipped to that span; speaker / emotion /
     scene come from the generation contract through the grouping plan (one speaker per unit on
     this line; a multi-speaker unit matches text against its dialogue_units).  The windows
     are also written out in the <EP>_FINAL_CUT_ASR_WINDOWS.json shape (--windows-out) so the
     audience detectors can measure the same spans.
  3. per window: median F0 with the SAME estimator the detectors use
     (tools.dialogue_voice_metrics.estimate_f0_median) on the exact span → semitone step to the
     speaker's band centre (voice_cast f0_band_hz), clamped to ±--max-shift-semitones; steps
     below --min-step-semitones are skipped.  WORLD (pyworld: harvest+stonemask → cheaptrick →
     d4c) re-synthesises the span with f0 scaled and the spectral envelope unchanged, so the
     timbre (formants) is kept; 50 ms crossfades into the untouched audio on both sides.
     Levels are NOT changed: this stage runs before the release mix / loudness stage.
  4. remuxes: video stream copied, audio re-encoded (or --wav-out for a lossless hand-off).
  5. report: per-line before/after F0, per-scene speaker medians, every co-present pair's
     Hz difference before/after, minimum pair difference, sha256 of input and output.

Overlapping or out-of-unit ASR windows are never trusted: a segment is bounded by its unit's
release span, which is what made the pre-existing FINAL_CUT_ASR_WINDOWS unusable on E12
(13 windows entirely outside their unit, 36 partial — built on pre-trim offsets).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import subprocess
import sys
import tempfile
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nalu_paths as _np  # noqa: E402
sys.path.insert(0, str(Path(f"{_np.ENGINE_ROOT}")))
from tools.dialogue_voice_metrics import estimate_f0_median  # noqa: E402

SR = 48000
SCHEMA = "nalu.final_cut_voice_pitch_unify.v1"
WINDOWS_SCHEMA = "nalu.final_cut_asr_windows.v1"
MIN_COPRESENT_F0_DIFF_HZ = 40.0   # Roger 2026-10-30: 同场对手戏两个角色基频中位数差 ≥40 Hz


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def run(argv: list[Any]) -> None:
    subprocess.run([str(a) for a in argv], check=True)


# ------------------------------------------------------------------ audio i/o

def demux(media: Path, wav: Path) -> None:
    run(["ffmpeg", "-loglevel", "error", "-y", "-i", media, "-vn", "-ar", SR, "-c:a", "pcm_f32le", wav])


def load_wav(path: Path) -> np.ndarray:
    import soundfile as sf
    audio, sr = sf.read(str(path), always_2d=True, dtype="float32")
    if sr != SR:
        raise SystemExit(f"unexpected sample rate {sr}")
    return audio


def save_wav(path: Path, audio: np.ndarray) -> None:
    import soundfile as sf
    sf.write(str(path), audio, SR, subtype="FLOAT")


# ------------------------------------------------------------------ windows

def unit_speakers(contract: dict[str, Any], grouping: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """unit_id -> {scene, shots, lines:[{speaker, emotion, text, shot_id}]} from the contract."""
    scene_of = {str(s.get("shot_id")): str(s.get("scene_id") or "") for s in contract.get("shots") or []}
    lines_by_shot: dict[str, list[dict[str, Any]]] = {}
    for row in (contract.get("audio_contract") or {}).get("dialogue_units") or []:
        lines_by_shot.setdefault(str(row.get("shot_id")), []).append(
            {"speaker": str(row.get("speaker_id") or ""), "emotion": str(row.get("emotion") or "calm"),
             "text": str(row.get("text") or ""), "shot_id": str(row.get("shot_id"))})
    out: dict[str, dict[str, Any]] = {}
    for unit in grouping.get("units") or []:
        shots = [s if isinstance(s, str) else str(s.get("shot_id")) for s in
                 (unit.get("editorial_shot_ids") or unit.get("shots") or unit.get("shot_ids") or [])]
        lines = [line for shot in shots for line in lines_by_shot.get(shot, [])]
        out[str(unit.get("unit_id"))] = {
            "scene": str(unit.get("scene_id") or next((scene_of.get(s) for s in shots if scene_of.get(s)), "")),
            "shots": shots, "lines": lines,
            "speakers": sorted({line["speaker"] for line in lines if line["speaker"]}),
        }
    return out


def _char_overlap(a: str, b: str) -> float:
    sa = {c for c in a if "一" <= c <= "鿿"}
    sb = {c for c in b if "一" <= c <= "鿿"}
    return len(sa & sb) / max(1, len(sa))


def transcribe(wav_mono_16k: Path, model: str) -> list[dict[str, Any]]:
    from faster_whisper import WhisperModel
    engine = WhisperModel(model, device="cpu", compute_type="int8")
    segs, _ = engine.transcribe(str(wav_mono_16k), language="zh", word_timestamps=True,
                                vad_filter=True, beam_size=5)
    out = []
    for s in segs:
        out.append({"start": round(float(s.start), 3), "end": round(float(s.end), 3), "text": s.text,
                    "words": [{"w": w.word, "s": round(float(w.start), 3), "e": round(float(w.end), 3)}
                              for w in (s.words or [])]})
    return out


def derive_windows(asr: list[dict[str, Any]], timeline: dict[str, Any], units: dict[str, dict[str, Any]],
                   *, min_len: float = 0.3) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """ASR segments → speaker-attributed line windows bounded by their unit's release span."""
    spans = [(str(s["unit_id"]), float(s["output_start"]), float(s["output_end"]))
             for s in timeline.get("segments") or []]
    content_end = float(timeline.get("content_runtime_seconds") or (spans[-1][2] if spans else 0.0))
    windows, dropped = [], []
    for seg in asr:
        # word timestamps trim whisper's padded segment ends (the dialogue-tail false positive)
        words = seg.get("words") or []
        start = float(words[0]["s"]) if words else float(seg["start"])
        end = float(words[-1]["e"]) if words else float(seg["end"])
        if end <= start:
            continue
        mid = (start + end) / 2
        if mid >= content_end:
            dropped.append({**seg, "reason": "AFTER_CONTENT_END"})
            continue
        unit = next(((u, a, b) for u, a, b in spans if a <= mid < b), None)
        if unit is None:
            dropped.append({**seg, "reason": "NO_UNIT_AT_MIDPOINT"})
            continue
        unit_id, a, b = unit
        start, end = max(start, a), min(end, b)
        if end - start < min_len:
            dropped.append({**seg, "reason": "TOO_SHORT_AFTER_CLIP", "unit_id": unit_id})
            continue
        info = units.get(unit_id) or {}
        lines = info.get("lines") or []
        if not lines:
            dropped.append({**seg, "reason": "UNIT_HAS_NO_DIALOGUE", "unit_id": unit_id})
            continue
        if len(info.get("speakers") or []) == 1:
            line = max(lines, key=lambda l: _char_overlap(seg.get("text") or "", l["text"]))
        else:
            line = max(lines, key=lambda l: _char_overlap(seg.get("text") or "", l["text"]))
        windows.append({"start": round(start, 3), "end": round(end, 3), "unit_id": unit_id,
                        "text": (seg.get("text") or "").strip(), "speaker": line["speaker"],
                        "emotion": line["emotion"], "scene": info.get("scene") or "",
                        "shot_id": line["shot_id"], "contract_text": line["text"],
                        "text_overlap": round(_char_overlap(seg.get("text") or "", line["text"]), 3)})
    windows.sort(key=lambda w: w["start"])
    # Multi-speaker units: character overlap against a weak ASR (whisper small on H3 speech) mis-assigns
    # lines.  The contract lists the unit's lines in spoken order, so a window whose text match is weak
    # (< 0.5) takes the speaker of the contract line at the same RANK inside the unit (time order).
    by_unit: dict[str, list[dict[str, Any]]] = {}
    for w in windows:
        by_unit.setdefault(w["unit_id"], []).append(w)
    for unit_id, ws in by_unit.items():
        lines = (units.get(unit_id) or {}).get("lines") or []
        if len({l["speaker"] for l in lines}) <= 1 or not lines:
            continue
        for rank, w in enumerate(ws):
            if w["text_overlap"] >= 0.5:
                continue
            line = lines[min(len(lines) - 1, int(rank * len(lines) / max(1, len(ws))))]
            w.update({"speaker": line["speaker"], "emotion": line["emotion"], "shot_id": line["shot_id"],
                      "contract_text": line["text"], "attribution": "RANK_ORDER_IN_UNIT"})
    # windows inside one unit must not overlap: later window wins the shared span
    for i in range(1, len(windows)):
        if windows[i]["start"] < windows[i - 1]["end"]:
            windows[i - 1]["end"] = round(windows[i]["start"], 3)
    windows = [w for w in windows if w["end"] - w["start"] >= min_len]
    return windows, dropped


# ------------------------------------------------------------------ pitch

F0_ESTIMATOR = "harvest"   # set from --f0-estimator; dio is ~10x faster, harvest is the reference


def world_shift(x: np.ndarray, factor: float) -> np.ndarray:
    """Formant-preserving pitch scale of a mono float32 block (WORLD vocoder)."""
    import pyworld as pw
    xd = x.astype(np.float64)
    if F0_ESTIMATOR == "dio":
        f0, t = pw.dio(xd, SR, f0_floor=60.0, f0_ceil=800.0, frame_period=5.0)
    else:
        f0, t = pw.harvest(xd, SR, f0_floor=60.0, f0_ceil=800.0, frame_period=5.0)
    f0 = pw.stonemask(xd, f0, t, SR)
    sp = pw.cheaptrick(xd, f0, t, SR)
    ap = pw.d4c(xd, f0, t, SR)
    y = pw.synthesize(f0 * factor, sp, ap, SR, frame_period=5.0)
    y = y[: len(xd)]
    if len(y) < len(xd):
        y = np.pad(y, (0, len(xd) - len(y)))
    return y.astype(np.float32)


def f0_of(audio: np.ndarray, start: float, end: float) -> float | None:
    a, b = int(start * SR), int(end * SR)
    mono = audio[a:b].mean(axis=1) if audio.ndim == 2 else audio[a:b]
    if len(mono) < SR * 0.2:
        return None
    value = estimate_f0_median(mono.tolist(), SR)
    return round(float(value), 2) if value is not None else None


def band_of(cast: dict[str, Any], speaker: str) -> tuple[float, float] | None:
    row = (cast.get("characters") or {}).get(speaker) or {}
    band = row.get("f0_band_hz")
    if not band:
        return None
    return float(band[0]), float(band[1])


def scene_targets(windows: list[dict[str, Any]], cast: dict[str, Any],
                  *, min_diff_hz: float = MIN_COPRESENT_F0_DIFF_HZ) -> dict[str, dict[str, Any]]:
    """Per-scene target F0 for every speaker: the band centre, pushed apart inside the bands until every
    co-present pair is >= ``min_diff_hz`` apart (or the band edges are reached).

    Roger 2026-10-30 (1c): the 40 Hz rule is absolute.  Two cast bands can sit closer than 40 Hz centre to
    centre (E12: 许岳平 131.6 vs 冯易安 98.2 = 33 Hz; vs 酒保 100.4 = 31 Hz), so a centre target can never
    satisfy the rule in their shared scenes; the edges can (151 vs 98 = 53 Hz).  The push is symmetric and
    clamped; ``reachable`` records whether the rule can be met inside the bands at all."""
    out: dict[str, dict[str, Any]] = {}
    scenes: dict[str, set[str]] = {}
    for w in windows:
        scenes.setdefault(w["scene"], set()).add(w["speaker"])
    for scene, speakers in sorted(scenes.items()):
        bands = {sp: band_of(cast, sp) for sp in sorted(speakers)}
        bands = {sp: b for sp, b in bands.items() if b}
        target = {sp: (b[0] + b[1]) / 2 for sp, b in bands.items()}
        for _ in range(8):
            moved = False
            for a, b in combinations(sorted(target), 2):
                lo_sp, hi_sp = (a, b) if target[a] <= target[b] else (b, a)
                deficit = min_diff_hz - (target[hi_sp] - target[lo_sp])
                if deficit <= 0:
                    continue
                new_lo = max(bands[lo_sp][0], target[lo_sp] - deficit / 2)
                new_hi = min(bands[hi_sp][1], target[hi_sp] + deficit / 2)
                still = min_diff_hz - (new_hi - new_lo)
                if still > 0:   # one side hit its edge: let the other side take the rest
                    new_lo = max(bands[lo_sp][0], new_lo - still)
                    still = min_diff_hz - (new_hi - new_lo)
                    if still > 0:
                        new_hi = min(bands[hi_sp][1], new_hi + still)
                if (new_lo, new_hi) != (target[lo_sp], target[hi_sp]):
                    target[lo_sp], target[hi_sp] = new_lo, new_hi
                    moved = True
            if not moved:
                break
        pairs = [{"a": a, "b": b, "diff_hz": round(abs(target[a] - target[b]), 2),
                  "reachable": abs(target[a] - target[b]) >= min_diff_hz - 1e-6}
                 for a, b in combinations(sorted(target), 2)]
        out[scene] = {"targets_hz": {sp: round(v, 2) for sp, v in target.items()},
                      "pairs": pairs, "reachable": all(pr["reachable"] for pr in pairs)}
    return out


def scene_medians(windows: list[dict[str, Any]], key: str) -> dict[str, dict[str, float]]:
    per: dict[tuple[str, str], list[float]] = {}
    for w in windows:
        if w.get(key) is not None:
            per.setdefault((w["scene"], w["speaker"]), []).append(float(w[key]))
    out: dict[str, dict[str, float]] = {}
    for (scene, speaker), values in per.items():
        out.setdefault(scene, {})[speaker] = round(statistics.median(values), 2)
    return out


def pair_table(medians: dict[str, dict[str, float]]) -> list[dict[str, Any]]:
    rows = []
    for scene, by in sorted(medians.items()):
        for a, b in combinations(sorted(by), 2):
            rows.append({"scene": scene, "a": a, "b": b, "f0_a": by[a], "f0_b": by[b],
                         "diff_hz": round(abs(by[a] - by[b]), 2),
                         "pass_40hz": abs(by[a] - by[b]) >= MIN_COPRESENT_F0_DIFF_HZ})
    return rows


# ------------------------------------------------------------------ main

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--episode", required=True)
    ap.add_argument("--input", required=True, type=Path, help="cut to correct (read only; pre-mix picture preferred)")
    ap.add_argument("--output", required=True, type=Path, help="new mp4; must not exist")
    ap.add_argument("--release-timeline", required=True, type=Path)
    ap.add_argument("--contract", required=True, type=Path, help="generation contract (audio_contract.dialogue_units)")
    ap.add_argument("--grouping-plan", required=True, type=Path)
    ap.add_argument("--voice-cast", required=True, type=Path, help="qingshan.voice_cast.v1 (f0_band_hz per speaker)")
    ap.add_argument("--asr-json", type=Path, help="faster-whisper segments of --input (start,end,text,words); else transcribed here")
    ap.add_argument("--asr-model", default="large-v3")
    ap.add_argument("--asr-out", type=Path, help="persist the raw ASR segments of --input (reusable via --asr-json)")
    ap.add_argument("--target-margin-hz", type=float, default=6.0,
                    help="scene targets are pushed to 40 Hz + this margin so measured medians stay >= 40 Hz")
    ap.add_argument("--min-window-seconds", type=float, default=0.8,
                    help="shorter windows are measured but never shifted (E12: a 0.4 s window read 191 Hz, shifted down, read 341 Hz)")
    ap.add_argument("--skip-units", default="",
                    help="comma-separated unit ids left untouched (e.g. units whose voice is an octave off the cast band: "
                         "a <=6 st shift cannot fix them, they are redo candidates for the line owner)")
    ap.add_argument("--target-tolerance-semitones", type=float, default=1.5,
                    help="an in-band line this close to its scene target is left untouched (fewer resyntheses)")
    ap.add_argument("--windows-out", type=Path, help="write the derived line windows (FINAL_CUT_ASR_WINDOWS shape)")
    ap.add_argument("--wav-out", type=Path, help="also write the corrected audio as 48 kHz float WAV for the mix stage")
    ap.add_argument("--report", required=True, type=Path)
    ap.add_argument("--max-shift-semitones", type=float, default=6.0)
    ap.add_argument("--min-step-semitones", type=float, default=0.25)
    ap.add_argument("--crossfade", type=float, default=0.05)
    ap.add_argument("--pad", type=float, default=0.03, help="context re-synthesised around each exact span")
    ap.add_argument("--work", type=Path)
    ap.add_argument("--f0-estimator", choices=["harvest", "dio"], default="harvest",
                    help="WORLD F0 analysis: harvest (reference, slow) or dio (~10x faster; 2026-10-30 E12 runs)")
    args = ap.parse_args(argv)
    global F0_ESTIMATOR
    F0_ESTIMATOR = args.f0_estimator

    if args.output.exists():
        raise SystemExit("output exists; evidence is immutable — choose a new version")
    cast = read_json(args.voice_cast, {}) or {}
    timeline = read_json(args.release_timeline, {}) or {}
    contract = read_json(args.contract, {}) or {}
    grouping = read_json(args.grouping_plan, {}) or {}
    units = unit_speakers(contract, grouping)

    work = args.work or Path(tempfile.mkdtemp(prefix=f"{args.episode}_pitch_unify_"))
    work.mkdir(parents=True, exist_ok=True)
    src_wav = work / "input_48k.wav"
    demux(args.input, src_wav)
    audio = load_wav(src_wav)
    channels = audio.shape[1]

    if args.asr_json and args.asr_json.is_file():
        asr = read_json(args.asr_json, []) or []
        asr_source = str(args.asr_json)
    else:
        mono16 = work / "input_16k.wav"
        run(["ffmpeg", "-loglevel", "error", "-y", "-i", args.input, "-vn", "-ac", 1, "-ar", 16000, mono16])
        asr = transcribe(mono16, args.asr_model)
        asr_source = f"faster-whisper {args.asr_model} on {args.input.name}"
        if args.asr_out:
            args.asr_out.parent.mkdir(parents=True, exist_ok=True)
            args.asr_out.write_text(json.dumps(asr, ensure_ascii=False, indent=1), encoding="utf-8")
    windows, dropped = derive_windows(asr, timeline, units)
    if not windows:
        raise SystemExit("no line windows derived")

    fade_n = int(args.crossfade * SR)
    out_audio = audio.copy()
    targets = scene_targets(windows, cast, min_diff_hz=MIN_COPRESENT_F0_DIFF_HZ + args.target_margin_hz)
    skip_units = {u.strip() for u in args.skip_units.split(",") if u.strip()}
    rows = []
    for i, w in enumerate(windows):
        band = band_of(cast, w["speaker"])
        before = f0_of(audio, w["start"], w["end"])
        target = ((targets.get(w["scene"]) or {}).get("targets_hz") or {}).get(w["speaker"])
        row = {**w, "band": list(band) if band else None, "target_hz": target, "f0_before": before,
               "step_semitones": 0.0, "clamped": False, "f0_after": before, "applied": False, "skipped": None}
        multi = len((units.get(w["unit_id"]) or {}).get("speakers") or []) > 1
        if band and before and target:
            step = 12 * math.log2(target / before)
            in_band = band[0] <= before <= band[1]
            if w["unit_id"] in skip_units:
                row["skipped"] = "UNIT_SKIPPED_BY_OPERATOR"
                step = 0.0
            elif in_band and abs(step) <= args.target_tolerance_semitones:
                row["skipped"] = "IN_BAND_NEAR_TARGET"
                step = 0.0
            elif (w["end"] - w["start"]) < args.min_window_seconds:
                row["skipped"] = "WINDOW_TOO_SHORT_TO_SHIFT"
                step = 0.0
            if abs(step) > args.max_shift_semitones:
                step = math.copysign(args.max_shift_semitones, step)
                row["clamped"] = True
            if abs(step) >= args.min_step_semitones:
                a = max(0, int((w["start"] - args.pad - args.crossfade) * SR))
                b = min(len(audio), int((w["end"] + args.pad + args.crossfade) * SR))
                factor = 2 ** (step / 12)
                env = np.ones(b - a, dtype=np.float32)
                if b - a > 2 * fade_n:
                    env[:fade_n] = np.linspace(0, 1, fade_n, dtype=np.float32)
                    env[-fade_n:] = np.linspace(1, 0, fade_n, dtype=np.float32)
                for ch in range(channels):
                    shifted = world_shift(audio[a:b, ch], factor)
                    # level-preserving: WORLD re-synthesis is not gain-exact (E12 v1: true peak -1.2 -> +2.6 dBTP).
                    # Match the span's RMS to the original and never exceed the original span's sample peak.
                    orig = audio[a:b, ch]
                    rms_o, rms_s = float(np.sqrt(np.mean(orig ** 2))), float(np.sqrt(np.mean(shifted ** 2)))
                    if rms_s > 1e-9:
                        shifted = shifted * (rms_o / rms_s)
                    peak_o, peak_s = float(np.max(np.abs(orig))), float(np.max(np.abs(shifted)))
                    if peak_s > peak_o > 0:
                        shifted = shifted * (peak_o / peak_s)
                    out_audio[a:b, ch] = orig * (1 - env) + shifted * env
                after = f0_of(out_audio, w["start"], w["end"])
                closer = (after is not None and abs(math.log2(after / target)) < abs(math.log2(before / target))
                          and (after > before) == (step > 0))
                if not closer:
                    # octave/estimator error or the vocoder did not move the voice: keep the original bytes
                    out_audio[a:b, :] = audio[a:b, :]
                    row.update({"skipped": "REVERTED_NO_IMPROVEMENT", "f0_after_attempt": after, "attempted_step_semitones": round(step, 2)})
                else:
                    row.update({"step_semitones": round(step, 2), "applied": True, "f0_after": after})
        row["after_in_band"] = bool(band and row["f0_after"] and band[0] <= row["f0_after"] <= band[1])
        row["before_in_band"] = bool(band and before and band[0] <= before <= band[1])
        rows.append(row)
        print(f"[{i + 1}/{len(windows)}] {w['unit_id']} {w['speaker']} {before} -> {row['f0_after']} Hz "
              f"step={row['step_semitones']} band={row['band']}", flush=True)

    fixed_wav = work / "output_48k.wav"
    save_wav(fixed_wav, out_audio)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-loglevel", "error", "-y", "-i", args.input, "-i", fixed_wav,
         "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", SR,
         "-movflags", "+faststart", args.output])
    if args.wav_out:
        args.wav_out.parent.mkdir(parents=True, exist_ok=True)
        save_wav(args.wav_out, out_audio)

    before_med = scene_medians(rows, "f0_before")
    after_med = scene_medians(rows, "f0_after")
    pairs_before, pairs_after = pair_table(before_med), pair_table(after_med)
    report = {
        "schema": SCHEMA, "episode": args.episode,
        "input": str(args.input), "input_sha256": sha256(args.input),
        "output": str(args.output), "output_sha256": sha256(args.output),
        "picture": "VIDEO_STREAM_COPIED_BIT_EXACT", "levels": "PER_SPAN_RMS_MATCHED_AND_PEAK_CAPPED_TO_SOURCE",
        "method": {"vocoder": f"pyworld WORLD {F0_ESTIMATOR}+stonemask/cheaptrick/d4c, formants preserved",
                   "estimator": "tools/dialogue_voice_metrics.estimate_f0_median (same as detectors)",
                   "target": "scene-aware: band centre pushed apart inside the bands until co-present pairs are >= 40 Hz",
                   "max_shift_semitones": args.max_shift_semitones,
                   "crossfade_s": args.crossfade, "asr_source": asr_source},
        "windows_total": len(rows), "windows_applied": sum(1 for r in rows if r["applied"]),
        "windows_clamped": sum(1 for r in rows if r["clamped"]),
        "lines_before_in_band": sum(1 for r in rows if r["before_in_band"]),
        "lines_after_in_band": sum(1 for r in rows if r["after_in_band"]),
        "scene_targets": targets,
        "scenes_40hz_unreachable_inside_bands": [sc for sc, t in targets.items() if not t["reachable"]],
        "target_tolerance_semitones": args.target_tolerance_semitones,
        "windows_skipped_by_reason": {k: sum(1 for r in rows if r.get("skipped") == k)
                                      for k in sorted({r.get("skipped") for r in rows if r.get("skipped")})},
        "guards": {"min_window_seconds": args.min_window_seconds, "weak_text_match_attribution": "RANK_ORDER_IN_UNIT", "skip_units": sorted(skip_units)},
        "scene_speaker_f0_median_before": before_med, "scene_speaker_f0_median_after": after_med,
        "copresent_pairs_before": pairs_before, "copresent_pairs_after": pairs_after,
        "min_pair_diff_hz_before": min((p["diff_hz"] for p in pairs_before), default=None),
        "min_pair_diff_hz_after": min((p["diff_hz"] for p in pairs_after), default=None),
        "pairs_under_40hz_before": [p for p in pairs_before if not p["pass_40hz"]],
        "pairs_under_40hz_after": [p for p in pairs_after if not p["pass_40hz"]],
        "dropped_asr_segments": dropped, "lines": rows, "work_dir": str(work),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.windows_out:
        args.windows_out.parent.mkdir(parents=True, exist_ok=True)
        args.windows_out.write_text(json.dumps(
            [{**{k: w[k] for k in ("start", "end", "unit_id", "text", "speaker", "emotion", "scene", "shot_id")},
              "f0_measurable": (w["end"] - w["start"]) >= args.min_window_seconds,
              "attribution": w.get("attribution", "TEXT_OVERLAP" if w.get("text_overlap", 0) >= 0.5 else "UNIT_SOLE_SPEAKER")}
             for w in windows], ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("output", "windows_total", "windows_applied", "lines_before_in_band",
                                             "lines_after_in_band", "min_pair_diff_hz_before", "min_pair_diff_hz_after")},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
