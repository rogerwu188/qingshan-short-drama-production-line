#!/usr/bin/env python3
"""Build exact-frame V23 two-part YouTube Shorts release drafts."""

from __future__ import annotations

import hashlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FFMPEG = Path("/Users/rogerwu/Documents/Codex/2026-07-17/referenced-chatgpt-conversation-this-is-untrusted/agentcut-0.9.7/agentcut/vendor/darwin-arm64/ffmpeg")
FFPROBE = FFMPEG.with_name("ffprobe")
SOURCE = ROOT / "working_assets/e36_agentcut_20260801/accepted_only_v23_canonical_dialogue_order/E36_ACCEPTED_ONLY_AGENTCUT_V23_CANONICAL_DIALOGUE_ORDER.mp4"
SOURCE_SHA = "89af22464112ec0be2da1fdd8897fd35f46d37cb40c19342422dcd76bb118a83"
OUT = ROOT / "working_assets/e36_release_prep_20260801/youtube_short_split_v23_canonical_order_v1"
QA_DIR = ROOT / "qa/e36_agentcut_20260730/v23_youtube_split_v1"
PARTS = [
    (1, 0, 3526, 0.0, 146.916667),
    (2, 3526, 7053, 146.916667, 293.942646),
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def build(row: tuple[int, int, int, float, float]) -> dict:
    number, start_frame, end_frame, audio_start, audio_end = row
    video = OUT / f"E36_YOUTUBE_SHORTS_V23_CANONICAL_ORDER_PART{number}_V1.mp4"
    decode = QA_DIR / f"E36_V23_YOUTUBE_PART{number}_FULL_DECODE.log"
    probe_path = QA_DIR / f"E36_V23_YOUTUBE_PART{number}_FFPROBE.json"
    graph = (
        f"[0:v]trim=start_frame={start_frame}:end_frame={end_frame},setpts=PTS-STARTPTS[v];"
        f"[0:a]atrim=start={audio_start:.6f}:end={audio_end:.6f},asetpts=PTS-STARTPTS[a]"
    )
    subprocess.run([
        str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", "-i", str(SOURCE),
        "-filter_complex", graph, "-map", "[v]", "-map", "[a]", "-c:v", "libx264",
        "-preset", "ultrafast", "-crf", "18", "-pix_fmt", "yuv420p", "-r", "24",
        "-fps_mode", "cfr", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", str(video),
    ], check=True)
    probe = json.loads(subprocess.check_output([
        str(FFPROBE), "-v", "error", "-show_entries",
        "format=duration:stream=codec_type,width,height,avg_frame_rate,nb_frames,duration,sample_rate,channels",
        "-of", "json", str(video),
    ], text=True))
    probe_path.write_text(json.dumps(probe, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with decode.open("w", encoding="utf-8") as handle:
        subprocess.run([str(FFMPEG), "-hide_banner", "-loglevel", "error", "-i", str(video), "-f", "null", "-"], stdout=handle, stderr=handle, check=True)
    streams = {item["codec_type"]: item for item in probe["streams"]}
    return {
        "part": number,
        "source_video_frames": [start_frame, end_frame],
        "source_audio_seconds": [audio_start, audio_end],
        "path": rel(video),
        "sha256": sha256(video),
        "format_duration_seconds": float(probe["format"]["duration"]),
        "width": int(streams["video"]["width"]),
        "height": int(streams["video"]["height"]),
        "fps": streams["video"]["avg_frame_rate"],
        "video_frames": int(streams["video"]["nb_frames"]),
        "video_duration_seconds": float(streams["video"]["duration"]),
        "audio_duration_seconds": float(streams["audio"]["duration"]),
        "audio_sample_rate": int(streams["audio"]["sample_rate"]),
        "audio_channels": int(streams["audio"]["channels"]),
        "probe": rel(probe_path),
        "probe_sha256": sha256(probe_path),
        "decode_log": rel(decode),
        "decode_log_sha256": sha256(decode),
        "full_decode": "PASS_ZERO_ERRORS" if decode.stat().st_size == 0 else "FAIL",
    }


def main() -> None:
    if sha256(SOURCE) != SOURCE_SHA:
        raise RuntimeError("V23 source changed")
    OUT.mkdir(parents=True, exist_ok=True)
    QA_DIR.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(build, PARTS))
    manifest = {
        "schema": "qingshan.e36.v23_youtube_two_part_build.v1",
        "source": rel(SOURCE),
        "source_sha256": SOURCE_SHA,
        "split_frame": 3526,
        "split_seconds": 146.916667,
        "parts": results,
        "frame_coverage": f"{sum(row['video_frames'] for row in results)}/7053",
        "status": "PASS" if sum(row["video_frames"] for row in results) == 7053 and all(row["full_decode"] == "PASS_ZERO_ERRORS" for row in results) else "FAIL",
        "credits": {"pay": 0, "refund": 0, "net": 0},
    }
    path = QA_DIR / "E36_V23_YOUTUBE_TWO_PART_BUILD_MANIFEST_V1.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if manifest["status"] != "PASS":
        raise RuntimeError(json.dumps(manifest, ensure_ascii=False))
    print(json.dumps({"status": "PASS", "manifest": rel(path), "manifest_sha256": sha256(path), "parts": results}, ensure_ascii=False))


if __name__ == "__main__":
    main()
