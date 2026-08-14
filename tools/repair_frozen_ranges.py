#!/usr/bin/env python3
"""Delete unmotivated frozen frames while retaining one continuity frame per run."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

try:
    from repair_periodic_duplicate_frames import FFMPEG, audio_filter, duration, has_audio, select_expression, sha256
except ModuleNotFoundError:
    from tools.repair_periodic_duplicate_frames import FFMPEG, audio_filter, duration, has_audio, select_expression, sha256


def frames_to_delete(runs: list[dict], fps: float, offset: float, source_duration: float) -> list[int]:
    frames = []
    for run in runs:
        local_start = max(0.0, float(run["start_seconds"]) - offset)
        local_end = min(source_duration, local_start + float(run["duration_seconds"]))
        first = int(local_start * fps)
        last = int(local_end * fps)
        frames.extend(range(first + 1, last + 1))
    return sorted(set(frame for frame in frames if frame >= 0))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--freeze-report", required=True)
    parser.add_argument("--timeline-offset", type=float, default=0.0)
    parser.add_argument("--out", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    source = Path(args.video).expanduser().resolve()
    audit_path = Path(args.freeze_report).expanduser().resolve()
    output = Path(args.out).expanduser().resolve()
    report_path = Path(args.report).expanduser().resolve()
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    runs = audit.get("unmotivated_freezes") or []
    if not runs:
        raise SystemExit("freeze report has no unmotivated frozen ranges")
    fps = float(audit.get("output_fps") or 24.0)
    source_duration = duration(source)
    frames = frames_to_delete(runs, fps, args.timeline_offset, source_duration)
    if not frames:
        raise SystemExit("no frozen frames intersect the source timeline")
    source_has_audio = has_audio(source)
    vf = f"select='{select_expression(frames)}',setpts=N/({fps}*TB)"
    command = [str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", "-i", str(source)]
    if source_has_audio:
        command.extend(["-filter_complex", f"[0:v]{vf}[vout];{audio_filter(frames, fps, source_duration)}",
                        "-map", "[vout]", "-map", "[aout]"])
    else:
        command.extend(["-vf", vf, "-an"])
    command.extend(["-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(output)])
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(command, check=True)
    payload = {"schema": "qingshan.frozen_range_repair.v1", "status": "REPAIRED_PENDING_QA",
               "source_video": str(source), "source_sha256": sha256(source), "freeze_report": str(audit_path),
               "timeline_offset_seconds": args.timeline_offset, "source_fps": fps,
               "unmotivated_freezes": runs, "removed_frame_indices": frames, "removed_frame_count": len(frames),
               "source_duration_seconds": source_duration, "output_video": str(output),
               "output_sha256": sha256(output), "output_duration_seconds": duration(output),
               "method": "DELETE_UNMOTIVATED_FROZEN_FRAMES_AND_MATCHING_AUDIO_KEEP_ONE_CONTINUITY_FRAME_PER_RUN",
               "new_generation_calls": 0, "new_generation_credits": 0,
               "recorded_at": datetime.now(timezone.utc).isoformat()}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "removed_frames": len(frames),
                      "duration_before": source_duration, "duration_after": payload["output_duration_seconds"],
                      "out": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
