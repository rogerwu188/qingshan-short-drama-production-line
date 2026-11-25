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


def _audio_seconds(path: Path) -> float:
    ffprobe = os.environ.get("FFPROBE_BIN") or shutil.which("ffprobe") or "ffprobe"
    run = subprocess.run([ffprobe, "-v", "error", "-select_streams", "a:0", "-show_entries",
                          "stream=duration:format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True, check=False)
    try:
        payload = json.loads(run.stdout or "{}")
    except ValueError:
        payload = {}
    for row in (payload.get("streams") or []) + [payload.get("format") or {}]:
        try:
            return float(row["duration"])
        except (KeyError, TypeError, ValueError):
            continue
    return 0.0


#: Fill-and-crop instead of letterbox when a clip is this close to the output's aspect (line owner 2026-11-12:
#: MiniMax-H3 768p is 768x1344, so fit+pad left a 10 px black band top and bottom of every published episode).
#: Clips further off (landscape title cards, stills) keep fit+pad so nothing important is cropped away.
FILL_CROP_ASPECT_TOLERANCE = 0.05


def _video_aspect(path: Path) -> float | None:
    """width / height of the first video stream (display aspect, rotation ignored), or None if unknown."""
    ffprobe = os.environ.get("FFPROBE_BIN") or shutil.which("ffprobe") or "ffprobe"
    try:
        run = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                              "stream=width,height", "-of", "json", str(path)],
                             capture_output=True, text=True, timeout=30)
        stream = (json.loads(run.stdout or "{}").get("streams") or [{}])[0]
        width, height = int(stream.get("width") or 0), int(stream.get("height") or 0)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return width / height if width > 0 and height > 0 else None


