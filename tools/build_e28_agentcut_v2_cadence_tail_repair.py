#!/usr/bin/env python3
"""Build E28 V2 by trimming only the three evidenced bad source tails."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path("/Users/rogerwu/qingshan_short_drama")
SOURCE = ROOT / "configs/e28_agentcut_project_v1_consolidated_36_20260720.json"
OUTPUT = ROOT / "configs/e28_agentcut_project_v2_cadence_tail_repair_20260721.json"
EXPECTED_SOURCE_SHA = "25834b0d307648f6a04a79886c71df6645dc96761d3802ed1c4013ee7824f6fd"

# Each value ends the source before the exact cadence failure begins.
TARGET_DURATIONS = {
    "DIA-028": 11.125,
    "DIA-031": 6.625,
    "DIA-036": 7.25,
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dialogue_id(clip_id: str) -> str:
    parts = clip_id.split("-")
    return "-".join(parts[1:3])


def main() -> None:
    actual_sha = sha256(SOURCE)
    if actual_sha != EXPECTED_SOURCE_SHA:
        raise SystemExit(f"source SHA mismatch: {actual_sha}")

    project = json.loads(SOURCE.read_text(encoding="utf-8"))
    video_clips = project["timeline"]["videoTracks"][0]["clips"]
    audio_clips = project["timeline"]["audioTracks"][0]["clips"]
    subtitle_clips = project["timeline"]["subtitleTracks"][0]["clips"]
    if len(video_clips) != 36 or len(audio_clips) != 36 or len(subtitle_clips) != 36:
        raise SystemExit("expected exactly 36 synchronized dialogue clips")

    video_by_dialogue: dict[str, dict] = {}
    cursor = 0.0
    for clip in video_clips:
        dia = dialogue_id(clip["id"])
        clip["start"] = round(cursor, 6)
        if dia in TARGET_DURATIONS:
            before = float(clip["duration"])
            after = TARGET_DURATIONS[dia]
            if after >= before:
                raise SystemExit(f"invalid trim for {dia}: {before} -> {after}")
            clip["duration"] = after
            metadata = clip.setdefault("metadata", {})
            metadata["cadence_tail_repair"] = {
                "source_duration_before_seconds": before,
                "source_duration_after_seconds": after,
                "removed_tail_seconds": round(before - after, 6),
                "evidence": "qa/e28_agentcut_v1_consolidated_36_20260721/E28_AGENTCUT_V1_FULLCUT_FRAME_CADENCE.json",
                "cut_reason": "REMOVE_EVIDENCED_DUPLICATE_OR_FROZEN_SOURCE_TAIL",
            }
        video_by_dialogue[dia] = clip
        cursor += float(clip["duration"])

    for clip in audio_clips:
        dia = dialogue_id(clip["id"])
        video = video_by_dialogue[dia]
        clip["start"] = video["start"]
        clip["duration"] = video["duration"]

    for clip in subtitle_clips:
        dia = clip["dialogue_id"]
        video = video_by_dialogue[dia]
        clip["start"] = round(float(video["start"]) + 0.12, 6)
        clip["duration"] = round(max(0.5, float(video["duration"]) - 0.24), 6)

    runtime = round(cursor, 6)
    project["metadata"].update(
        {
            "status": "FULL_DIALOGUE_BATCH_CADENCE_TAIL_REPAIR_NOT_FINAL",
            "builder_version": "0.2.2",
            "source_project": str(SOURCE),
            "source_project_sha256": actual_sha,
            "runtime_seconds": runtime,
            "targeted_repairs": sorted(TARGET_DURATIONS),
            "untouched_dialogue_units": 33,
        }
    )
    project["output"]["path"] = str(
        ROOT
        / "exports/e28/agentcut_v2_cadence_tail_repair_20260721/E28_AGENTCUT_V2_CADENCE_TAIL_REPAIR_NOT_FINAL.mp4"
    )

    OUTPUT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "BUILT",
                "output": str(OUTPUT),
                "source_sha256": actual_sha,
                "output_sha256": sha256(OUTPUT),
                "runtime_seconds": runtime,
                "targeted_repairs": TARGET_DURATIONS,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
