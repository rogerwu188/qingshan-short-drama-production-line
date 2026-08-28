#!/usr/bin/env python3
"""Assemble the accepted 25-unit, 180-second E44 v5 native master."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MEDIA_MAP = ROOT / "qa/e44_v5_final/E44_V5_ACCEPTED_MEDIA_MAP_25_OF_25_A2_REPAIRED_V1.json"
OUT_DIR = ROOT / "working_assets/e44_v5_final"
MASTER = OUT_DIR / "E44_V5_SD2_STANDARD_9X16_MASTER_CANDIDATE_A2_REPAIRED_V1.mp4"
TECH_QA = ROOT / "qa/e44_v5_final/E44_V5_MASTER_CANDIDATE_TECHNICAL_QA_V1.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def main() -> int:
    media_map = json.loads(MEDIA_MAP.read_text(encoding="utf-8"))
    rows = media_map.get("rows") or []
    if media_map.get("status") != "PASS_ACCEPTED_MEDIA_25_OF_25_A2_REPAIRED" or len(rows) != 25 or abs(float(media_map.get("planned_runtime_seconds", 0)) - 180.0) > 0.001:
        raise RuntimeError("accepted E44 media map is not exact PASS 25/25/180")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    command = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "warning"]
    filters = []
    concat_inputs = []
    for row in rows:
        media = ROOT / row["media_path"]
        if not media.is_file() or sha(media) != row["media_sha256"]:
            raise RuntimeError(f"accepted media missing or changed: {row['unit_id']}")
        command.extend(["-i", str(media)])
    for index, row in enumerate(rows):
        duration = float(row["planned_duration_seconds"])
        filters.append(
            f"[{index}:v]scale=720:1280:force_original_aspect_ratio=decrease,"
            f"pad=720:1280:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=24,"
            f"tpad=stop_mode=clone:stop_duration=1,trim=duration={duration:.6f},setpts=PTS-STARTPTS[v{index}]"
        )
        filters.append(
            f"[{index}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"apad=pad_dur=1,atrim=duration={duration:.6f},asetpts=PTS-STARTPTS[a{index}]"
        )
        concat_inputs.append(f"[v{index}][a{index}]")
    filters.append("".join(concat_inputs) + f"concat=n={len(rows)}:v=1:a=1[outv][outa]")
    command.extend([
        "-filter_complex_threads", "1", "-filter_complex", ";".join(filters),
        "-map", "[outv]", "-map", "[outa]", "-t", "180.000",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(MASTER),
    ])
    subprocess.run(command, check=True)
    info = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(MASTER)], text=True))
    video = next((row for row in info["streams"] if row.get("codec_type") == "video"), None)
    audio = next((row for row in info["streams"] if row.get("codec_type") == "audio"), None)
    duration = float(info["format"]["duration"])
    failures = []
    if not video or video.get("codec_name") != "h264" or (video.get("width"), video.get("height")) != (720, 1280):
        failures.append("VIDEO_STREAM_INVALID")
    if not audio or audio.get("codec_name") != "aac":
        failures.append("AUDIO_STREAM_INVALID")
    if abs(duration - 180.0) > 0.1:
        failures.append("DURATION_NOT_180_SECONDS")
    qa = {
        "schema": "qingshan.e44.v5.master_candidate_technical_qa.v1",
        "episode": "E44",
        "created_at": now(),
        "status": "PASS_TECHNICAL_MASTER" if not failures else "FAIL",
        "source_media_map": rel(MEDIA_MAP),
        "source_media_map_sha256": sha(MEDIA_MAP),
        "master_candidate": rel(MASTER),
        "master_candidate_sha256": sha(MASTER),
        "unit_count": 25,
        "decoded_duration_seconds": duration,
        "video_stream": video,
        "audio_stream": audio,
        "failures": failures,
    }
    TECH_QA.parent.mkdir(parents=True, exist_ok=True)
    TECH_QA.write_text(json.dumps(qa, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": qa["status"], "duration": duration, "master": rel(MASTER), "sha256": sha(MASTER)}, ensure_ascii=False))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
