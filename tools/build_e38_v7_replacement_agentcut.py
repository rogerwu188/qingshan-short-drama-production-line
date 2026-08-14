#!/usr/bin/env python3
"""Rebind the E38 replacement cut to the exact admitted V7 sources."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/e38_agentcut_v2_ocr_clean_bgm_subtitles_nulu_outro_20260805.json"
PROJECT = ROOT / "configs/e38_agentcut_v7_character_action_replacement_20260805.json"
OUTPUT = ROOT / "exports/e38/agentcut_v7_character_action_replacement_20260805/E38_AGENTCUT_V7_CHARACTER_ACTION_REPLACEMENT_NOT_FINAL.mp4"
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E38剧本_ClaudeWriter_v3.md"
MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E38_manifest_v3.json"
FFPROBE = "ffprobe"

REPLACEMENTS = {
    "U06": ("working_assets/e38_replacement_v7_20260805/pro/U06/result_01.mp4", "qa/e38_replacement_v7_20260805/E38_V7_PARALLEL_SOURCE_QA_R1.json", True),
    "U07": ("working_assets/e38_replacement_v7_20260805/pro/U07/result_01.mp4", "qa/e38_replacement_v7_20260805/E38_V7_U07_LONG_TAKE_QA.json", True),
    "U08": ("working_assets/e38_replacement_v7_20260805/accepted_visuals/U08/E38-U08-V7-SILENT-VISUAL.mp4", "qa/e38_replacement_v7_20260805/E38_V7_U08_U14B_ZERO_CREDIT_ADMISSION.json", False),
    "U12": ("working_assets/e38_replacement_v7_20260805/pro/U12/result_01.mp4", "qa/e38_replacement_v7_20260805/E38_V7_PARALLEL_SOURCE_QA_R1.json", True),
    "U13": ("working_assets/e38_replacement_v7_20260805/pro/U13_R2/result_01.mp4", "qa/e38_replacement_v7_20260805/E38_V7_DIALOGUE_FAILED_ONLY_R2_QA.json", True),
    "U14": ("working_assets/e38_replacement_v7_20260805/accepted_composites/U14/E38-U14-COMPOSITE-R4.mp4", "qa/e38_replacement_v7_20260805/E38_V7_U08_U14B_ZERO_CREDIT_ADMISSION.json", True),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def duration(path: Path) -> float:
    return float(subprocess.check_output([
        FFPROBE, "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", str(path),
    ], text=True).strip())


def main() -> int:
    project = json.loads(BASE.read_text(encoding="utf-8"))
    video_clips = project["timeline"]["videoTracks"][0]["clips"]
    old_windows = {clip["metadata"]["unit_id"]: (float(clip["start"]), float(clip["duration"])) for clip in video_clips}

    cursor = 0.0
    new_windows: dict[str, tuple[float, float]] = {}
    admitted_shas: list[str] = []
    for clip in video_clips:
        unit = clip["metadata"]["unit_id"]
        if unit in REPLACEMENTS:
            source_rel, qa_rel, _ = REPLACEMENTS[unit]
            source = ROOT / source_rel
            qa = ROOT / qa_rel
            clip["source"] = str(source)
            clip["duration"] = round(duration(source) - 0.001, 6)
            clip["metadata"].update({
                "source_sha256": sha256(source),
                "source_qa": str(qa),
                "source_qa_sha256": sha256(qa),
                "admission": "PASS_E38_V7_SOURCE_GROUNDED_REPLACEMENT",
                "camera_policy": "LOCKED_OR_ACTION_MOTIVATED_NO_ROAM_NO_SWAY",
                "visible_actor_motion": "PASS_ALL_VISIBLE_ACTORS_CONTINUOUS",
            })
        clip["start"] = round(cursor, 6)
        new_windows[unit] = (cursor, float(clip["duration"]))
        cursor += float(clip["duration"])
        admitted_shas.append(clip["metadata"]["source_sha256"])

    audio_track = project["timeline"]["audioTracks"][0]
    audio_by_unit = {clip["metadata"]["unit_id"]: clip for clip in audio_track["clips"]}
    rebuilt_audio = []
    for unit, (start, use_duration) in new_windows.items():
        row = audio_by_unit[unit]
        if unit in REPLACEMENTS:
            source_rel, _, keep_audio = REPLACEMENTS[unit]
            if not keep_audio:
                continue
            source = ROOT / source_rel
            row["source"] = str(source)
            row["metadata"]["source_sha256"] = sha256(source)
            row["metadata"]["audio_source"] = "E38_V7_ADMITTED_NATIVE_AUDIO"
        row["start"] = round(start, 6)
        row["duration"] = round(min(use_duration, duration(Path(row["source"]))) - 0.001, 6)
        rebuilt_audio.append(row)
    audio_track["clips"] = rebuilt_audio

    for track in project["timeline"].get("subtitleTracks", []):
        for caption in track.get("clips", []):
            unit = caption.get("metadata", {}).get("unit_id")
            if unit not in old_windows:
                continue
            old_start, old_duration = old_windows[unit]
            new_start, new_duration = new_windows[unit]
            relative = max(0.0, float(caption["start"]) - old_start)
            scale = new_duration / old_duration if old_duration else 1.0
            caption["start"] = round(new_start + relative * scale, 6)
            caption["duration"] = round(min(float(caption["duration"]) * scale, max(0.1, new_duration - relative * scale)), 6)

    project["output"]["path"] = str(OUTPUT)
    project["metadata"].update({
        "status": "E38_V7_CHARACTER_ACTION_REPLACEMENT_NOT_FINAL",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "canonical_script": str(SCRIPT),
        "canonical_script_sha256": sha256(SCRIPT),
        "canonical_manifest": str(MANIFEST),
        "canonical_manifest_sha256": sha256(MANIFEST),
        "runtime_seconds": round(cursor, 6),
        "v7_replacement_units": sorted(REPLACEMENTS),
        "u08_audio_policy": "SILENT_VISUAL_AFTER_UNEXPECTED_VOCALIZATION_FAIL; BGM_AND_ADJACENT_ROOM_TONE_ONLY",
    })
    binding = project["metadata"].setdefault("replacementBindingPolicy", {})
    binding["expectedTargetCount"] = len(video_clips)
    binding["targets"] = [
        {"clipId": clip["id"], "replacementSourceSha256": clip["metadata"]["source_sha256"]}
        for clip in video_clips
    ]
    binding["admittedSourceSha256"] = sorted(admitted_shas)
    project["qingshanAudit"].update({
        "pipelineStage": "E38_AGENTCUT_V7_REPLACEMENT_ASSEMBLY",
        "sourceBinding": "SHA_LOCKED_V7_ACCEPTED_ONLY",
        "generationCredits": {"pay": 5255, "refund": 0, "net": 5255, "cap": 10000, "headroom": 4745},
    })

    PROJECT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    PROJECT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "READY", "project": str(PROJECT), "project_sha256": sha256(PROJECT),
        "output": str(OUTPUT), "runtime_seconds": round(cursor, 6),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
