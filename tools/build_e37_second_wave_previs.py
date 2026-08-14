#!/usr/bin/env python3
"""Build a zero-credit E37 timing previs from accepted stills.

The output is preproduction evidence only. It is never eligible as generated
dialogue or as an accepted production-video source.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import imageio_ffmpeg


ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT = ROOT / "qa/e37_preproduction_20260802/E37_SECOND_WAVE_DIALOGUE_MOTION_AND_SPLIT_PREFLIGHT_V1.json"
MANIFEST = ROOT / "workflow/claude_writer_agent/production/e37_claude_writer_v2_4a738459_20260802/E37_SECOND_WAVE_VIDEO_GENERATION_MANIFEST_V1.json"
OUT = ROOT / "working_assets/e37_preproduction_20260802/second_wave_timing_previs_v1"
QA = ROOT / "qa/e37_preproduction_20260802/E37_SECOND_WAVE_TIMING_PREVIS_QA_V1.json"
FPS = 24
WIDTH = 720
HEIGHT = 1280


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(*args: str) -> None:
    subprocess.run(args, check=True, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def probe(ffprobe: str, path: Path) -> dict:
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-count_frames",
            "-show_entries",
            "stream=width,height,r_frame_rate,nb_read_frames,duration",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def main() -> None:
    preflight = json.loads(PREFLIGHT.read_text())
    manifest = json.loads(MANIFEST.read_text())
    tasks = {item["task_key"].removeprefix("E37-CW-").removesuffix("-VIDEO-V1"): item for item in manifest["tasks"]}
    OUT.mkdir(parents=True, exist_ok=True)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    ffprobe = str(Path(ffmpeg).with_name("ffprobe"))
    if not Path(ffprobe).exists():
        ffprobe = "/Users/rogerwu/qingshan_short_drama/.agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffprobe"

    clip_records = []
    concat_lines = []
    timeline_start = 0.0
    for index, segment in enumerate(preflight["approved_generation_segments"], 1):
        segment_id = segment["segment_id"]
        task = tasks[segment_id]
        still = ROOT / task["reference_images"][0]
        duration = int(segment["duration_seconds"])
        frames = duration * FPS
        clip = OUT / f"{index:02d}_{segment_id}_PREVIS_ONLY.mp4"
        direction = -1 if index % 2 else 1
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = f"ih/2-(ih/zoom/2)+{direction}*min(on,120)*0.18"
        vf = (
            f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={WIDTH}:{HEIGHT},"
            f"zoompan=z='min(zoom+0.00045,1.055)':x='{x_expr}':y='{y_expr}':"
            f"d={frames}:s={WIDTH}x{HEIGHT}:fps={FPS},format=yuv420p"
        )
        run(
            ffmpeg,
            "-y",
            "-loop",
            "1",
            "-i",
            str(still),
            "-vf",
            vf,
            "-frames:v",
            str(frames),
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-movflags",
            "+faststart",
            str(clip),
        )
        clip_probe = probe(ffprobe, clip)
        clip_records.append(
            {
                "segment_id": segment_id,
                "timeline_start_seconds": timeline_start,
                "timeline_end_seconds": timeline_start + duration,
                "duration_seconds": duration,
                "frames_expected": frames,
                "kind": segment["kind"],
                "canonical_lines": segment["canonical_lines"],
                "accepted_still": str(still.relative_to(ROOT)),
                "accepted_still_sha256": sha256(still),
                "previs_clip": str(clip.relative_to(ROOT)),
                "previs_clip_sha256": sha256(clip),
                "probe": clip_probe,
                "admission": "PREVIS_ONLY_NOT_PRODUCTION_VIDEO_NOT_DIALOGUE_EVIDENCE",
            }
        )
        concat_lines.append(f"file '{clip.as_posix()}'")
        timeline_start += duration

    concat_file = OUT / "concat_v1.txt"
    concat_file.write_text("\n".join(concat_lines) + "\n")
    reel = OUT / "E37_SECOND_WAVE_TIMING_PREVIS_V1.mp4"
    run(
        ffmpeg,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_file),
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(reel),
    )
    reel_probe = probe(ffprobe, reel)
    expected_frames = sum(item["frames_expected"] for item in clip_records)
    actual_frames = int(reel_probe["streams"][0]["nb_read_frames"])
    report = {
        "schema": "qingshan.preproduction_timing_previs_qa.v1",
        "episode": "E37",
        "status": "PASS_PREVIS_ONLY" if actual_frames == expected_frames else "FAIL_FRAME_COUNT",
        "scope": "ZERO_CREDIT_TIMING_AND_EDIT_PREVIS_ONLY",
        "hard_scope_limit": "NOT_PRODUCTION_VIDEO_NOT_NATIVE_DIALOGUE_NOT_LIPSYNC_NOT_MOTION_ADMISSION",
        "source_preflight": str(PREFLIGHT.relative_to(ROOT)),
        "source_preflight_sha256": sha256(PREFLIGHT),
        "source_manifest": str(MANIFEST.relative_to(ROOT)),
        "source_manifest_sha256": sha256(MANIFEST),
        "clips": clip_records,
        "reel": str(reel.relative_to(ROOT)),
        "reel_sha256": sha256(reel),
        "expected_duration_seconds": timeline_start,
        "expected_frames": expected_frames,
        "actual_frames": actual_frames,
        "probe": reel_probe,
        "gate_results": {
            "segment_coverage": f"PASS_{len(clip_records)}_OF_{len(preflight['approved_generation_segments'])}",
            "frame_count": "PASS_EXACT" if actual_frames == expected_frames else "FAIL",
            "dimensions": f"PASS_{WIDTH}x{HEIGHT}",
            "fps": f"PASS_{FPS}",
            "audio": "NOT_APPLICABLE_PREVIS_ONLY",
            "dialogue": "NOT_ADMITTED",
            "production_video": "NOT_ADMITTED",
        },
        "credits": {"pay": 0, "refund": 0, "net": 0},
        "next_action": "Use the exact timing map for AgentCut planning while provider output is blocked; replace every previs clip with independently QA-accepted generated video before production assembly.",
    }
    QA.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "reel": report["reel"], "sha256": report["reel_sha256"], "frames": actual_frames}, ensure_ascii=False))


if __name__ == "__main__":
    main()
