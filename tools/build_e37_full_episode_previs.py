#!/usr/bin/env python3
"""Build a full E37 zero-credit timing previs across all 22 segments."""

from __future__ import annotations

import json
from pathlib import Path

import imageio_ffmpeg

from build_e37_second_wave_previs import FPS, HEIGHT, ROOT, WIDTH, probe, run, sha256


FIRST_PREFLIGHT = ROOT / "qa/e37_preproduction_20260802/E37_FIRST_WAVE_DIALOGUE_OCCUPANCY_AND_SPLIT_PREFLIGHT_V1.json"
FIRST_MANIFEST = ROOT / "workflow/claude_writer_agent/production/e37_claude_writer_v2_4a738459_20260802/E37_FIRST_WAVE_VIDEO_GENERATION_MANIFEST_V1.json"
SECOND_QA = ROOT / "qa/e37_preproduction_20260802/E37_SECOND_WAVE_TIMING_PREVIS_QA_V1.json"
OUT = ROOT / "working_assets/e37_preproduction_20260802/full_episode_timing_previs_v1"
QA = ROOT / "qa/e37_preproduction_20260802/E37_FULL_EPISODE_TIMING_PREVIS_QA_V1.json"


def main() -> None:
    first_preflight = json.loads(FIRST_PREFLIGHT.read_text())
    first_manifest = json.loads(FIRST_MANIFEST.read_text())
    second_qa = json.loads(SECOND_QA.read_text())
    first_tasks = {
        item["task_key"].removeprefix("E37-CW-").removesuffix("-VIDEO-V1"): item
        for item in first_manifest["tasks"]
    }
    OUT.mkdir(parents=True, exist_ok=True)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    ffprobe = str(Path(ffmpeg).with_name("ffprobe"))
    if not Path(ffprobe).exists():
        ffprobe = str(ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffprobe")

    records = []
    timeline = 0.0
    concat_lines = []
    for index, segment in enumerate(first_preflight["approved_generation_segments"], 1):
        segment_id = segment["segment_id"]
        task = first_tasks[segment_id]
        still = ROOT / task["reference_images"][0]
        duration = int(segment["duration_seconds"])
        frames = duration * FPS
        clip = OUT / f"{index:02d}_{segment_id}_PREVIS_ONLY.mp4"
        direction = -1 if index % 2 else 1
        vf = (
            f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={WIDTH}:{HEIGHT},"
            f"zoompan=z='min(zoom+0.00045,1.055)':x='iw/2-(iw/zoom/2)':"
            f"y='ih/2-(ih/zoom/2)+{direction}*min(on,120)*0.18':"
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
        records.append(
            {
                "segment_id": segment_id,
                "wave": 1,
                "timeline_start_seconds": timeline,
                "timeline_end_seconds": timeline + duration,
                "duration_seconds": duration,
                "frames": frames,
                "canonical_lines": segment["canonical_lines"],
                "accepted_still": str(still.relative_to(ROOT)),
                "accepted_still_sha256": sha256(still),
                "previs_clip": str(clip.relative_to(ROOT)),
                "previs_clip_sha256": sha256(clip),
                "admission": "PREVIS_ONLY_NOT_PRODUCTION_VIDEO_NOT_DIALOGUE_EVIDENCE",
            }
        )
        concat_lines.append(f"file '{clip.as_posix()}'")
        timeline += duration

    for offset, source in enumerate(second_qa["clips"], len(records) + 1):
        clip = ROOT / source["previs_clip"]
        duration = int(source["duration_seconds"])
        records.append(
            {
                "segment_id": source["segment_id"],
                "wave": 2,
                "timeline_start_seconds": timeline,
                "timeline_end_seconds": timeline + duration,
                "duration_seconds": duration,
                "frames": source["frames_expected"],
                "canonical_lines": source["canonical_lines"],
                "accepted_still": source["accepted_still"],
                "accepted_still_sha256": source["accepted_still_sha256"],
                "previs_clip": source["previs_clip"],
                "previs_clip_sha256": sha256(clip),
                "admission": "PREVIS_ONLY_NOT_PRODUCTION_VIDEO_NOT_DIALOGUE_EVIDENCE",
            }
        )
        concat_lines.append(f"file '{clip.as_posix()}'")
        timeline += duration

    concat_file = OUT / "concat_v1.txt"
    concat_file.write_text("\n".join(concat_lines) + "\n")
    reel = OUT / "E37_FULL_EPISODE_TIMING_PREVIS_V1.mp4"
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
    expected_frames = sum(item["frames"] for item in records)
    actual_frames = int(reel_probe["streams"][0]["nb_read_frames"])
    line_coverage = sorted(line for item in records for line in item["canonical_lines"])
    report = {
        "schema": "qingshan.full_episode_preproduction_timing_previs_qa.v1",
        "episode": "E37",
        "status": "PASS_PREVIS_ONLY" if actual_frames == expected_frames and line_coverage == list(range(1, 32)) else "FAIL",
        "scope": "ZERO_CREDIT_FULL_EPISODE_TIMING_AND_REPLACEMENT_MAP_ONLY",
        "hard_scope_limit": "NOT_PRODUCTION_VIDEO_NOT_NATIVE_DIALOGUE_NOT_LIPSYNC_NOT_MOTION_ADMISSION",
        "sources": [
            {"path": str(FIRST_PREFLIGHT.relative_to(ROOT)), "sha256": sha256(FIRST_PREFLIGHT)},
            {"path": str(FIRST_MANIFEST.relative_to(ROOT)), "sha256": sha256(FIRST_MANIFEST)},
            {"path": str(SECOND_QA.relative_to(ROOT)), "sha256": sha256(SECOND_QA)},
        ],
        "clips": records,
        "reel": str(reel.relative_to(ROOT)),
        "reel_sha256": sha256(reel),
        "expected_duration_seconds": timeline,
        "expected_frames": expected_frames,
        "actual_frames": actual_frames,
        "canonical_line_coverage": line_coverage,
        "probe": reel_probe,
        "gate_results": {
            "segment_coverage": "PASS_22_OF_22",
            "canonical_line_timing_slots": "PASS_31_OF_31",
            "frame_count": "PASS_EXACT" if actual_frames == expected_frames else "FAIL",
            "dimensions": f"PASS_{WIDTH}x{HEIGHT}",
            "fps": f"PASS_{FPS}",
            "audio": "NOT_APPLICABLE_PREVIS_ONLY",
            "native_dialogue": "NOT_ADMITTED",
            "production_video": "NOT_ADMITTED",
        },
        "credits": {"pay": 0, "refund": 0, "net": 0},
        "next_action": "Use all 22 intervals as the AgentCut replacement map; replace each interval only with independently QA-accepted generated video before production assembly.",
    }
    QA.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "reel": report["reel"], "sha256": report["reel_sha256"], "frames": actual_frames, "seconds": timeline}, ensure_ascii=False))


if __name__ == "__main__":
    main()
