#!/usr/bin/env python3
"""final_cut_voice_unify — re-voice every dialogue line of a finished cut to its
character's canonical reference timbre, without touching picture or timing.

Why (E09, 2026-09-28): Seedance synthesises each unit's voice independently and
treats the bound reference audio as a soft hint, so one character's median F0
wandered 2x between scenes (秦铭 119–250 Hz against a 173–234 Hz reference band).
Re-generating units costs credits and does not converge; this is the free,
post-production repair (Roger chose option A).

Pipeline (all local, no provider POST):
  1. demucs two-stem split of the final mix -> vocals / no_vocals
  2. every line window of <EP>_FINAL_CUT_ASR_WINDOWS.json (speaker already
     attributed) is cut from the vocals and converted with Seed-VC to that
     speaker's reference WAV, length_adjust=1.0 so lip timing is unchanged
  3. converted lines are gain-matched and cross-faded back over the original
     vocals; everything outside line windows (breaths, efforts) stays original
  4. vocals + no_vocals are remixed, loudness-normalised to the release target
     and muxed onto the ORIGINAL video stream (stream copy, picture bit-exact)
  5. per-line F0 before/after is measured against voice_cast f0_band_hz

The output is a NEW versioned file; the admitted final cut is never overwritten.

ADAPTER_REQUIRED: runs under a Python that has torch, demucs, librosa and a
Seed-VC checkout (default $NALU_RUNTIME_ROOT/vendor/seed-vc, its .venv).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 44100


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run(argv: list[str]) -> None:
    subprocess.run([str(a) for a in argv], check=True)


def load_mono(path: Path) -> np.ndarray:
    audio, sr = sf.read(str(path), always_2d=True)
    audio = audio.mean(axis=1)
    if sr != SR:
        import librosa
        audio = librosa.resample(audio, orig_sr=sr, target_sr=SR)
    return audio.astype(np.float32)


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x)) + 1e-12))


def median_f0(x: np.ndarray, sr: int = SR) -> float | None:
    import librosa
    if len(x) < sr * 0.2:
        return None
    f0, voiced, _ = librosa.pyin(x, fmin=65, fmax=500, sr=sr, frame_length=2048)
    f0 = f0[voiced & ~np.isnan(f0)]
    return round(float(np.median(f0)), 2) if len(f0) else None


def separate(audio_wav: Path, work: Path, python: str) -> tuple[Path, Path]:
    stem = work / "demucs" / "htdemucs" / audio_wav.stem
    if (stem / "vocals.wav").is_file() and (stem / "no_vocals.wav").is_file():
        return stem / "vocals.wav", stem / "no_vocals.wav"  # a resumed run reuses its own split
    # -d cpu: on Apple silicon demucs picks MPS, which rejects conv_transpose1d >65536 channels
    run([python, "-m", "demucs", "--two-stems", "vocals", "-n", "htdemucs", "-d", "cpu",
         "-o", work / "demucs", audio_wav])
    return stem / "vocals.wav", stem / "no_vocals.wav"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--episode", required=True)
    ap.add_argument("--final", required=True, type=Path, help="admitted final cut (read only)")
    ap.add_argument("--windows", required=True, type=Path, help="<EP>_FINAL_CUT_ASR_WINDOWS.json")
    ap.add_argument("--voice-refs", required=True, type=Path,
                    help='JSON {"CHAR-ID": {"ref": wav, "band": [lo, hi]}}')
    ap.add_argument("--output", required=True, type=Path, help="new versioned mp4; must not exist")
    ap.add_argument("--report", required=True, type=Path)
    ap.add_argument("--work", type=Path, default=None)
    ap.add_argument("--seedvc-dir", type=Path,
                    default=Path(os.environ.get("NALU_RUNTIME_ROOT", "/Users/rogerwu/nalu_runtime")) / "vendor/seed-vc")
    ap.add_argument("--pad", type=float, default=0.12, help="seconds of context around each line")
    ap.add_argument("--fade", type=float, default=0.03)
    ap.add_argument("--diffusion-steps", type=int, default=30)
    # E09 v1 (timbre only, f0 unconditioned) left 26/49 lines outside the band: Seed-VC keeps
    # most of the source pitch.  f0 conditioning + auto adjust moves each speaker's pitch to the
    # reference median while keeping the line's intonation contour.
    ap.add_argument("--f0-condition", choices=("True", "False"), default="True")
    # v2 (auto adjust over a per-speaker batch) applies ONE shift to all of a speaker's lines and
    # keeps the drift between them; v3 moves every line's own median F0 to the reference median
    # before conversion, so auto adjust stays off.
    ap.add_argument("--auto-f0-adjust", choices=("True", "False"), default="False")
    ap.add_argument("--per-line-pitch-normalise", choices=("True", "False"), default="True")
    ap.add_argument("--max-shift-semitones", type=float, default=14.0)
    # after conversion, a line still outside the band by at most this much is pitch-shifted to
    # the band centre (larger residuals are left and reported for listening)
    ap.add_argument("--post-correct-semitones", type=float, default=4.0)
    ap.add_argument("--release-lufs", type=float, default=-14.0)
    ap.add_argument("--release-tp", type=float, default=-1.0)
    args = ap.parse_args()

    if args.output.exists() or args.report.exists():
        raise SystemExit("output/report exist; evidence is immutable — choose a new version")
    windows = json.loads(args.windows.read_text(encoding="utf-8"))
    refs = json.loads(args.voice_refs.read_text(encoding="utf-8"))
    missing = sorted({w["speaker"] for w in windows} - set(refs))
    if missing:
        raise SystemExit(f"no reference voice for {missing}")

    work = args.work or Path(tempfile.mkdtemp(prefix=f"{args.episode}_voicefix_"))
    work.mkdir(parents=True, exist_ok=True)
    python = sys.executable

    # 1. split
    mix_wav = work / "final_mix.wav"
    run(["ffmpeg", "-loglevel", "error", "-y", "-i", args.final, "-vn", "-ac", "2", "-ar", SR, mix_wav])
    vocals_path, rest_path = separate(mix_wav, work, python)
    vocals, _ = sf.read(str(vocals_path), always_2d=True)
    rest, _ = sf.read(str(rest_path), always_2d=True)
    vocals_mono = vocals.mean(axis=1).astype(np.float32)
    new_vocals = vocals.copy()

    # 2. convert, one Seed-VC run per speaker: that speaker's line clips are joined with
    # silence gaps, converted in one pass (length_adjust=1.0 keeps every offset), then cut
    # back.  One model load per speaker instead of per line; the in-process wrapper ran
    # ~9 s per diffusion step on CPU against ~1 s for inference.py.
    import librosa
    gap = np.zeros(int(0.5 * SR), dtype=np.float32)
    shifts: dict[int, float] = {}
    clips: dict[int, tuple[int, int, np.ndarray]] = {}
    by_speaker: dict[str, list[int]] = {}
    for i, w in enumerate(windows):
        a = max(0, int((float(w["start"]) - args.pad) * SR))
        b = min(len(vocals_mono), int((float(w["end"]) + args.pad) * SR))
        clip = vocals_mono[a:b]
        band = refs[w["speaker"]].get("band") or [None, None]
        shifts[i] = 0.0
        if args.per_line_pitch_normalise == "True" and band[0] is not None:
            source_f0 = median_f0(clip)
            if source_f0:
                target_f0 = (float(band[0]) + float(band[1])) / 2  # band = reference median ±15 %
                step = 12 * float(np.log2(target_f0 / source_f0))
                if abs(step) <= args.max_shift_semitones:
                    shifts[i] = round(step, 2)
                    clip = librosa.effects.pitch_shift(clip, sr=SR, n_steps=step).astype(np.float32)
        clips[i] = (a, b, clip)
        by_speaker.setdefault(w["speaker"], []).append(i)
    converted: dict[int, np.ndarray] = {}
    for speaker, idxs in by_speaker.items():
        pieces, offsets, cursor = [], {}, 0
        for i in idxs:
            offsets[i] = cursor
            pieces += [clips[i][2], gap]
            cursor += len(clips[i][2]) + len(gap)
        joined = np.concatenate(pieces)
        src = work / f"speaker_{speaker}.wav"
        sf.write(str(src), joined, SR)
        out_dir = work / f"vc_{speaker}"
        out_dir.mkdir(exist_ok=True)
        stamp = out_dir / "source.sha256"
        cached = sorted(out_dir.glob("vc_*.wav"))
        if cached and stamp.is_file() and stamp.read_text().strip() == sha256(src):
            reuse = True  # same speaker input as a previous run in this work dir
        else:
            reuse = False
            for old in cached:
                old.unlink()
        runner = ("import runpy, sys, torch; torch.backends.mps.is_available = lambda: False; "
                  "sys.argv = ['inference.py'] + sys.argv[1:]; runpy.run_path('inference.py', run_name='__main__')")
        if not reuse:
            subprocess.run([python, "-c", runner, "--source", str(src), "--target", refs[speaker]["ref"],
                            "--output", str(out_dir), "--diffusion-steps", str(args.diffusion_steps),
                            "--length-adjust", "1.0", "--inference-cfg-rate", "0.7",
                            "--f0-condition", args.f0_condition, "--auto-f0-adjust", args.auto_f0_adjust,
                            "--fp16", "False"],
                           check=True, cwd=str(args.seedvc_dir))
            stamp.write_text(sha256(src))
        result = sorted(out_dir.glob("vc_*.wav"))[-1]
        wave = load_mono(result)
        scale = len(joined) / max(1, len(wave))  # guard against a few samples of drift
        for i in idxs:
            lo = int(offsets[i] / scale)
            conv = wave[lo: lo + len(clips[i][2])]
            converted[i] = np.pad(conv, (0, len(clips[i][2]) - len(conv)))
        print(f"{speaker}: {len(idxs)} lines converted{' (cached)' if reuse else ''}", flush=True)

    rows = []
    fade = int(args.fade * SR)
    for i, w in enumerate(windows):
        speaker = w["speaker"]
        a, b, _ = clips[i]
        clip = vocals_mono[a:b]
        conv = converted[i] * (rms(clip) / rms(converted[i]))
        band = refs[speaker].get("band") or [None, None]
        before, after = median_f0(clip), median_f0(conv)
        post_shift = 0.0
        if after is not None and band[0] is not None and not (band[0] <= after <= band[1]):
            step = 12 * float(np.log2(((float(band[0]) + float(band[1])) / 2) / after))
            if abs(step) <= args.post_correct_semitones:
                conv = librosa.effects.pitch_shift(conv, sr=SR, n_steps=step).astype(np.float32)
                post_shift, after = round(step, 2), median_f0(conv)
        in_band = (after is not None and band[0] is not None and band[0] <= after <= band[1])
        env = np.ones(len(clip), dtype=np.float32)
        if len(clip) > 2 * fade:
            env[:fade] = np.linspace(0, 1, fade)
            env[-fade:] = np.linspace(1, 0, fade)
        conv = conv[: len(clip)]
        for ch in range(new_vocals.shape[1]):
            new_vocals[a:b, ch] = new_vocals[a:b, ch] * (1 - env) + conv * env
        rows.append({"index": i, "unit_id": w.get("unit_id"), "speaker": speaker, "text": w.get("text"),
                     "start": w["start"], "end": w["end"], "f0_before": before, "pitch_shift_semitones": shifts[i], "post_shift_semitones": post_shift,
                     "f0_after": after,
                     "band": band, "after_in_band": in_band})
        print(f"[{i + 1}/{len(windows)}] {speaker} {before} -> {after} Hz band={band}", flush=True)

    # 3/4. remix, normalise, mux onto original picture
    n = min(len(new_vocals), len(rest))
    remix = work / "remix.wav"
    sf.write(str(remix), (new_vocals[:n] + rest[:n]).astype(np.float32), SR)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-loglevel", "error", "-y", "-i", args.final, "-i", remix,
         "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
         "-af", f"loudnorm=I={args.release_lufs}:TP={args.release_tp}:LRA=11",
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", args.output])

    report = {
        "schema": "nalu.final_cut_voice_unify.v1", "episode": args.episode,
        "source_final": str(args.final), "source_final_sha256": sha256(args.final),
        "output": str(args.output), "output_sha256": sha256(args.output),
        "picture": "VIDEO_STREAM_COPIED_BIT_EXACT", "engine": "seed-vc", "f0_condition": args.f0_condition, "auto_f0_adjust": args.auto_f0_adjust, "per_line_pitch_normalise": args.per_line_pitch_normalise,
        "separation": "demucs htdemucs two-stem", "diffusion_steps": args.diffusion_steps,
        "length_adjust": 1.0, "release_lufs": args.release_lufs,
        "lines": rows, "lines_total": len(rows),
        "lines_after_in_band": sum(1 for r in rows if r["after_in_band"]),
        "lines_before_in_band": sum(1 for r in rows if r["f0_before"] and r["band"][0] is not None
                                    and r["band"][0] <= r["f0_before"] <= r["band"][1]),
        "work_dir": str(work),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("output", "lines_total", "lines_before_in_band",
                                             "lines_after_in_band")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
