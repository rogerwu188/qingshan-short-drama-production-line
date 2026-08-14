#!/usr/bin/env python3
"""Build an E17 real-ambience diagnostic over audited digital-zero windows."""

from __future__ import annotations

import argparse
import array
import hashlib
import json
import math
import re
import subprocess
from pathlib import Path


DIAGNOSTIC_TOKEN = "DIAGNOSTIC_NOT_FINAL"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_output_path(path: Path) -> None:
    if path.suffix.lower() != ".wav":
        raise ValueError("Diagnostic output must be a WAV file")
    if DIAGNOSTIC_TOKEN not in path.name.upper():
        raise ValueError(f"Diagnostic output name must contain {DIAGNOSTIC_TOKEN}")


def merge_windows(
    windows: list[tuple[float, float]], tolerance: float = 0.002
) -> list[tuple[float, float]]:
    merged: list[list[float]] = []
    for start, end in sorted(windows):
        if end <= start:
            raise ValueError(f"Invalid window: {start}-{end}")
        if merged and start <= merged[-1][1] + tolerance:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def map_interval_after_cut(
    start: float, end: float, cut_start: float, cut_end: float
) -> list[tuple[float, float]]:
    if cut_start < 0 or cut_end <= cut_start:
        raise ValueError("Invalid cut interval")
    removed = cut_end - cut_start
    mapped: list[tuple[float, float]] = []
    if start < cut_start:
        mapped.append((start, min(end, cut_start)))
    if end > cut_end:
        mapped.append((max(start, cut_end) - removed, end - removed))
    return [(left, right) for left, right in mapped if right > left]


def alignment_cuts(alignment: dict) -> list[tuple[float, float]]:
    edits = alignment.get("audio_edits")
    if edits:
        return [
            tuple(float(value) for value in edit["approved_cut_seconds"])
            for edit in edits
        ]
    return [
        tuple(float(value) for value in alignment["audio_edit"]["approved_cut_seconds"])
    ]


def map_interval_after_cuts(
    start: float, end: float, cuts: list[tuple[float, float]]
) -> list[tuple[float, float]]:
    if end <= start:
        raise ValueError("Invalid source interval")
    cursor = start
    removed_before = 0.0
    mapped: list[tuple[float, float]] = []
    previous_end = -1.0
    for cut_start, cut_end in sorted(cuts):
        if cut_start < previous_end or cut_start < 0 or cut_end <= cut_start:
            raise ValueError("Invalid or overlapping cut intervals")
        previous_end = cut_end
        removed = cut_end - cut_start
        if cut_end <= cursor:
            removed_before += removed
            continue
        if cut_start >= end:
            break
        if cursor < cut_start:
            mapped.append(
                (cursor - removed_before, min(end, cut_start) - removed_before)
            )
        cursor = max(cursor, cut_end)
        removed_before += removed
    if cursor < end:
        mapped.append((cursor - removed_before, end - removed_before))
    return [(left, right) for left, right in mapped if right > left]


def mapped_digital_zero_windows(
    audit: dict, alignment: dict
) -> list[tuple[float, float]]:
    rows = audit.get("digital_zero_shots") or []
    if not rows:
        raise ValueError("Audit has no digital_zero_shots")
    cuts = alignment_cuts(alignment)
    target = float(alignment["output"]["expected_duration_seconds"])
    original = merge_windows(
        [(float(row["start_sec"]), float(row["end_sec"])) for row in rows]
    )
    mapped: list[tuple[float, float]] = []
    for start, end in original:
        mapped.extend(map_interval_after_cuts(start, end, cuts))
    clamped = [(max(0.0, start), min(target, end)) for start, end in mapped]
    return merge_windows([(start, end) for start, end in clamped if end > start])