def _fit_filter(path: Path, width: int, height: int, cache: dict[str, float | None]) -> str:
    """Scale step for one clip: fill+centre-crop when its aspect is within FILL_CROP_ASPECT_TOLERANCE of the
    output, else fit+black pad (also when the aspect cannot be read)."""
    key = str(path)
    if key not in cache:
        cache[key] = _video_aspect(path)
    aspect, target = cache[key], width / height
    if aspect is not None and abs(aspect - target) / target <= FILL_CROP_ASPECT_TOLERANCE:
        return (f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height}:(iw-ow)/2:(ih-oh)/2")
    return (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black")


def _crossfade_audio_filters(audio_rows: list[dict], audios: list[dict], seconds: float, sample_rate: int
                             ) -> list[str]:
    """CAMERA_GRAMMAR_V1 (metadata.audio_cut_crossfade): equal-power crossfade at every cut from the clips' own
    handles (tools/s7_audio_smoothing.crossfade_plan); the timeline length and every in-point stay where they are."""
    try:
        from tools import s7_audio_smoothing as _smooth
    except ImportError:
        import s7_audio_smoothing as _smooth  # type: ignore
    slots = [{**clip, "duration": row["duration"]} for clip, row in zip(audios, audio_rows)]
    plan = _smooth.crossfade_plan(slots, [_audio_seconds(row["path"]) for row in audio_rows], seconds)
    total = sum(row["duration"] for row in audio_rows)
    filters = []
    curve = _smooth.CROSSFADE_CURVE
    for index, row in enumerate(audio_rows):
        head = plan[index - 1]["head"] if index > 0 else 0.0
        tail = plan[index]["tail"] if index < len(plan) else 0.0
        length = row["duration"] + head + tail
        fades = ""
        fade_in = plan[index - 1]["fade"] if index > 0 else 0.0
        fade_out = plan[index]["fade"] if index < len(plan) else 0.0
        if fade_in > 0:
            fades += f",afade=t=in:st=0:d={fade_in:.6f}:curve={curve}"
        if fade_out > 0:
            fades += f",afade=t=out:st={length - fade_out:.6f}:d={fade_out:.6f}:curve={curve}"
        filters.append(
            f"[{row['input']}:a:0]atrim=start={row['in'] - head:.6f}:duration={length:.6f},"
            f"asetpts=PTS-STARTPTS,aresample={sample_rate},apad=whole_dur={length:.6f},volume={row['volume']:g}"
            f"{fades}[c{index}]")
    current = "[c0]"
    for index, cut in enumerate(plan, start=1):
        label = f"[x{index}]"
        if cut["seconds"] > 0:
            filters.append(f"{current}[c{index}]acrossfade=d={cut['seconds']:.6f}:"
                           f"c1={_smooth.CROSSFADE_CURVE}:c2={_smooth.CROSSFADE_CURVE}{label}")
        else:
            filters.append(f"{current}[c{index}]concat=n=2:v=0:a=1{label}")
        current = label
    filters.append(f"{current}apad=whole_dur={total:.6f},atrim=duration={total:.6f}[aout]")
    return filters


def audio_placement_plan(audio_rows: list[dict], audios: list[dict], seconds: float, jcuts: list[dict],
                         source_seconds: list[float]) -> list[dict]:
    """S7 J-cut (metadata.audio_jcut, tools/dialogue_jcut.py): every clip's audio as one segment placed at its own
    timeline position.  Ordinary cuts keep the equal-power crossfade of ``crossfade_plan`` (same head/tail handles
    and curves as the acrossfade chain); at a J-cut the incoming clip's audio starts ``preroll_seconds`` before the
    cut from its own source (``[in - preroll, in]``, so it stays locked to its picture) and fades in over
    ``fade_in_seconds``, while the outgoing clip plays on to the cut and fades out over ``fade_out_seconds`` (using
    up to half of it from its own tail handle).  Returns rows {input, src_start, length, place, fade_in, fade_out,
    volume}."""
    try:
        from tools import s7_audio_smoothing as _smooth
    except ImportError:
        import s7_audio_smoothing as _smooth  # type: ignore
    slots = [{**clip, "duration": row["duration"]} for clip, row in zip(audios, audio_rows)]
    if seconds > 0:
        plan = _smooth.crossfade_plan(slots, source_seconds, seconds)
    else:
        plan = [{"mode": "HARD", "head": 0.0, "tail": 0.0, "seconds": 0.0, "fade": 0.0} for _ in slots[1:]]
    for jc in jcuts:
        index = int(jc["index"])
        if not 0 < index < len(slots):
            continue
        out_clip = slots[index - 1]
        tail_room = max(0.0, float(source_seconds[index - 1]) - float(out_clip.get("in") or 0.0)
                        - float(out_clip["duration"]))
        fade_out = float(jc.get("fade_out_seconds") or 0.03)
        preroll = min(float(jc["preroll_seconds"]), float(slots[index].get("in") or 0.0),
                      float(out_clip["duration"]) / 2.0)
        plan[index - 1] = {"mode": "JCUT", "head": round(preroll, 6), "tail": round(min(fade_out / 2.0, tail_room), 6),
                           "fade_in": min(float(jc.get("fade_in_seconds") or 0.03), preroll), "fade_out": fade_out}
    rows, place = [], 0.0
    for index, row in enumerate(audio_rows):
        before = plan[index - 1] if index > 0 else None
        after = plan[index] if index < len(plan) else None
        head = before["head"] if before and before["mode"] in ("CROSSFADE", "JCUT") else 0.0
        tail = after["tail"] if after and after["mode"] in ("CROSSFADE", "JCUT") else 0.0
        fade_in = (before["seconds"] if before and before["mode"] == "CROSSFADE"
                   else before["fade"] if before and before["mode"] == "FADE_THROUGH"
                   else before["fade_in"] if before and before["mode"] == "JCUT" else 0.0)
        fade_out = (after["seconds"] if after and after["mode"] == "CROSSFADE"
                    else after["fade"] if after and after["mode"] == "FADE_THROUGH"
                    else after["fade_out"] if after and after["mode"] == "JCUT" else 0.0)
        length = row["duration"] + head + tail
        rows.append({"input": row["input"], "src_start": round(max(0.0, row["in"] - head), 6),
                     "length": round(length, 6), "place": round(max(0.0, place - head), 6),
                     "fade_in": round(min(fade_in, length / 2.0), 6), "fade_out": round(min(fade_out, length / 2.0), 6),
                     "volume": row["volume"], "cut_mode_in": before["mode"] if before else None})
        place += row["duration"]
    return rows


def _placed_audio_filters(audio_rows: list[dict], audios: list[dict], seconds: float, sample_rate: int,
                          jcuts: list[dict]) -> list[str]:
    try:
        from tools import s7_audio_smoothing as _smooth
    except ImportError:
        import s7_audio_smoothing as _smooth  # type: ignore
    placed = audio_placement_plan(audio_rows, audios, seconds, jcuts,
                                  [_audio_seconds(row["path"]) for row in audio_rows])
    total = sum(row["duration"] for row in audio_rows)
    curve = _smooth.CROSSFADE_CURVE
    filters, labels = [], []
    for index, seg in enumerate(placed):
        fades = ""
        if seg["fade_in"] > 0:
            fades += f",afade=t=in:st=0:d={seg['fade_in']:.6f}:curve={curve}"
        if seg["fade_out"] > 0:
            fades += f",afade=t=out:st={seg['length'] - seg['fade_out']:.6f}:d={seg['fade_out']:.6f}:curve={curve}"
        delay = int(round(seg["place"] * sample_rate))
        filters.append(
            f"[{seg['input']}:a:0]atrim=start={seg['src_start']:.6f}:duration={seg['length']:.6f},"
            f"asetpts=PTS-STARTPTS,aresample={sample_rate},aformat=channel_layouts=stereo,"
            f"apad=whole_dur={seg['length']:.6f},atrim=duration={seg['length']:.6f},volume={seg['volume']:g}"
            f"{fades},adelay=delays={delay}S:all=1[p{index}]")
        labels.append(f"[p{index}]")
    filters.append("".join(labels) + f"amix=inputs={len(labels)}:duration=longest:normalize=0,"
                   f"apad=whole_dur={total:.6f},atrim=duration={total:.6f}[aout]")
    return filters


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
    crossfade = (project.get("metadata") or {}).get("audio_cut_crossfade") or {}
    crossfade_seconds = _number(crossfade.get("seconds", 0), "metadata.audio_cut_crossfade.seconds") if crossfade else 0.0
    jcuts = [row for row in (((project.get("metadata") or {}).get("audio_jcut") or {}).get("cuts") or [])
             if isinstance(row, dict)]
    for row in jcuts:
        _number(row.get("index"), "metadata.audio_jcut.cuts[].index", minimum=1)
        _number(row.get("preroll_seconds"), "metadata.audio_jcut.cuts[].preroll_seconds")
    per_clip_audio = crossfade_seconds > 0 or bool(jcuts)
    audio_rows: list[dict] = []
    aspect_cache: dict[str, float | None] = {}
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
        # crossfade path: every picture segment is exactly round(duration * fps) frames (last frame held if the
        # source runs short) and its audio slot is exactly as long, so picture and sound stay locked at every cut
        frames = max(1, round(duration * fps))
        exact = (f",tpad=stop_mode=clone:stop=2,trim=end_frame={frames},setpts=PTS-STARTPTS"
                 if per_clip_audio else "")
        filters.append(
            f"[{v_index}:v:0]trim=start={v_in:.6f}:duration={duration:.6f},"
            f"setpts=PTS-STARTPTS,{_fit_filter(video_path, width, height, aspect_cache)},"
            # scale keeps the display aspect by rewriting SAR (e.g. 5120:5117) and some sources carry no SAR
            # at all (0:1); concat refuses segments whose SAR differs, so every segment is forced to square pixels
            f"setsar=1,fps={fps:g},format=yuv420p{exact}[v{index}]"
        )
        if per_clip_audio:
            audio_rows.append({"input": a_index, "path": audio_path, "in": a_in, "volume": volume,
                               "duration": frames / fps})
            concat_inputs.append(f"[v{index}]")
            cursor += duration
            continue
        filters.append(
            f"[{a_index}:a:0]atrim=start={a_in:.6f}:duration={duration:.6f},"
            f"asetpts=PTS-STARTPTS,aresample={sample_rate},volume={volume:g}[a{index}]"
        )
        concat_inputs.extend((f"[v{index}]", f"[a{index}]"))
        cursor += duration

    if jcuts:
        filters.append("".join(concat_inputs) + f"concat=n={len(videos)}:v=1:a=0[vout]")
        filters.extend(_placed_audio_filters(audio_rows, audios, crossfade_seconds, sample_rate, jcuts))
    elif crossfade_seconds > 0:
        filters.append("".join(concat_inputs) + f"concat=n={len(videos)}:v=1:a=0[vout]")
        filters.extend(_crossfade_audio_filters(audio_rows, audios, crossfade_seconds, sample_rate))
    else:
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
