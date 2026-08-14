#!/usr/bin/env python3
"""Render a video-only plan with source-frame-exact trims and no candidate audio."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from copy import deepcopy
from pathlib import Path


def run(command: list[str]) -> None:
    process = subprocess.run(command, text=True, capture_output=True)
    if process.returncode:
        raise SystemExit(process.stderr[-4000:])


def count_frames(ffmpeg: Path, video: Path) -> int:
    process = subprocess.run(
        [
            str(ffmpeg),
            "-v",
            "error",
            "-i",
            str(video),
            "-map",
            "0:v:0",
            "-f",
            "null",
            "-",
            "-progress",
            "pipe:1",
        ],
        text=True,
        capture_output=True,
    )
    if process.returncode:
        raise SystemExit(process.stderr[-4000:])
    frame_values = [
        int(line.split("=", 1)[1])
        for line in process.stdout.splitlines()
        if line.startswith("frame=")
    ]
    if not frame_values:
        raise SystemExit(f"Could not count frames in {video}: {process.stdout!r}")
    return frame_values[-1]


def write_report(output: Path, payload: dict) -> Path:
    report = output.with_suffix(".render.json")
    report.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def apply_transform_overrides(segments: list[dict], overrides: dict) -> list[dict]:
    allowed = {"crop_bottom_fraction", "eq_brightness", "day_for_night_strength"}
    result = deepcopy(segments)
    found: set[str] = set()
    for segment in result:
        source_id = segment["source_id"]
        values = overrides.get(source_id)
        if values is None:
            continue
        unknown = set(values) - allowed
        if unknown:
            raise ValueError(f"Unsupported transform overrides for {source_id}: {sorted(unknown)}")
        segment.update(values)
        found.add(source_id)
    missing = sorted(set(overrides) - found)
    if missing:
        raise ValueError(f"Transform override source IDs not present in plan: {missing}")
    return result


def build_frame_filter(segment: dict, facts: dict, fps: int) -> tuple[str, dict]:
    transforms: dict[str, float] = {}
    filters = [
        f"select=between(n\\,{facts['start_frame']}\\,{facts['end_frame'] - 1})",
        f"setpts=N/({fps}*TB)",
    ]

    crop_bottom_fraction = float(segment.get("crop_bottom_fraction", 0) or 0)
    if crop_bottom_fraction:
        if not 0 < crop_bottom_fraction < 0.5:
            raise ValueError(
                f"Invalid crop_bottom_fraction for {segment['source_id']}: "
                f"{crop_bottom_fraction}"
            )
        transforms["crop_bottom_fraction"] = crop_bottom_fraction
        filters.extend(
            [
                f"crop=iw:ih*(1-{crop_bottom_fraction:.4f}):0:0",
                "scale=720:1280:force_original_aspect_ratio=increase",
                "crop=720:1280",
            ]
        )
    else:
        filters.extend(
            [
                "scale=720:1280:force_original_aspect_ratio=decrease",
                "pad=720:1280:(ow-iw)/2:(oh-ih)/2:black",
            ]
        )

    eq_brightness = segment.get("eq_brightness")
    if eq_brightness is not None:
        value = float(eq_brightness)
        if not -0.35 <= value <= 0.35:
            raise ValueError(
                f"Invalid eq_brightness for {segment['source_id']}: {value}"
            )
        transforms["eq_brightness"] = value
        filters.append(f"eq=brightness={value:.4f}:contrast=1.0")

    day_for_night_strength = segment.get("day_for_night_strength")
    if day_for_night_strength is not None:
        strength = float(day_for_night_strength)
        if not 0 < strength <= 1:
            raise ValueError(
                f"Invalid day_for_night_strength for {segment['source_id']}: "
                f"{strength}"
            )
        transforms["day_for_night_strength"] = strength
        brightness = -0.16 * strength
        saturation = 1.0 - (0.30 * strength)
        blue_shadows = 0.14 * strength
        blue_midtones = 0.09 * strength
        blue_highlights = 0.04 * strength
        red_shadows = -0.06 * strength
        red_midtones = -0.04 * strength
        filters.extend(
            [
                f"eq=brightness={brightness:.4f}:contrast=1.0600:saturation={saturation:.4f}",
                (
                    "colorbalance="
                    f"bs={blue_shadows:.4f}:bm={blue_midtones:.4f}:bh={blue_highlights:.4f}:"
                    f"rs={red_shadows:.4f}:rm={red_midtones:.4f}"
                ),
            ]
        )

    filters.extend(["setsar=1", "format=yuv420p"])
    return ",".join(filters), transforms


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--transform-overrides")
    args = parser.parse_args()

    plan_path = Path(args.plan).resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    segments = plan.get("segments", [])
    override_path = None
    if args.transform_overrides:
        override_path = Path(args.transform_overrides).resolve()
        override_payload = json.loads(override_path.read_text(encoding="utf-8"))
        try:
            segments = apply_transform_overrides(
                segments,
                override_payload.get("overrides", override_payload),
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
    if not segments:
        raise SystemExit("Plan has no segments")

    ffmpeg = Path(args.ffmpeg).resolve()

    expected_frames = 0
    segment_frames = []
    for index, segment in enumerate(segments):
        path = Path(segment["path"]).resolve()
        if not path.is_file():
            raise SystemExit(f"Missing source: {path}")
        start_frame = round(float(segment["in_sec"]) * args.fps)
        frame_count = round(float(segment["duration_sec"]) * args.fps)
        end_frame = start_frame + frame_count
        expected_frames += frame_count
        segment_frames.append(
            {
                "index": index,
                "source_id": segment["source_id"],
                "path": str(path),
                "start_frame": start_frame,
                "end_frame": end_frame,
                "expected_frames": frame_count,
            }
        )

    output = Path(args.out).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="qingshan-frame-exact-") as temp_name:
        temp_dir = Path(temp_name)
        segment_outputs = []
        for segment, facts in zip(segments, segment_frames):
            segment_output = temp_dir / f"segment_{facts['index']:03d}.mp4"
            try:
                frame_filter, transforms = build_frame_filter(segment, facts, args.fps)
            except ValueError as exc:
                raise SystemExit(str(exc)) from exc
            facts["transforms_applied"] = transforms
            run(
                [
                    str(ffmpeg),
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(Path(segment["path"]).resolve()),
                    "-vf",
                    frame_filter,
                    "-frames:v",
                    str(facts["expected_frames"]),
                    "-r",
                    str(args.fps),
                    "-fps_mode",
                    "cfr",
                    "-an",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "20",
                    str(segment_output),
                ]
            )
            facts["actual_frames"] = count_frames(ffmpeg, segment_output)
            facts["actual_duration_seconds"] = facts["actual_frames"] / args.fps
            if facts["actual_frames"] != facts["expected_frames"]:
                payload = {
                    "schema": "qingshan.frame_exact_video_plan_render.v2",
                    "status": "FAIL_SEGMENT_FRAME_MISMATCH",
                    "plan": str(plan_path),
                    "output": str(output),
                    "fps": args.fps,
                    "expected_frames": expected_frames,
                    "candidate_audio_included": False,
                    "transform_overrides": str(override_path) if override_path else None,
                    "segments": segment_frames,
                }
                report = write_report(output, payload)
                raise SystemExit(
                    f"Segment {facts['index']} frame mismatch; report: {report}"
                )
            segment_outputs.append(segment_output)

        concat_file = temp_dir / "segments.ffconcat"
        concat_file.write_text(
            "ffconcat version 1.0\n"
            + "".join(f"file '{path.as_posix()}'\n" for path in segment_outputs),
            encoding="utf-8",
        )
        run(
            [
                str(ffmpeg),
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_file),
                "-map",
                "0:v:0",
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(output),
            ]
        )

    actual_frames = count_frames(ffmpeg, output)
    payload = {
        "schema": "qingshan.frame_exact_video_plan_render.v2",
        "status": "PASS" if actual_frames == expected_frames else "FAIL_OUTPUT_FRAME_MISMATCH",
        "plan": str(plan_path),
        "output": str(output),
        "fps": args.fps,
        "expected_frames": expected_frames,
        "actual_frames": actual_frames,
        "expected_duration_seconds": expected_frames / args.fps,
        "actual_duration_seconds": actual_frames / args.fps,
        "candidate_audio_included": False,
        "transform_overrides": str(override_path) if override_path else None,
        "segments": segment_frames,
    }
    report = write_report(output, payload)
    if actual_frames != expected_frames:
        raise SystemExit(f"Output frame mismatch; report: {report}")

    print(
        json.dumps(
            {
                "status": "PASS",
                "output": str(output),
                "frames": actual_frames,
                "duration": actual_frames / args.fps,
                "report": str(report),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