def media_duration(ffmpeg: Path, path: Path) -> float:
    process = subprocess.run(
        [str(ffmpeg), "-hide_banner", "-i", str(path)],
        capture_output=True,
        text=True,
    )
    match = re.search(
        r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)",
        process.stderr + process.stdout,
    )
    if not match:
        raise RuntimeError(f"Media duration missing for {path}")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def map_audit_rows(
    rows: list[dict], alignment: dict
) -> list[tuple[float, float]]:
    cuts = alignment_cuts(alignment)
    target = float(alignment["output"]["expected_duration_seconds"])
    original = merge_windows(
        [(float(row["start_sec"]), float(row["end_sec"])) for row in rows]
    )
    mapped: list[tuple[float, float]] = []
    for start, end in original:
        mapped.extend(map_interval_after_cuts(start, end, cuts))
    clamped = [(max(0.0, start), min(target, end)) for start, end in mapped]
    return merge_windows([(start, end) for start, end in clamped if end > start])


def detect_silence_windows(
    ffmpeg: Path,
    source: Path,
    target_seconds: float,
    threshold_db: float = -80.0,
    minimum_seconds: float = 0.5,
) -> list[tuple[float, float]]:
    process = subprocess.run(
        [
            str(ffmpeg),
            "-hide_banner",
            "-i",
            str(source),
            "-af",
            f"silencedetect=noise={threshold_db:.3f}dB:d={minimum_seconds:.3f}",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    if process.returncode:
        raise RuntimeError(process.stderr[-4000:])
    events = re.findall(
        r"silence_(start|end):\s*([0-9]+(?:\.[0-9]+)?)",
        process.stderr + process.stdout,
    )
    windows: list[tuple[float, float]] = []
    open_start: float | None = None
    for kind, value in events:
        seconds = float(value)
        if kind == "start":
            open_start = seconds
        elif open_start is not None:
            windows.append((open_start, min(seconds, target_seconds)))
            open_start = None
    if open_start is not None and open_start < target_seconds:
        windows.append((open_start, target_seconds))
    return merge_windows([(start, end) for start, end in windows if end > start])


def overlap_seconds(left: tuple[float, float], right: tuple[float, float]) -> float:
    return max(0.0, min(left[1], right[1]) - max(left[0], right[0]))


def verified_fill_windows(
    audit: dict,
    alignment: dict,
    measured_silence: list[tuple[float, float]],
    safety_margin_seconds: float = 0.02,
) -> list[tuple[float, float]]:
    audited_silence = map_audit_rows(
        audit.get("unmotivated_silence_segments") or [], alignment
    )
    if not audited_silence:
        raise ValueError("Audit has no unmotivated_silence_segments")
    verified: list[tuple[float, float]] = []
    for audit_match in audited_silence:
        measured_match = max(
            measured_silence,
            key=lambda window: overlap_seconds(audit_match, window),
        )
        if overlap_seconds(audit_match, measured_match) <= 0:
            raise ValueError(
                f"Target audio does not confirm audited silence {audit_match}"
            )
        start = max(audit_match[0], measured_match[0]) + safety_margin_seconds
        end = min(audit_match[1], measured_match[1]) - safety_margin_seconds
        if end <= start:
            raise ValueError(
                f"Verified silence intersection is empty at {audit_match}"
            )
        verified.append((round(start, 6), round(end, 6)))
    return merge_windows(verified)


def build_filter_graph(
    target_seconds: float,
    ambience_loop_samples: int,
    windows: list[tuple[float, float]],
    gain_db: float,
    window_fade_seconds: float,
) -> str:
    if not windows:
        raise ValueError("At least one digital-zero window is required")
    envelopes: list[str] = []
    for start, end in windows:
        duration = end - start
        fade = min(window_fade_seconds, duration / 4)
        fade_in_end = start + fade
        fade_out_start = end - fade
        envelopes.append(
            f"if(between(t,{start:.6f},{fade_in_end:.6f}),"
            f"(t-{start:.6f})/{fade:.6f},"
            f"if(between(t,{fade_in_end:.6f},{fade_out_start:.6f}),1,"
            f"if(between(t,{fade_out_start:.6f},{end:.6f}),"
            f"({end:.6f}-t)/{fade:.6f},0)))"
        )
    gate = "+".join(f"({expression})" for expression in envelopes)
    graph = [
        (
            f"[0:a:0]aresample=48000,"
            f"aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"atrim=start=0:duration={target_seconds:.6f},"
            "asetpts=PTS-STARTPTS[src]"
        ),
        (
            "[1:a:0]aresample=48000,"
            "aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"aloop=loop=-1:size={ambience_loop_samples}:start=0,"
            f"atrim=start=0:duration={target_seconds:.6f},"
            "asetpts=PTS-STARTPTS,"
            f"volume={gain_db:.3f}dB,"
            f"aeval=exprs='val(0)*({gate})|val(1)*({gate})'[gatedbed]"
        ),
    ]
    graph.append(
        f"[src][gatedbed]amix=inputs=2:normalize=0:duration=first,"
        f"atrim=start=0:duration={target_seconds:.6f}[out]"
    )
    return ";".join(graph)


def decode_f32(ffmpeg: Path, path: Path, target_seconds: float) -> array.array:
    process = subprocess.run(
        [
            str(ffmpeg),
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-t",
            f"{target_seconds:.6f}",
            "-ac",
            "2",
            "-ar",
            "48000",
            "-f",
            "f32le",
            "-",
        ],
        capture_output=True,
    )
    if process.returncode:
        raise RuntimeError(process.stderr.decode(errors="replace")[-4000:])
    samples = array.array("f")
    samples.frombytes(process.stdout)
    return samples


def rms_db(samples: list[float] | array.array) -> float:
    if not samples:
        return -120.0
    mean_square = sum(float(value) * float(value) for value in samples) / len(samples)
    if mean_square <= 1e-24:
        return -120.0
    return max(-120.0, 20 * math.log10(math.sqrt(mean_square)))


def analyze_render(
    source_samples: array.array,
    output_samples: array.array,
    windows: list[tuple[float, float]],
    sample_rate: int = 48000,
    channels: int = 2,
) -> dict:
    sample_count = min(len(source_samples), len(output_samples))
    window_metrics = []
    covered: list[tuple[int, int]] = []
    failures: list[str] = []
    for index, (start, end) in enumerate(windows):
        left = max(0, round(start * sample_rate) * channels)
        right = min(sample_count, round(end * sample_rate) * channels)
        covered.append((left, right))
        source_window = source_samples[left:right]
        output_window = output_samples[left:right]
        source_level = rms_db(source_window)
        output_level = rms_db(output_window)
        delta_level = rms_db(
            [float(output_window[i]) - float(source_window[i]) for i in range(len(source_window))]
        )
        disposition = "PASS"
        if source_level > -80.0:
            disposition = "FAIL_SOURCE_NOT_DIGITAL_ZERO"
            failures.append(f"window_{index + 1}_source_rms:{source_level:.2f}")
        if not -70.0 <= output_level <= -35.0:
            disposition = "FAIL_OUTPUT_NOT_LOW_LEVEL_REAL_AMBIENCE"
            failures.append(f"window_{index + 1}_output_rms:{output_level:.2f}")
        window_metrics.append(
            {
                "window_index": index + 1,
                "start_sec": round(start, 6),
                "end_sec": round(end, 6),
                "source_rms_dbfs": round(source_level, 3),
                "output_rms_dbfs": round(output_level, 3),
                "inserted_ambience_rms_dbfs": round(delta_level, 3),
                "status": disposition,
            }
        )

    max_delta = 0.0
    delta_square_sum = 0.0
    delta_count = 0
    cursor = 0
    for left, right in covered + [(sample_count, sample_count)]:
        for position in range(cursor, left):
            delta = abs(float(output_samples[position]) - float(source_samples[position]))
            max_delta = max(max_delta, delta)
            delta_square_sum += delta * delta
            delta_count += 1
        cursor = max(cursor, right)
    outside_rms = math.sqrt(delta_square_sum / delta_count) if delta_count else 0.0
    if max_delta > 2e-6:
        failures.append(f"outside_window_max_delta:{max_delta:.9f}")
    if outside_rms > 2e-7:
        failures.append(f"outside_window_rms_delta:{outside_rms:.9f}")
    return {
        "status": "PASS" if not failures else "FAIL",
        "window_metrics": window_metrics,
        "outside_window_preservation": {
            "max_abs_sample_delta": round(max_delta, 10),
            "rms_sample_delta": round(outside_rms, 10),
            "max_allowed": 0.000002,
            "rms_allowed": 0.0000002,
            "status": "PASS" if max_delta <= 2e-6 and outside_rms <= 2e-7 else "FAIL",
        },
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-audio", required=True)
    parser.add_argument("--ambience", required=True)
    parser.add_argument("--audit", required=True)
    parser.add_argument("--alignment-report", required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--gain-db", type=float, default=9.0)
    parser.add_argument("--window-fade-seconds", type=float, default=0.15)
    args = parser.parse_args()

    source = Path(args.source_audio).resolve()
    ambience = Path(args.ambience).resolve()
    audit_path = Path(args.audit).resolve()
    alignment_path = Path(args.alignment_report).resolve()
    ffmpeg = Path(args.ffmpeg).resolve()
    output = Path(args.out).resolve()
    validate_output_path(output)
    for path in (source, ambience, audit_path, alignment_path, ffmpeg):
        if not path.is_file():
            raise SystemExit(f"Missing input: {path}")
    if not -6.0 <= args.gain_db <= 18.0:
        raise SystemExit("gain-db must remain within the low-level diagnostic range")

    audit = load_json(audit_path)
    alignment = load_json(alignment_path)
    if audit.get("schema") != "qingshan.audio_bed_continuity.v1":
        raise SystemExit("Unexpected continuity-audit schema")
    if alignment.get("final_admission") is not False:
        raise SystemExit("Alignment input must be a non-final diagnostic")
    expected_source_sha = alignment["output"]["file_sha256"]
    actual_source_sha = file_sha256(source)
    if actual_source_sha != expected_source_sha:
        raise SystemExit("Aligned source SHA-256 does not match alignment report")

    target_seconds = float(alignment["output"]["expected_duration_seconds"])
    ambience_seconds = media_duration(ffmpeg, ambience)
    measured_silence = detect_silence_windows(
        ffmpeg, source, target_seconds, threshold_db=-80.0, minimum_seconds=0.5
    )
    anchor_windows = mapped_digital_zero_windows(audit, alignment)
    audited_silence_windows = map_audit_rows(
        audit.get("unmotivated_silence_segments") or [], alignment
    )
    windows = verified_fill_windows(audit, alignment, measured_silence)
    ambience_loop_samples = round(ambience_seconds * 48000)
    graph = build_filter_graph(
        target_seconds,
        ambience_loop_samples,
        windows,
        args.gain_db,
        args.window_fade_seconds,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(ffmpeg),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-i",
        str(ambience),
        "-filter_complex",
        graph,
        "-map",
        "[out]",
        "-c:a",
        "pcm_s24le",
        "-ar",
        "48000",
        "-ac",
        "2",
        str(output),
    ]
    process = subprocess.run(command, capture_output=True, text=True)
    if process.returncode:
        raise SystemExit(process.stderr[-4000:])

    actual_duration = media_duration(ffmpeg, output)
    source_samples = decode_f32(ffmpeg, source, target_seconds)
    output_samples = decode_f32(ffmpeg, output, target_seconds)
    qa = analyze_render(source_samples, output_samples, windows)
    failures = list(qa["failures"])
    remaining_long_silence = detect_silence_windows(
        ffmpeg,
        output,
        target_seconds,
        threshold_db=-60.0,
        minimum_seconds=1.0,
    )
    if remaining_long_silence:
        failures.extend(
            f"remaining_silence_over_1s:{start:.6f}-{end:.6f}"
            for start, end in remaining_long_silence
        )
    if abs(actual_duration - target_seconds) > 0.02:
        failures.append(f"duration:{actual_duration}!={target_seconds}")
    status = "PASS_DIAGNOSTIC_NOT_FINAL" if not failures else "FAIL_DIAGNOSTIC"
    provenance = {
        "schema": "qingshan.e17_real_ambience_bed_diagnostic.v1",
        "episode": "E17",
        "status": status,
        "final_admission": False,
        "diagnostic_only": True,
        "candidate_audio_used": False,
        "synthetic_audio_used": False,
        "generated_noise_used": False,
        "source_audio": {
            "path": str(source),
            "sha256": actual_source_sha,
            "contract": "EXISTING_FRAME_EXACT_PUBLISHED_MIX_ALIGNMENT_DIAGNOSTIC",
        },
        "ambience_source": {
            "path": str(ambience),
            "sha256": file_sha256(ambience),
            "duration_seconds": ambience_seconds,
            "asset_type": "REAL_RECORDED_AMBIENCE_REFERENCE",
            "processing": [
                "resample_to_48000_stereo",
                "sample_exact_aloop_of_the_same_real_recording_without_generated_fill",
                f"gain_{args.gain_db:+.3f}_db",
                "fade_only_at_audited_window_boundaries",
                "mix_only_inside_audit_anchored_and_target_measured_digital_zero_windows",
            ],
        },
        "window_derivation": {
            "audit_path": str(audit_path),
            "audit_sha256": file_sha256(audit_path),
            "alignment_report_path": str(alignment_path),
            "alignment_report_sha256": file_sha256(alignment_path),
            "source_digital_zero_rows": len(audit["digital_zero_shots"]),
            "mapped_digital_zero_anchor_windows": [
                {"start_sec": round(start, 6), "end_sec": round(end, 6)}
                for start, end in anchor_windows
            ],
            "mapped_audited_silence_windows": [
                {"start_sec": round(start, 6), "end_sec": round(end, 6)}
                for start, end in audited_silence_windows
            ],
            "target_audio_measured_silence_windows": [
                {"start_sec": round(start, 6), "end_sec": round(end, 6)}
                for start, end in measured_silence
            ],
            "mapped_merged_windows": [
                {"start_sec": round(start, 6), "end_sec": round(end, 6)}
                for start, end in windows
            ],
            "approved_removed_interval_seconds": alignment["audio_edit"]["approved_cut_seconds"],
            "approved_removed_intervals_seconds": [
                list(cut) for cut in alignment_cuts(alignment)
            ],
            "target_silence_detection_threshold_dbfs": -80.0,
            "target_silence_detection_minimum_seconds": 0.5,
            "verified_window_safety_margin_seconds": 0.02,
            "repeat_method": "FFMPEG_AUDIO_FILTER_ALOOP_REAL_SOURCE_ONLY",
            "ambience_loop_samples_per_channel": ambience_loop_samples,
            "window_fade_seconds": args.window_fade_seconds,
        },
        "output": {
            "path": str(output),
            "sha256": file_sha256(output),
            "codec": "pcm_s24le",
            "sample_rate": 48000,
            "channels": 2,
            "expected_duration_seconds": target_seconds,
            "actual_duration_seconds": actual_duration,
            "overwrites_final": False,
        },
        "qa": {
            **qa,
            "window_level_silence_gate": {
                "threshold_dbfs": -60.0,
                "minimum_seconds": 1.0,
                "remaining_windows": [
                    {"start_sec": round(start, 6), "end_sec": round(end, 6)}
                    for start, end in remaining_long_silence
                ],
                "status": "PASS" if not remaining_long_silence else "FAIL",
            },
            "failures": failures,
        },
        "remaining_gate": "FULL_REALTIME_WATCH_LISTEN_BEFORE_ANY_NON_DIAGNOSTIC_USE",
    }
    report_path = output.with_suffix(".provenance.json")
    report_path.write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"status": status, "output": str(output), "provenance": str(report_path)}
        )
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
