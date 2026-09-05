#!/usr/bin/env python3
"""Render the standard Qingshan/AgentCut JSON timeline with stock FFmpeg.

This public fallback supports one ordered, gap-free video track and one
matching native-audio track. Advanced multi-track work may use AgentCut when
it is separately installed.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def _resolve(project_path: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (project_path.parent / path).resolve()


def _number(value: object, name: str, *, minimum: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if isinstance(value, bool) or not math.isfinite(result) or result < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return result


def _integer(value: object, name: str) -> int:
    number = _number(value, name, minimum=1)
    if not number.is_integer():
        raise ValueError(f"{name} must be an integer")
    return int(number)


def _reject_unsupported(container: dict) -> None:
    for key in ("effects", "transitions", "subtitleTracks", "textTracks", "overlays", "volumeEnvelope"):
        if container.get(key):
            raise ValueError(f"portable renderer does not support {key}; use the full editing engine")
    for key in ("speed", "playbackRate"):
        if key in container and _number(container[key], key) != 1:
            raise ValueError(f"portable renderer does not support {key}; use the full editing engine")


def build_ffmpeg_command(project_path: Path, output_override: Path | None = None) -> list[str]:
    project_path = project_path.expanduser().resolve()
    project = json.loads(project_path.read_text(encoding="utf-8"))
    timeline = project.get("timeline") or {}
    _reject_unsupported(project)
    _reject_unsupported(timeline)
    video_tracks = timeline.get("videoTracks") or []
    audio_tracks = timeline.get("audioTracks") or []
    if len(video_tracks) != 1 or len(audio_tracks) != 1:
        raise ValueError("portable renderer requires exactly one video track and one audio track")

    videos = video_tracks[0].get("clips") or []
    audios = audio_tracks[0].get("clips") or []
    if not videos or len(videos) != len(audios):
        raise ValueError("video/audio clip counts must be equal and non-zero")

    output = project.get("output") or {}
    width = _integer(output.get("width", 720), "output.width")
    height = _integer(output.get("height", 1280), "output.height")
    if width % 2 or height % 2:
        raise ValueError("yuv420p output dimensions must be even")
    fps = _number(output.get("fps", 24), "output.fps", minimum=1.0)
    sample_rate = _integer(output.get("audioSampleRate", 48000), "output.audioSampleRate")
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
    input_index = 0
    for track in video_tracks + audio_tracks:
        _reject_unsupported(track)
    if output_path == project_path:
        raise ValueError("output must not overwrite the timeline project")

    for index, (video, audio) in enumerate(zip(videos, audios)):
        _reject_unsupported(video)
        _reject_unsupported(audio)
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
        if output_path in (video_path, audio_path) or any(
            output_path.exists() and output_path.samefile(path) for path in (video_path, audio_path)
        ):
            raise ValueError("output must not overwrite source media")
        v_index = input_index
        command.extend(["-i", str(video_path)])
        input_index += 1
        a_index = v_index
        if audio_path != video_path:
            a_index = input_index
            command.extend(["-i", str(audio_path)])
            input_index += 1
        v_in = _number(video.get("in", 0), f"video[{index}].in")
        a_in = _number(audio.get("in", 0), f"audio[{index}].in")
        volume = _number(audio.get("volume", 1.0), f"audio[{index}].volume")
        filters.append(
            f"[{v_index}:v:0]trim=start={v_in:.6f}:duration={duration:.6f},"
            f"setpts=PTS-STARTPTS,scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,fps={fps:g},format=yuv420p[v{index}]"
        )
        filters.append(
            f"[{a_index}:a:0]atrim=start={a_in:.6f}:duration={duration:.6f},"
            f"asetpts=PTS-STARTPTS,aresample={sample_rate},volume={volume:g}[a{index}]"
        )
        concat_inputs.extend((f"[v{index}]", f"[a{index}]"))
        cursor += duration

    filters.append("".join(concat_inputs) + f"concat=n={len(videos)}:v=1:a=1[vout][aout]")
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


def execute_render(command: list[str]) -> int:
    """Keep a previously approved final intact when encoding fails."""
    output = Path(command[-1])
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, prefix=output.stem + ".render-",
                                     suffix=output.suffix, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        result = subprocess.run([*command[:-1], str(temporary)], check=False)
        if result.returncode == 0:
            if not temporary.stat().st_size:
                raise ValueError("encoder produced an empty output")
            os.replace(temporary, output)
        return result.returncode
    finally:
        temporary.unlink(missing_ok=True)


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
    return execute_render(command)


if __name__ == "__main__":
    raise SystemExit(main())
