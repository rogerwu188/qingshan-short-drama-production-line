#!/usr/bin/env python3
"""Remove only mpdecimate-confirmed duplicate frames from a generated video."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
_bundled_ffmpeg = next(
    (path for path in (ROOT / ".agentcut_env").glob("lib/python*/site-packages/agentcut/vendor/*/ffmpeg") if path.is_file()),
    None,
)
FFMPEG = Path(
    os.environ.get("AGENTCUT_FFMPEG")
    or _bundled_ffmpeg
    or shutil.which("ffmpeg")
    or "ffmpeg"
)
FFPROBE = FFMPEG.with_name("ffprobe")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def duration(path: Path) -> float:
    proc = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        text=True,
        capture_output=True,
        check=True,
    )
    return float(proc.stdout.strip())


def select_expression(frames: list[int]) -> str:
    return "not(" + "+".join(f"eq(n\\,{frame})" for frame in frames) + ")"


def consecutive_ranges(frames: list[int]) -> list[tuple[int, int]]:
    values = sorted(set(frames))
    if not values:
        return []
    ranges = []
    start = end = values[0]
    for frame in values[1:]:
        if frame == end + 1:
            end = frame
            continue
        ranges.append((start, end))
        start = end = frame
    ranges.append((start, end))
    return ranges


def confirmed_chain_frames(chains: list[dict]) -> list[int]:
    """Return only frames explicitly verified inside periodic cadence chains."""
    return sorted({
        int(value)
        for chain in chains
        if chain.get("verification_status") == "CONFIRMED_MPDECIMATE"
        for value in chain.get("mpdecimate_matching_frames") or []
    })


def has_audio(path: Path) -> bool:
    proc = subprocess.run(
        [str(FFPROBE), "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
        text=True,
        capture_output=True,
        check=True,
    )
    return bool(proc.stdout.strip())


def audio_filter(frames: list[int], fps: float, source_duration: float) -> str:
    keep_ranges = []
    cursor = 0.0
    for start_frame, end_frame in consecutive_ranges(frames):
        cut_start = start_frame / fps
        cut_end = (end_frame + 1) / fps
        if cut_start > cursor:
            keep_ranges.append((cursor, cut_start))
        cursor = cut_end
    if cursor < source_duration:
        keep_ranges.append((cursor, source_duration))
    filters = []
    labels = []
    for index, (start, end) in enumerate(keep_ranges):
        label = f"a{index}"
        filters.append(f"[0:a]atrim=start={start:.9f}:end={end:.9f},asetpts=PTS-STARTPTS[{label}]")
        labels.append(f"[{label}]")
    filters.append(f"{''.join(labels)}concat=n={len(labels)}:v=0:a=1[aout]")
    return ";".join(filters)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--cadence-report", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    source = Path(args.video).expanduser().resolve()
    cadence_path = Path(args.cadence_report).expanduser().resolve()
    output = Path(args.out).expanduser().resolve()
    report_path = Path(args.report).expanduser().resolve()
    cadence = json.loads(cadence_path.read_text(encoding="utf-8"))
    duplicates = cadence.get("periodic_duplicates") or {}
    chains = duplicates.get("periodic_chains") or []
    # The broad mpdecimate list is diagnostic evidence and may include hundreds
    # of ordinary low-motion frames. Repair only frames that belong to cadence
    # chains independently confirmed by the audit.
    frames = confirmed_chain_frames(chains)
    if not chains or not frames:
        raise SystemExit("cadence report has no confirmed periodic duplicate frames")

    fps = float(cadence.get("output_fps") or 24.0)
    source_duration = duration(source)
    source_has_audio = has_audio(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    vf = f"select='{select_expression(frames)}',setpts=N/({fps}*TB)"
    command = [str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", "-i", str(source)]
    if source_has_audio:
        command.extend([
            "-filter_complex", f"[0:v]{vf}[vout];{audio_filter(frames, fps, source_duration)}",
            "-map", "[vout]", "-map", "[aout]",
        ])
    else:
        command.extend(["-vf", vf, "-an"])
    command.extend([
        "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(output),
    ])
    subprocess.run(command, check=True)

    report = {
        "schema": "qingshan.periodic_duplicate_frame_repair.v1",
        "status": "REPAIRED_PENDING_QA",
        "source_video": str(source),
        "source_sha256": sha256(source),
        "cadence_report": str(cadence_path),
        "confirmed_periodic_chains": chains,
        "removed_frame_indices": frames,
        "removed_frame_count": len(frames),
        "source_duration_seconds": source_duration,
        "source_audio_present": source_has_audio,
        "output_video": str(output),
        "output_sha256": sha256(output),
        "output_duration_seconds": duration(output),
        "method": "DELETE_CONFIRMED_DUPLICATE_FRAMES_AND_MATCHING_AUDIO_INTERVALS_ONLY_NO_SLOWDOWN_NO_INTERPOLATION_NO_PADDING",
        "generation_call_count": 0,
        "new_credits": 0,
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "removed_frames": len(frames),
        "duration_before": report["source_duration_seconds"],
        "duration_after": report["output_duration_seconds"],
        "out": str(output),
        "report": str(report_path),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
