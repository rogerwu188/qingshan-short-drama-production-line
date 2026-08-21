#!/usr/bin/env python3
"""Render a duration-checked audio master from an AgentCut project."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

try:
    from tools.audio_postproduction_contract import (
        REQUIRED_SAMPLE_RATE_HZ,
        validate_audio_profile,
    )
except ModuleNotFoundError:  # Direct execution from tools/.
    from audio_postproduction_contract import (  # type: ignore
        REQUIRED_SAMPLE_RATE_HZ,
        validate_audio_profile,
    )

try:
    from tools.sound_cue_contract import evaluate as evaluate_sound_cues
except ModuleNotFoundError:  # Direct execution from tools/.
    from sound_cue_contract import evaluate as evaluate_sound_cues  # type: ignore


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, text=True, capture_output=True)


def probe_duration(ffprobe: str, path: Path) -> float:
    result = run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
    )
    return float(result.stdout.strip())


def probe_sample_rate(ffprobe: str, path: Path) -> int:
    result = run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=sample_rate",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
    )
    return int(result.stdout.strip())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    args = parser.parse_args()

    project = json.loads(args.project.read_text())
    profile_failures = validate_audio_profile(project)
    if profile_failures:
        raise SystemExit("audio profile contract failed: " + ", ".join(profile_failures))
    sound_report = evaluate_sound_cues(project)
    if sound_report["status"] != "PASS":
        raise SystemExit("sound cue contract failed: " + ", ".join(sound_report["failures"]))
    audio_clips = [
        clip
        for track in project["timeline"].get("audioTracks", [])
        for clip in track.get("clips", [])
    ]
    video_ends = [
        float(clip["start"]) + float(clip["duration"])
        for track in project["timeline"].get("videoTracks", [])
        for clip in track.get("clips", [])
    ]
    audio_ends = [float(clip["start"]) + float(clip["duration"]) for clip in audio_clips]
    duration = max(video_ends + audio_ends)
    if not audio_clips:
        raise SystemExit("project has no audio clips")

    command = [args.ffmpeg, "-hide_banner", "-y"]
    for clip in audio_clips:
        command.extend(
            [
                "-ss",
                f"{float(clip.get('in', 0.0)):.6f}",
                "-t",
                f"{float(clip['duration']):.6f}",
                "-i",
                str(clip["source"]),
            ]
        )

    filters: list[str] = []
    mix_labels: list[str] = []
    for index, clip in enumerate(audio_clips):
        clip_duration = float(clip["duration"])
        start_ms = round(float(clip["start"]) * 1000)
        volume = float(clip.get("volume", 1.0))
        transition_in = min(float(clip.get("transitionIn", {}).get("duration", 0.0)), clip_duration / 2)
        transition_out = min(float(clip.get("transitionOut", {}).get("duration", 0.0)), clip_duration / 2)
        chain = [
            f"aresample={REQUIRED_SAMPLE_RATE_HZ}:async=1:first_pts=0",
            "aformat=sample_fmts=fltp:channel_layouts=stereo",
            f"atrim=duration={clip_duration:.6f}",
            "asetpts=N/SR/TB",
        ]
        if transition_in > 0:
            chain.append(f"afade=t=in:st=0:d={transition_in:.6f}")
        if transition_out > 0:
            fade_start = max(0.0, clip_duration - transition_out)
            chain.append(f"afade=t=out:st={fade_start:.6f}:d={transition_out:.6f}")
        chain.extend([f"volume={volume:.8f}", f"adelay={start_ms}:all=1"])
        label = f"a{index}"
        filters.append(f"[{index}:a]{','.join(chain)}[{label}]")
        mix_labels.append(f"[{label}]")

    filters.append(
        "".join(mix_labels)
        + f"amix=inputs={len(mix_labels)}:duration=longest:normalize=0,"
        + f"aresample={REQUIRED_SAMPLE_RATE_HZ}:async=1:first_pts=0,"
        + f"loudnorm=I=-16:TP=-1.5:LRA=11,aresample={REQUIRED_SAMPLE_RATE_HZ},"
        + f"apad=whole_dur={duration:.6f},atrim=duration={duration:.6f},asetpts=N/SR/TB[aout]"
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[aout]",
            "-ar",
            str(REQUIRED_SAMPLE_RATE_HZ),
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            str(args.output),
        ]
    )

    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode != 0:
        args.output.unlink(missing_ok=True)
        raise SystemExit(result.stderr[-6000:])

    rendered_duration = probe_duration(args.ffprobe, args.output)
    rendered_sample_rate = probe_sample_rate(args.ffprobe, args.output)
    delta = abs(rendered_duration - duration)
    if delta > 0.1:
        args.output.unlink(missing_ok=True)
        raise SystemExit(f"audio duration gate failed: {rendered_duration:.6f} vs {duration:.6f}")
    if rendered_sample_rate != REQUIRED_SAMPLE_RATE_HZ:
        args.output.unlink(missing_ok=True)
        raise SystemExit(
            f"audio sample-rate gate failed: {rendered_sample_rate} vs {REQUIRED_SAMPLE_RATE_HZ}"
        )

    report = {
        "schema": "qingshan.agentcut_audio_master.v1",
        "status": "PASS",
        "project": str(args.project.resolve()),
        "output": str(args.output.resolve()),
        "clip_count": len(audio_clips),
        "expected_duration_seconds": round(duration, 6),
        "rendered_duration_seconds": round(rendered_duration, 6),
        "duration_delta_seconds": round(delta, 6),
        "sample_rate_hz": rendered_sample_rate,
        "audio_profile_id": (project.get("metadata") or {}).get("audio_profile_id"),
        "sound_cue_contract_status": sound_report["status"],
        "sha256": sha256(args.output),
        "hard_gates": {
            "audio_present": True,
            "duration_delta_lte_0_1_seconds": True,
            "pts_rebuilt_from_samples": True,
            "sample_rate_equals_48000_hz": True,
        },
    }
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
