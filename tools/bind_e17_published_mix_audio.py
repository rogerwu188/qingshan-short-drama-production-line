#!/usr/bin/env python3
"""Bind E17's approved published mix to a frame-exact picture diagnostic."""

from __future__ import annotations

import argparse
import array
import hashlib
import json
import math
import re
import subprocess
from pathlib import Path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audio_fingerprint(path: Path, ffmpeg: Path) -> str:
    process = subprocess.run(
        [
            str(ffmpeg),
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-c:a",
            "pcm_s16le",
            "-f",
            "hash",
            "-hash",
            "sha256",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    if process.returncode:
        raise RuntimeError(process.stderr[-4000:])
    match = re.search(r"SHA256=([0-9a-fA-F]{64})", process.stdout)
    if not match:
        raise RuntimeError("Audio fingerprint missing")
    return match.group(1).lower()


def crossfade_trim_points(
    cut_start: float, cut_end: float, crossfade_seconds: float
) -> tuple[float, float, float]:
    if cut_start < 0 or cut_end <= cut_start:
        raise ValueError("Invalid audio cut interval")
    if crossfade_seconds <= 0 or crossfade_seconds >= cut_end - cut_start:
        raise ValueError("Crossfade must be positive and shorter than the cut")
    left_end = cut_start + crossfade_seconds / 2
    right_start = cut_end - crossfade_seconds / 2
    effective_removed = (right_start - left_end) + crossfade_seconds
    return left_end, right_start, effective_removed


def parse_cut(value: str) -> tuple[float, float]:
    try:
        start_text, end_text = value.split(":", 1)
        return float(start_text), float(end_text)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("Cut must use START:END seconds") from exc


def normalized_cuts(
    cuts: list[tuple[float, float]], crossfade_seconds: float
) -> list[dict]:
    rows: list[dict] = []
    previous_end = -1.0
    removed_before = 0.0
    for cut_start, cut_end in sorted(cuts):
        if cut_start < previous_end:
            raise ValueError("Audio cut intervals must not overlap")
        left_end, right_start, effective_removed = crossfade_trim_points(
            cut_start, cut_end, crossfade_seconds
        )
        rows.append(
            {
                "cut_start": cut_start,
                "cut_end": cut_end,
                "cut_duration": cut_end - cut_start,
                "left_end": left_end,
                "right_start": right_start,
                "effective_removed": effective_removed,
                "output_seam_seconds": cut_start - removed_before,
            }
        )
        previous_end = cut_end
        removed_before += effective_removed
    return rows


def multi_cut_filter(cuts: list[dict], crossfade_seconds: float, target_seconds: float) -> str:
    filters: list[str] = []
    segment_labels: list[str] = []
    source_start = 0.0
    for index, row in enumerate(cuts):
        label = f"a{index}"
        filters.append(
            f"[1:a:0]atrim=start={source_start:.6f}:end={row['left_end']:.6f},"
            f"asetpts=PTS-STARTPTS[{label}]"
        )
        segment_labels.append(label)
        source_start = row["right_start"]
    final_label = f"a{len(cuts)}"
    filters.append(
        f"[1:a:0]atrim=start={source_start:.6f},asetpts=PTS-STARTPTS[{final_label}]"
    )
    segment_labels.append(final_label)

    current = segment_labels[0]
    for index, next_label in enumerate(segment_labels[1:], start=1):
        output_label = "aout" if index == len(segment_labels) - 1 else f"xf{index}"
        suffix = ""
        if output_label == "aout":
            suffix = (
                f",apad=pad_dur={target_seconds:.6f},"
                f"atrim=start=0:duration={target_seconds:.6f},asetpts=PTS-STARTPTS"
            )
        filters.append(
            f"[{current}][{next_label}]acrossfade=d={crossfade_seconds:.6f}:"
            f"c1=tri:c2=tri{suffix}[{output_label}]"
        )
        current = output_label
    return ";".join(filters)


def count_video_frames(ffmpeg: Path, path: Path) -> int:
    process = subprocess.run(
        [
            str(ffmpeg),
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-f",
            "null",
            "-",
            "-progress",
            "pipe:1",
        ],
        capture_output=True,
        text=True,
    )
    if process.returncode:
        raise RuntimeError(process.stderr[-4000:])
    values = [
        int(line.split("=", 1)[1])
        for line in process.stdout.splitlines()
        if line.startswith("frame=")
    ]
    if not values:
        raise RuntimeError("Frame count missing")
    return values[-1]


def media_duration(ffmpeg: Path, path: Path) -> float:
    process = subprocess.run(
        [str(ffmpeg), "-hide_banner", "-i", str(path)],
        capture_output=True,
        text=True,
    )
    match = re.search(
        r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", process.stderr + process.stdout
    )
    if not match:
        raise RuntimeError("Media duration missing")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def audio_seam_metrics(
    ffmpeg: Path, path: Path, seam_seconds: float, sample_rate: int = 48000
) -> dict:
    window_seconds = 0.5
    process = subprocess.run(
        [
            str(ffmpeg),
            "-v",
            "error",
            "-ss",
            f"{max(0.0, seam_seconds - window_seconds / 2):.6f}",
            "-i",
            str(path),
            "-t",
            f"{window_seconds:.6f}",
            "-map",
            "0:a:0",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-f",
            "s16le",
            "-",
        ],
        capture_output=True,
    )
    if process.returncode:
        raise RuntimeError(process.stderr.decode(errors="replace")[-4000:])
    samples = array.array("h")
    samples.frombytes(process.stdout)
    if not samples:
        raise RuntimeError("Audio seam samples missing")
    center = min(len(samples) - 1, round(window_seconds / 2 * sample_rate))
    neighborhood = max(2, round(0.005 * sample_rate))
    local = samples[max(0, center - neighborhood) : center + neighborhood + 1]
    local_deltas = [abs(local[index] - local[index - 1]) for index in range(1, len(local))]
    all_deltas = [
        abs(samples[index] - samples[index - 1]) for index in range(1, len(samples))
    ]
    rms_width = max(2, round(0.05 * sample_rate))
    pre = samples[max(0, center - rms_width) : center]
    post = samples[center : min(len(samples), center + rms_width)]

    def normalized_rms(values: array.array | list[int]) -> float:
        if not values:
            return 0.0
        return math.sqrt(sum(value * value for value in values) / len(values)) / 32768.0

    return {
        "window_seconds": [round(seam_seconds - 0.25, 6), round(seam_seconds + 0.25, 6)],
        "sample_rate": sample_rate,
        "center_sample_abs_delta_normalized": round(
            abs(samples[center] - samples[center - 1]) / 32768.0, 8
        ),
        "local_5ms_max_abs_delta_normalized": round(max(local_deltas) / 32768.0, 8),
        "window_max_abs_delta_normalized": round(max(all_deltas) / 32768.0, 8),
        "pre_50ms_rms_normalized": round(normalized_rms(pre), 8),
        "post_50ms_rms_normalized": round(normalized_rms(post), 8),
        "disposition": "MACHINE_MEASURE_ONLY_WATCH_LISTEN_STILL_REQUIRED",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--picture", required=True)
    parser.add_argument("--published-mix", required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--expected-published-mix-sha256", required=True)
    parser.add_argument("--expected-published-mix-audio-fingerprint", required=True)
    parser.add_argument("--cut-start", type=float, default=9.725)
    parser.add_argument("--cut-end", type=float, default=15.1)
    parser.add_argument(
        "--cut",
        action="append",
        type=parse_cut,
        help="Repeatable START:END cut in published-mix source seconds. Overrides legacy cut-start/cut-end.",
    )
    parser.add_argument("--crossfade-seconds", type=float, default=0.08)
    parser.add_argument("--target-seconds", type=float, default=165.25)
    parser.add_argument("--expected-frames", type=int, default=3966)
    args = parser.parse_args()

    picture = Path(args.picture).resolve()
    published_mix = Path(args.published_mix).resolve()
    ffmpeg = Path(args.ffmpeg).resolve()
    output = Path(args.out).resolve()
    for path in (picture, published_mix, ffmpeg):
        if not path.is_file():
            raise SystemExit(f"Missing input: {path}")

    actual_source_sha = file_sha256(published_mix)
    actual_source_audio_fingerprint = audio_fingerprint(published_mix, ffmpeg)
    if actual_source_sha != args.expected_published_mix_sha256.lower():
        raise SystemExit("Published mix file SHA-256 mismatch")
    if (
        actual_source_audio_fingerprint
        != args.expected_published_mix_audio_fingerprint.lower()
    ):
        raise SystemExit("Published mix audio fingerprint mismatch")

    requested_cuts = args.cut or [(args.cut_start, args.cut_end)]
    try:
        cuts = normalized_cuts(requested_cuts, args.crossfade_seconds)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    for row in cuts:
        if abs(row["effective_removed"] - row["cut_duration"]) > 1e-9:
            raise SystemExit("Crossfade trim arithmetic does not preserve the approved cut")

    output.parent.mkdir(parents=True, exist_ok=True)
    filter_complex = multi_cut_filter(cuts, args.crossfade_seconds, args.target_seconds)
    command = [
        str(ffmpeg),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(picture),
        "-i",
        str(published_mix),
        "-filter_complex",
        filter_complex,
        "-map",
        "0:v:0",
        "-map",
        "[aout]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        str(output),
    ]
    process = subprocess.run(command, capture_output=True, text=True)
    if process.returncode:
        raise SystemExit(process.stderr[-4000:])

    actual_frames = count_video_frames(ffmpeg, output)
    actual_duration = media_duration(ffmpeg, output)
    output_audio_fingerprint = audio_fingerprint(output, ffmpeg)
    failures: list[str] = []
    if actual_frames != args.expected_frames:
        failures.append(f"frame_count:{actual_frames}!={args.expected_frames}")
    if abs(actual_duration - args.target_seconds) > 0.02:
        failures.append(f"duration:{actual_duration}!={args.target_seconds}")

    report = {
        "schema": "qingshan.e17_published_mix_alignment_render.v1",
        "episode": "E17",
        "status": "PASS_LOCAL_ALIGNMENT_DIAGNOSTIC" if not failures else "FAIL",
        "final_admission": False,
        "picture": str(picture),
        "published_mix": {
            "path": str(published_mix),
            "file_sha256": actual_source_sha,
            "audio_fingerprint": actual_source_audio_fingerprint,
            "candidate_audio_used": False,
        },
        "audio_edit": {
            "approved_cut_seconds": [cuts[0]["cut_start"], cuts[0]["cut_end"]],
            "approved_cut_duration_seconds": cuts[0]["cut_duration"],
            "crossfade_seconds": args.crossfade_seconds,
            "left_trim_end_seconds": cuts[0]["left_end"],
            "right_trim_start_seconds": cuts[0]["right_start"],
            "effective_removed_seconds": cuts[0]["effective_removed"],
            "output_crossfade_window_seconds": [
                round(cuts[0]["output_seam_seconds"] - args.crossfade_seconds / 2, 6),
                round(cuts[0]["output_seam_seconds"] + args.crossfade_seconds / 2, 6),
            ],
            "audio_retime": False,
        },
        "audio_edits": [
            {
                "approved_cut_seconds": [row["cut_start"], row["cut_end"]],
                "approved_cut_duration_seconds": row["cut_duration"],
                "crossfade_seconds": args.crossfade_seconds,
                "left_trim_end_seconds": row["left_end"],
                "right_trim_start_seconds": row["right_start"],
                "effective_removed_seconds": row["effective_removed"],
                "output_seam_seconds": row["output_seam_seconds"],
                "audio_retime": False,
            }
            for row in cuts
        ],
        "output": {
            "path": str(output),
            "file_sha256": file_sha256(output),
            "audio_fingerprint": output_audio_fingerprint,
            "expected_frames": args.expected_frames,
            "actual_frames": actual_frames,
            "expected_duration_seconds": args.target_seconds,
            "actual_duration_seconds": actual_duration,
            "has_audio": True,
        },
        "audio_seam_metrics": [
            audio_seam_metrics(
                ffmpeg, output, row["output_seam_seconds"], sample_rate=48000
            )
            for row in cuts
        ],
        "failures": failures,
        "remaining_gates": [
            "FULL_REALTIME_WATCH_LISTEN",
            "DIALOGUE_PICTURE_ALIGNMENT_REVIEW",
            "FINAL_SCENE_BRIGHTNESS",
            "FINAL_OCR",
            "FINAL_REGRESSION_CI",
        ],
    }
    report_path = output.with_suffix(".alignment.json")
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": report["status"], "report": str(report_path)}))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
