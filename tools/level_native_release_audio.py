#!/usr/bin/env python3
"""Level provider-native release audio per unit without changing picture."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

try:
    from tools.native_audio_loudness_contract import (
        evaluate_release_loudness,
        evaluate_unit_loudness,
        measure_loudness,
        plan_static_gain,
        ROLE_TARGETS_LUFS,
        ROLE_ACCEPTANCE_RANGES_LUFS,
        DEFAULT_RELEASE_TARGET_LUFS as RELEASE_TARGET_LUFS,
    )
except ModuleNotFoundError:
    from native_audio_loudness_contract import (
        evaluate_release_loudness,
        evaluate_unit_loudness,
        measure_loudness,
        plan_static_gain,
        DEFAULT_RELEASE_TARGET_LUFS as RELEASE_TARGET_LUFS,
        ROLE_TARGETS_LUFS,
        ROLE_ACCEPTANCE_RANGES_LUFS,
    )


PREMIX_LIMITER_INPUT_CEILING_DBTP = 6.0
# seq=19 C3 (2026-09-16): the release target moved from -16 to -14 LUFS; with the old -3.0 dBTP ceiling the
# LINEAR loudnorm could only add ~1.5 dB and E04 v2 landed at -15.1 (band -15..-13).  Align the ceiling with
# native_audio_loudness_contract.DEFAULT_TRUE_PEAK_CEILING_DBTP (-1.5 dBTP, release max -1.0).
FINAL_LOUDNORM_TRUE_PEAK_DBTP = -1.5
FINAL_LIMITER_LINEAR = 0.841395  # 10 ** (-1.5 / 20)
STATIC_TRUE_PEAK_LIMIT_LINEAR = 0.749894  # 10 ** (-2.5 / 20): --pre-levelled-units, oversampled, AAC headroom


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False)


def stream_hash(path: Path, stream: str) -> str:
    result = run([
        "ffmpeg", "-v", "error", "-i", str(path), "-map", stream,
        "-c", "copy", "-f", "hash", "-hash", "sha256", "-",
    ])
    if result.returncode:
        raise RuntimeError(result.stderr[-4000:])
    return result.stdout.strip().split("=", 1)[1]


MAX_REFINEMENT_PASSES = 12  # 2026-09-18 (nalu E06): 6 passes were not enough for a dialogue-heavy mix; same stop conditions


def unit_role(unit: dict) -> str:
    if any(str(row.get("dialogue") or "").strip() for row in unit["ordered_prompt_specs"]):
        return "DIALOGUE"
    if str(unit.get("action_classification") or "").upper() == "COMBAT":
        return "ACTION"
    acoustic_text = " ".join(
        [str(unit.get("narrative_beat") or "")]
        + [str(row.get("action") or "") for row in unit["ordered_prompt_specs"]]
    )
    if any(token in acoustic_text for token in ("哨响", "爆裂", "撞击", "破碎", "兵刃", "刀剑")):
        return "ACTION"
    return "AMBIENCE"


def voice_over_windows(placement_path: Path | None) -> list[tuple[float, float]]:
    """Release-timeline windows of V.O. narration mixed in at S7.

    Mixed-in narration is not provider-native audio, so it is accepted only with its
    sha-bound evidence chain (placement -> S4 manifest -> every wav); otherwise the
    leveller refuses to run (fail closed)."""
    if placement_path is None:
        return []
    try:
        from tools import voice_over_narration as vo
    except ImportError:
        import voice_over_narration as vo  # type: ignore
    failures = vo.binding_failures(placement_path)
    if failures:
        raise RuntimeError("VOICE_OVER_PLACEMENT_UNBOUND:" + ";".join(failures))
    return [(float(row["start"]), float(row["end"])) for row in vo.windows_from_placement(placement_path)]


def level_release(
    *, source: Path, timeline_path: Path, grouped_path: Path,
    output: Path, qa_path: Path, episode: str, version: str,
    expected_sha256: str | None = None,
    line_windows: list[dict] | None = None,
    line_band_lufs: tuple[float, float] = (-18.0, -12.0),
    line_target_lufs: float = -13.5,
    voice_over_placement: Path | None = None,
    pre_levelled_units: Path | None = None,
) -> dict:
    """``line_windows`` (seq=19 C3, 2026-09-17): dialogue windows [{start, end}] on the release timeline.
    After each render every window is measured (ebur128 on the OUTPUT); a window outside
    ``line_band_lufs`` gets a per-window gain toward ``line_target_lufs`` (clamped -8..+4 dB, applied
    inside its unit's premix before the program loudnorm) and the render is repeated.  This is line
    levelling a mixer would do by hand, not a threshold change: the band and the target are the
    release contract's.

    ``pre_levelled_units`` (CAMERA_GRAMMAR_V1, line owner 2026-10-27, lab E07): the units were already levelled
    before the AgentCut build (tools/s7_audio_smoothing.py, <EP>_UNIT_AUDIO_LEVELLING.json, +-6 dB).  Staging a
    second per-unit gain here (up to +24 dB) and per-line gain steps re-created the level jumps at every cut, and
    the loudnorm fell back to dynamic normalisation (pumping).  In this mode every unit keeps unity gain, no line
    gain is staged, and the program gain is one static gain + the final limiter, trimmed until the release lands
    on the target.  The unit / release evaluation is unchanged and recorded honestly."""
    # Never let a failed leveling run erase an approved release or its inputs.
    protected = {path.resolve() for path in (source, timeline_path, grouped_path)}
    if output.resolve() in protected or qa_path.resolve() in protected:
        raise ValueError("Audio leveling output must not overwrite an input")
    if output.resolve() == qa_path.resolve():
        raise ValueError("Media and QA output must use distinct paths")
    if output.exists() or qa_path.exists():
        raise FileExistsError("Use new versioned output and QA paths; existing evidence is immutable")
    if expected_sha256 and sha256(source) != expected_sha256:
        raise RuntimeError(f"{episode} source changed or is not the declared authority")
    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    grouped = json.loads(grouped_path.read_text(encoding="utf-8"))
    units = {row["unit_id"]: row for row in grouped["units"]}
    segments = timeline["segments"]
    content_runtime = float(timeline["content_runtime_seconds"])
    release_runtime = float(timeline["release_runtime_seconds"])

    # nalu e20b (2026-09-14): the static plan predicts each unit's premix loudness, but the premix
    # limiter and the per-segment gating shift the rendered result by several LU (E02: VU-001 landed
    # 4 LU above its prediction, VU-006 2 LU below).  Render, measure the OUTPUT per unit, and
    # refine the per-unit gain toward (role target + program gain) — up to 3 passes.
    narration = voice_over_windows(voice_over_placement)
    static_units = pre_levelled_units is not None
    if static_units:
        line_windows = None
    program_trim = 0.0
    measured_inputs = []
    for segment in segments:
        uid = segment["unit_id"]
        start, end = float(segment["output_start"]), float(segment["output_end"])
        role = unit_role(units[uid])
        if role != "DIALOGUE" and any(we > start and ws < end for ws, we in narration):
            role = "DIALOGUE"  # a unit carrying bound V.O. narration is levelled as speech
        measured_inputs.append((uid, start, end, role,
                                measure_loudness(source, start_seconds=start, duration_seconds=end - start)))
    outro_measured = measure_loudness(
        source, start_seconds=content_runtime, duration_seconds=release_runtime - content_runtime,
    )
    outro_plan = plan_static_gain(
        outro_measured["integrated_loudness_lufs"], outro_measured["true_peak_dbtp"], "MUSIC",
        true_peak_ceiling_dbtp=PREMIX_LIMITER_INPUT_CEILING_DBTP,
    )
    import json as _json, re as _re
    adjust: dict[str, float] = {}
    line_adjust: dict[str, float] = {}
    line_rows: list[dict] = []
    iterations = []
    for attempt in range(1, MAX_REFINEMENT_PASSES + 1):
        plans, filters, labels = [], [], []
        for index, (uid, start, end, role, measured) in enumerate(measured_inputs):
            quiet_ambience = role == "AMBIENCE" and float(measured["integrated_loudness_lufs"]) < -38.0
            plan = plan_static_gain(
                measured["integrated_loudness_lufs"], measured["true_peak_dbtp"], role,
                true_peak_ceiling_dbtp=PREMIX_LIMITER_INPUT_CEILING_DBTP,
                max_gain_db=24.0 if quiet_ambience else 12.0,
            )
            gain = 0.0 if static_units else float(plan["gain_db"]) + float(adjust.get(uid, 0.0))
            label = f"a{index}"
            line_filters = ""
            for win in (line_windows or []):
                ws, we = float(win["start"]), float(win["end"])
                key = f"{ws:.3f}-{we:.3f}"
                g = float(line_adjust.get(key, 0.0))
                if abs(g) < 0.05 or we <= start or ws >= end:
                    continue
                line_filters += (f"volume={g:.3f}dB:enable='between(t,{max(0.0, ws - start):.3f},"
                                 f"{min(end, we) - start:.3f})',")
            filters.append(
                f"[0:a]atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS,"
                f"aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                f"volume={gain:.3f}dB,{line_filters}alimiter=limit=0.841395:attack=5:release=50:level=false[{label}]"
            )
            labels.append(f"[{label}]")
            plans.append({
                "unit_id": uid, "role": role, "start_seconds": start, "end_seconds": end,
                "input": measured, "gain_plan": plan, "refinement_db": round(float(adjust.get(uid, 0.0)), 3),
                "applied_gain_db": round(gain, 3),
            })
        filters.append(
            f"[0:a]atrim=start={content_runtime:.6f}:end={release_runtime:.6f},asetpts=PTS-STARTPTS,"
            "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"volume={float(outro_plan['gain_db']):.3f}dB,"
            "alimiter=limit=0.841395:attack=5:release=50:level=false[aoutro]"
        )
        labels.append("[aoutro]")
        # two-pass LINEAR loudnorm (nalu e20): measure the premix once, apply a single program gain
        premix = "".join(labels) + f"concat=n={len(labels)}:v=0:a=1"
        probe = run([
            "ffmpeg", "-hide_banner", "-nostats", "-i", str(source), "-filter_complex_threads", "1",
            "-filter_complex", ";".join(filters + [premix + f",loudnorm=I={RELEASE_TARGET_LUFS:g}:TP={FINAL_LOUDNORM_TRUE_PEAK_DBTP}:LRA=11:print_format=json[aprobe]"]),
            "-map", "[aprobe]", "-f", "null", "-",
        ])
        match = _re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", probe.stderr or "", _re.S)
        if not match:
            raise RuntimeError("loudnorm first pass produced no statistics: " + (probe.stderr or "")[-2000:])
        stats = _json.loads(match.group(0))
        program_gain = RELEASE_TARGET_LUFS - float(stats["input_i"])
        linear = (
            f"loudnorm=I={RELEASE_TARGET_LUFS:g}:TP={FINAL_LOUDNORM_TRUE_PEAK_DBTP}:LRA=11:linear=true:"
            f"measured_I={float(stats['input_i']):.3f}:measured_LRA={float(stats['input_lra']):.3f}:"
            f"measured_TP={float(stats['input_tp']):.3f}:measured_thresh={float(stats['input_thresh']):.3f}:"
            f"offset={float(stats.get('target_offset') or 0.0):.3f}"
        )
        # True-peak limiting needs oversampling: at 48 kHz alimiter only sees sample peaks, and inter-sample
        # peaks after the AAC encode landed E12's re-cut release at -0.8 dBTP against a -1.0 ceiling
        # (2026-10-30).  Run the limiter 4x oversampled exactly as the static branch does.
        # Measured 2026-10-30 on the E12 release: the AAC encode overshoots the limited peak by 0.3–1.0 dB
        # (a -1.5 dB limit came out at -0.8 dBTP, -2.5 dB at -2.0), so the linear branch keeps the same
        # -2.5 dB AAC headroom the static branch already uses; integrated loudness is unaffected (-14.0/-14.1).
        linear = linear + ",aresample=192000"
        limiter = f"alimiter=limit={STATIC_TRUE_PEAK_LIMIT_LINEAR}:attack=5:release=50:level=false:latency=1,"
        if static_units:
            # static program gain; the limiter runs 4x oversampled (true peak) with headroom for the AAC encode
            linear = f"volume={program_gain + program_trim:.3f}dB,aresample=192000"
            limiter = f"alimiter=limit={STATIC_TRUE_PEAK_LIMIT_LINEAR}:attack=5:release=50:level=false:latency=1,"
        filters.append(
            premix + "," + linear + ","
            + limiter
            + f"aresample=48000,apad=whole_dur={release_runtime:.6f},"
            + f"atrim=duration={release_runtime:.6f},asetpts=N/SR/TB[aout]"
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        qa_path.parent.mkdir(parents=True, exist_ok=True)
        output.unlink(missing_ok=True)
        result = run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "warning", "-i", str(source),
            "-filter_complex_threads", "1", "-filter_complex", ";".join(filters),
            "-map", "0:v:0", "-map", "[aout]", "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", str(output),
        ])
        if result.returncode:
            output.unlink(missing_ok=True)
            raise RuntimeError(result.stderr[-12000:])
        output_units = []
        for row in plans:
            measured = measure_loudness(
                output, start_seconds=row["start_seconds"],
                duration_seconds=row["end_seconds"] - row["start_seconds"],
            )
            output_units.append({"unit_id": row["unit_id"], "role": row["role"], **measured})
        unit_tolerance = 0.5 if str(os.environ.get("NALU_POSTGEN_QA_PROFILE") or "").upper() == "WEAK" else 0.0
        unit_failures = evaluate_unit_loudness(output_units, role_range_tolerance_lu=unit_tolerance)
        errors = {}
        for row, out_row in zip(plans, output_units):
            desired = ROLE_TARGETS_LUFS[row["role"]] + program_gain
            # 2026-09-18 (nalu E06): with ~5 dB of program gain the staged dialogue target lands at -12.9,
            # ABOVE the -13 acceptance ceiling, so refinement steered dialogue out of band.  Steer toward
            # the staged target but never outside the role's acceptance band (0.3 LU inside the edges).
            lo, hi = ROLE_ACCEPTANCE_RANGES_LUFS.get(row["role"], (desired, desired))
            desired = min(max(desired, lo + 0.3), hi - 0.3)
            errors[row["unit_id"]] = round(float(out_row["integrated_loudness_lufs"]) - desired, 3)
        line_rows = []
        line_out_of_band = 0
        for win in (line_windows or []):
            ws, we = float(win["start"]), float(win["end"])
            if we - ws < 0.4:
                continue
            key = f"{ws:.3f}-{we:.3f}"
            got = measure_loudness(output, start_seconds=ws, duration_seconds=we - ws)
            lufs = got.get("integrated_loudness_lufs")
            row = {"start": ws, "end": we, "lufs_window": lufs, "applied_gain_db": round(float(line_adjust.get(key, 0.0)), 3)}
            if lufs is not None and not (line_band_lufs[0] <= float(lufs) <= line_band_lufs[1]):
                line_out_of_band += 1
                row["out_of_band"] = True
                proposed = float(line_adjust.get(key, 0.0)) + (line_target_lufs - float(lufs))
                line_adjust[key] = round(max(-8.0, min(4.0, proposed)), 3)
            line_rows.append(row)
        iterations.append({"attempt": attempt, "program_gain_db": round(program_gain, 3),
                           "unit_failures": unit_failures, "max_abs_error_lu": max(abs(v) for v in errors.values()),
                           "line_windows_out_of_band": line_out_of_band})
        if static_units:
            release_now = float(measure_loudness(output)["integrated_loudness_lufs"])
            iterations[-1].update(program_trim_db=round(program_trim, 3), release_integrated_lufs=release_now)
            if abs(release_now - RELEASE_TARGET_LUFS) <= 0.3 or attempt >= 4:
                break
            program_trim = round(program_trim + RELEASE_TARGET_LUFS - release_now, 3)
            continue
        if not unit_failures and not line_out_of_band:
            break
        if attempt == MAX_REFINEMENT_PASSES:
            break
        for uid, err in errors.items():
            if abs(err) > 0.5:
                adjust[uid] = round(float(adjust.get(uid, 0.0)) - err, 3)

    release_metrics = measure_loudness(output)
    unit_tolerance = 0.5 if str(os.environ.get("NALU_POSTGEN_QA_PROFILE") or "").upper() == "WEAK" else 0.0
    failures = evaluate_unit_loudness(output_units, role_range_tolerance_lu=unit_tolerance) + evaluate_release_loudness(release_metrics)
    source_video_hash = stream_hash(source, "0:v:0")
    output_video_hash = stream_hash(output, "0:v:0")
    if source_video_hash != output_video_hash:
        failures.append("VIDEO_ELEMENTARY_STREAM_CHANGED")
    probe = json.loads(run([
        "ffprobe", "-v", "error", "-show_format", "-of", "json", str(output)
    ]).stdout)
    decoded_duration = float(probe["format"]["duration"])
    if abs(decoded_duration - release_runtime) > 0.1:
        failures.append("RELEASE_DURATION_CHANGED")
    payload = {
        "schema": f"qingshan.{episode.lower()}.{version}.native_audio_loudness_qa.v1",
        "episode": episode, "created_at": now(),
        "status": "PASS_AUDIO_LEVEL_CORRECTED_PICTURE_BIT_EXACT" if not failures else "FAIL",
        "source_release": {"ref": str(source), "sha256": sha256(source)},
        "output_release": {"ref": str(output), "sha256": sha256(output)},
        "processing_scope": "LEVEL_ONLY_NATIVE_AUDIO_NO_DIALOGUE_REPLACEMENT_NO_PICTURE_CHANGE",
        "source_video_stream_sha256": source_video_hash,
        "output_video_stream_sha256": output_video_hash,
        "video_stream_bit_exact": source_video_hash == output_video_hash,
        "duration_seconds": decoded_duration,
        "unit_gain_plans": plans,
        "final_loudnorm": ({"mode": "STATIC_PROGRAM_GAIN_PRE_LEVELLED_UNITS", "first_pass_stats": stats,
                            "filter": linear, "pre_levelled_units": str(pre_levelled_units)}
                           if static_units else
                           {"mode": "TWO_PASS_LINEAR (nalu e20)", "first_pass_stats": stats, "filter": linear}),
        "refinement_iterations": iterations,
        "outro_gain_plan": {"input": outro_measured, "gain_plan": outro_plan},
        "output_unit_loudness": output_units, "release_loudness": release_metrics,
        "line_levelling": {"band_lufs": list(line_band_lufs), "target_lufs": line_target_lufs,
                           "windows": line_rows, "gains_db": line_adjust} if line_windows else None,
        "failures": failures,
    }
    if voice_over_placement is not None:
        payload["voice_over_narration"] = {
            "placement": str(voice_over_placement), "placement_sha256": sha256(voice_over_placement),
            "windows": [[round(ws, 3), round(we, 3)] for ws, we in narration],
            "binding": "PASS_SHA_BOUND_TO_S4_MANIFEST_AND_WAVS",
        }
    qa_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--timeline", type=Path, required=True)
    parser.add_argument("--grouped", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--qa", type=Path, required=True)
    parser.add_argument("--episode", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--line-windows", type=Path, help="dialogue windows [{start,end}] on the release timeline (seq=19 C3 line levelling)")
    parser.add_argument("--pre-levelled-units", type=Path,
                        help="CAMERA_GRAMMAR_V1 <EP>_UNIT_AUDIO_LEVELLING.json: units were levelled before the build; "
                             "stage no per-unit / per-line gain, static program gain only")
    parser.add_argument("--voice-over-placement", type=Path,
                        help="S7 <EP>_voice_over_placement.json; mixed-in narration must be sha-bound to the S4 manifest")
    args = parser.parse_args()
    payload = level_release(
        source=args.source.resolve(), timeline_path=args.timeline.resolve(),
        grouped_path=args.grouped.resolve(), output=args.output.resolve(),
        qa_path=args.qa.resolve(), episode=args.episode, version=args.version,
        expected_sha256=args.expected_sha256,
        line_windows=(json.loads(args.line_windows.read_text(encoding="utf-8"))
                      if args.line_windows and args.line_windows.is_file() else None),
        voice_over_placement=args.voice_over_placement.resolve() if args.voice_over_placement else None,
        pre_levelled_units=args.pre_levelled_units.resolve() if args.pre_levelled_units else None,
    )
    print(json.dumps({
        "status": payload["status"], "output": payload["output_release"],
        "release_loudness": payload["release_loudness"], "failures": payload["failures"],
    }, ensure_ascii=False))
    return 0 if payload["status"].startswith("PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
