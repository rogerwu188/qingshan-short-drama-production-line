#!/usr/bin/env python3
"""Assemble the accepted 26-unit E43 v6 master after scoped A2 repairs."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MEDIA_MAP = ROOT / "qa/e43_v6_a2_continuity_repairs/E43_V6_ACCEPTED_MEDIA_MAP_26_OF_26_A2_REPAIRED_V1.json"
OUT_DIR = ROOT / "working_assets/e43_v6_final"
CONCAT = OUT_DIR / "E43_V6_SD2_STANDARD_26_UNITS_A2_REPAIRED_V1.ffconcat"
MASTER = OUT_DIR / "E43_V6_SD2_STANDARD_9X16_MASTER_CANDIDATE_A2_REPAIRED_V1.mp4"
TECH_QA = ROOT / "qa/e43_v6_final/E43_V6_MASTER_CANDIDATE_TECHNICAL_QA_A2_REPAIRED_V1.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def probe(path: Path) -> dict:
    return json.loads(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        text=True,
    ))


def main() -> int:
    media_map = json.loads(MEDIA_MAP.read_text(encoding="utf-8"))
    if media_map.get("status") != "PASS_ACCEPTED_MEDIA_26_OF_26_A2_REPAIRED":
        raise RuntimeError("accepted media map is not PASS")
    rows = media_map.get("rows") or []
    if len(rows) != 26 or abs(float(media_map.get("planned_runtime_seconds", 0)) - 180.0) > 0.001:
        raise RuntimeError("accepted media map is not exact 26/26/180 seconds")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    lines = ["ffconcat version 1.0"]
    for row in rows:
        media = ROOT / row["media_path"]
        if not media.is_file() or sha(media) != row["media_sha256"]:
            raise RuntimeError(f"accepted media missing or changed: {row['unit_id']}")
        escaped = str(media).replace("'", "'\\''")
        lines.extend([
            f"file '{escaped}'",
            "inpoint 0",
            f"outpoint {float(row['planned_duration_seconds']):.3f}",
        ])
    CONCAT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "warning",
            "-f", "concat", "-safe", "0", "-i", str(CONCAT), "-t", "180.000",
            "-vf", "scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2:black,setsar=1",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", str(MASTER),
        ],
        check=True,
    )
    info = probe(MASTER)
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
        "schema": "qingshan.e43.v6.master_candidate_technical_qa.v1",
        "episode": "E43",
        "created_at": now(),
        "status": "PASS_TECHNICAL_MASTER_BASIC_PLOT_QA_PENDING" if not failures else "FAIL",
        "source_media_map": rel(MEDIA_MAP),
        "source_media_map_sha256": sha(MEDIA_MAP),
        "master_candidate": rel(MASTER),
        "master_candidate_sha256": sha(MASTER),
        "unit_count": 26,
        "repaired_units": media_map["replaced_a1_units"],
        "decoded_duration_seconds": duration,
        "video_stream": video,
        "audio_stream": audio,
        "failures": failures,
        "post_generation_qa_scope": "TECHNICAL_PLUS_BASIC_PLOT_ONLY",
        "content_lock_allowed": False,
        "release_allowed": False,
    }
    TECH_QA.parent.mkdir(parents=True, exist_ok=True)
    TECH_QA.write_text(json.dumps(qa, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": qa["status"],
        "duration": duration,
        "master": rel(MASTER),
        "sha256": sha(MASTER),
    }, ensure_ascii=False))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
