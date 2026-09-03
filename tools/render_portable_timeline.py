#!/usr/bin/env python3
"""Render the standard Qingshan/AgentCut JSON timeline with stock FFmpeg.

This public fallback supports one ordered, gap-free video track and one
matching native-audio track. Advanced multi-track work may use AgentCut when
it is separately installed.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path


def _resolve(project_path: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (project_path.parent / path).resolve()


def _number(value: object, name: str, *, minimum: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if result < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return result


def build_ffmpeg_command(project_path: Path, output_override: Path | None = None) -> list[str]:
    project_path = project_path.expanduser().resolve()
    project = json.loads(project_path.read_text(encoding="utf-8"))
    timeline = project.get("timeline") or {}
    video_tracks = timeline.get("videoTracks") or []
    audio_tracks = timeline.get("audioTracks") or []
    if len(video_tracks) != 1 or len(audio_tracks) != 1:
        raise ValueError("portable renderer requires exactly one video track and one audio track")

    videos = video_tracks[0].get("clips") or []
    audios = audio_tracks[0].get("clips") or []
    if not videos or len(videos) != len(audios):
        raise ValueError("video/audio clip counts must be equal and non-zero")

    output = project.get("output") or {}
    width = int(output.get("width") or 720)
    height = int(output.get("height") or 1280)
    fps = _number(output.get("fps") or 24, "output.fps", minimum=1.0)
    sample_rate = int(output.get("audioSampleRate") or 48000)
    video_codec = str(output.get("videoCodec") or "libx264")
    if video_codec not in {"libx264", "h264_videotoolbox"}:
        raise ValueError(f"unsupported portable video codec: {video_codec}")
    if str(output.get("audioCodec") or "aac") != "aac":
        raise ValueError("portable renderer supports AAC output")

    output_path = output_override.expanduser().resolve() if output_override else _resolve(
        project_path, str(output.get("path") or "deliverables/output.mp4")
    )
    command = [os.environ.get("FFMPEG_BIN") or shutil.which("ffmpeg") or "ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    filters: list[str] = []
    concat_inputs: list[str] = []
    cursor = 0.0

    for index, (video, audio) in enumerate(zip(videos, audios)):
        v_start = _number(video.get("start", 0), f"video[{index}].start")
        a_start = _number(audio.get("start", 0), f"audio[{index}].start")
        duration = _number(video.get("duration"), f"video[{index}].duration", minimum=0.001)
        audio_duration = _number(audio.get("duration"), f"audio[{index}].duration", minimum=0.001)
        if abs(v_start - cursor) > 0.002 or abs(a_start - cursor) > 0.002:
            raise ValueError(f"timeline gap/overlap at clip {index}: expected {cursor}, got video={v_start}, audio={a_start}")
        if abs(duration - audio_duration) > 0.002:
            raise ValueError(f"video/audio duration mismatch at clip {index}")

        video_path = _resolve(project_path, str(video.get("source") or ""))
        audio_path = _resolve(project_path, str(audio.get("source") or ""))
        if not video_path.is_file() or not audio_path.is_file():
            raise FileNotFoundError(f"missing media at clip {index}: {video_path} / {audio_path}")
        command.extend(["-i", str(video_path), "-i", str(audio_path)])
        v_in = _number(video.get("in", 0), f"video[{index}].in")
        a_in = _number(audio.get("in", 0), f"audio[{index}].in")
        volume = _number(audio.get("volume", 1.0), f"audio[{index}].volume")
        filters.append(
            f"[{index * 2}:v:0]trim=start={v_in:.6f}:duration={duration:.6f},"
            f"setpts=PTS-STARTPTS,scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,fps={fps:g},format=yuv420p[v{index}]"
        )
        filters.append(
            f"[{index * 2 + 1}:a:0]atrim=start={a_in:.6f}:duration={duration:.6f},"
            f"asetpts=PTS-STARTPTS,aresample={sample_rate},volume={volume:g}[a{index}]"
        )
        concat_inputs.extend((f"[v{index}]", f"[a{index}]"))
        cursor += duration

    filters.append("".join(concat_inputs) + f"concat=n={len(videos)}:v=1:a=1[vout][aout]")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command.extend(["-filter_complex", ";".join(filters), "-map", "[vout]", "-map", "[aout]"])
    if video_codec == "libx264":
        command.extend(["-c:v", video_codec, "-preset", "medium", "-crf", "18"])
    else:
        command.extend(["-c:v", video_codec, "-b:v", str(output.get("videoBitrate") or "8M")])
    command.extend([
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", str(output.get("audioBitrate") or "192k"),
        "-ar", str(sample_rate), "-movflags", "+faststart", "-t", f"{cursor:.6f}", str(output_path),
    ])
    return command


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    command = build_ffmpeg_command(args.project, args.output)
    if args.dry_run:
        print(json.dumps({"status": "PASS", "command": command}, ensure_ascii=False, indent=2))
        return 0
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
