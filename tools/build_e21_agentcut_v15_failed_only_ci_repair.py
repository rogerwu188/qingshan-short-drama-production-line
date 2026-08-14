#!/usr/bin/env python3
"""Build E21 V15 from V14, repairing only frozen-CI failures."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/e21_agentcut_project_v14_runtime_and_cut_separation_repair_20260719.json"
CI = ROOT / "qa/e21_agentcut_v14_runtime_and_cut_separation_repair_20260719/E21_REGRESSION_CI_V14_FROZEN_THRESHOLDS.json"
OUT_PROJECT = ROOT / "configs/e21_agentcut_project_v15_failed_only_ci_repair_20260719.json"
OUT_QA = ROOT / "qa/e21_agentcut_v15_failed_only_ci_repair_20260719"
OUT_TIMELINE = OUT_QA / "E21_FINAL_TIMELINE_SHOTS_V15.json"
OUT_AUDIO_BOUNDARIES = OUT_QA / "E21_AUDIO_EDIT_BOUNDARIES_V15.json"
OUT_RECEIPT = ROOT / "workflow/tasks/E21_AGENTCUT_V15_FAILED_ONLY_CI_REPAIR_20260719.json"
OUT_VIDEO = ROOT / "exports/e21/agentcut_v15_failed_only_ci_repair_20260719/E21_AGENTCUT_V15_FAILED_ONLY_CI_REPAIR_NOT_FINAL.mp4"
LUMA_DIR = ROOT / "working_assets/e21_v15_failed_only_luma_repair_20260719"

EXPECTED_FAILURES = {
    "too_many_long_shots:8",
    "repeated_frame_cluster:3",
    "audio_adjacent_rms_jump:25-26:22.2",
    "audio_adjacent_rms_jump:26-27:20.4",
    "scene_luma_jump:E21-DIA-019-VIDEO->E21-DIA-020-VIDEO:25.06",
    "scene_luma_jump:E21-DIA-024-VIDEO->E21-DIA-025-VIDEO:26.16",
}
STRONG_BOUNDARY_PUNCH_INS = {"DIA-007", "DIA-013", "DIA-016", "DIA-017", "DIA-024", "DIA-026"}
INTERNAL_SPLITS = {"DIA-009": 3.0, "DIA-010": 3.0, "DIA-018": 3.0}
LUMA_REPAIRS = {"DIA-020": 0.012, "DIA-025": 0.020}


def dialogue_id(clip: dict) -> str | None:
    explicit = clip.get("metadata", {}).get("dialogue_id") or clip.get("dialogue_id")
    if explicit:
        return explicit
    for index in range(1, 38):
        candidate = f"DIA-{index:03d}"
        if candidate in clip.get("id", ""):
            return candidate
    return None


def make_luma_source(source: Path, target: Path, brightness: float) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    expression = f"eq=brightness='{brightness}*(1-min(t/1.2\\,1))':eval=frame"
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
        "-vf", expression, "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264",
        "-preset", "medium", "-crf", "17", "-c:a", "copy", "-movflags", "+faststart", str(target),
    ]
    subprocess.run(command, check=True)


def main() -> int:
    project = json.loads(BASE.read_text(encoding="utf-8"))
    ci = json.loads(CI.read_text(encoding="utf-8"))
    if set(ci.get("failures", [])) != EXPECTED_FAILURES:
        raise SystemExit(f"Unexpected V14 failure set: {ci.get('failures')}")

    video_track = project["timeline"]["videoTracks"][0]
    source_by_dialogue = {dialogue_id(clip): Path(clip["source"]) for clip in video_track["clips"]}
    luma_sources: dict[str, str] = {}
    for dia_id, brightness in LUMA_REPAIRS.items():
        source = source_by_dialogue[dia_id]
        target = LUMA_DIR / f"E21_{dia_id}_V15_OPENING_LUMA_RAMP.mp4"
        make_luma_source(source, target, brightness)
        luma_sources[dia_id] = str(target)

    repaired_video_clips: list[dict] = []
    for clip in video_track["clips"]:
        dia_id = dialogue_id(clip)
        current = copy.deepcopy(clip)
        if dia_id in luma_sources:
            current["source"] = luma_sources[dia_id]
            current.setdefault("metadata", {})["v15_opening_luma_ramp"] = {
                "seconds": 1.2,
                "brightness": LUMA_REPAIRS[dia_id],
                "video_only": True,
            }
        if dia_id in STRONG_BOUNDARY_PUNCH_INS:
            current["size"] = {"width": 1080, "height": 1920}
            current["position"] = {"x": -180, "y": -320}
            current.setdefault("metadata", {})["v15_strong_boundary_punch_in"] = True
        split_at = INTERNAL_SPLITS.get(dia_id)
        if split_at is None:
            repaired_video_clips.append(current)
            continue
        original_duration = float(current["duration"])
        if not 0.5 < split_at < original_duration - 0.5:
            raise SystemExit(f"Unsafe split for {dia_id}: {split_at}/{original_duration}")
        second = copy.deepcopy(current)
        current["duration"] = split_at
        current.setdefault("metadata", {})["v15_internal_cut_part"] = "A"
        second["id"] = f"{current['id']}-V15B"
        second["start"] = round(float(current["start"]) + split_at, 6)
        second["in"] = round(float(current.get("in", 0.0)) + split_at, 6)
        second["duration"] = round(original_duration - split_at, 6)
        second["size"] = {"width": 1080, "height": 1920}
        second["position"] = {"x": -180, "y": -320}
        second.setdefault("metadata", {})["v15_internal_cut_part"] = "B"
        semantic_group = second["metadata"].get("semantic_group")
        if semantic_group:
            second["metadata"]["semantic_group"] = f"{semantic_group}_CONTINUATION_CUT_B"
        second["metadata"]["cut_reason"] = "DIALOGUE_CONTINUATION_REACTION_PUNCH_IN"
        repaired_video_clips.extend([current, second])
    video_track["clips"] = repaired_video_clips

    normalized = 0
    for track in project["timeline"].get("audioTracks", []):
        for clip in track.get("clips", []):
            if dialogue_id(clip) != "DIA-021":
                continue
            clip["volume"] = 5.76
            clip.setdefault("metadata", {})["v15_source_loudness_repair"] = {
                "source_first_1_5s_mean_db": -44.3,
                "gain_factor_vs_v14": 8.0,
                "final_master_limiter_required": True,
            }
            normalized += 1
    if normalized != 1:
        raise SystemExit(f"Expected one DIA-021 audio clip, found {normalized}")

    project["metadata"].update({
        "status": "V15_FAILED_ONLY_CI_REPAIR_NOT_FINAL",
        "version": "E21_AGENTCUT_V15_FAILED_ONLY_CI_REPAIR",
        "source_project": str(BASE.relative_to(ROOT)),
        "change_scope": "Only V14 frozen-CI failures: long visual segments, one repeat cluster, DIA-021 loudness, and two luma boundaries",
        "internal_split_dialogue_ids": list(INTERNAL_SPLITS),
        "strong_boundary_punch_in_dialogue_ids": sorted(STRONG_BOUNDARY_PUNCH_INS),
        "luma_repair_dialogue_ids": sorted(LUMA_REPAIRS),
        "audio_repair_dialogue_ids": ["DIA-021"],
        "rollback": str(BASE.relative_to(ROOT)),
    })
    project["output"]["path"] = str(OUT_VIDEO)
    OUT_PROJECT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    OUT_QA.mkdir(parents=True, exist_ok=True)
    shots = [{
        "shot_id": clip["id"],
        "scene_id": clip.get("metadata", {}).get("scene_id"),
        "start": clip["start"],
        "end": round(float(clip["start"]) + float(clip["duration"]), 6),
    } for clip in repaired_video_clips]
    OUT_TIMELINE.write_text(json.dumps({
        "schema": "qingshan.final_timeline_shots.v1", "episode": "E21", "version": "V15", "shots": shots,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    audio_starts = sorted({
        round(float(clip["start"]), 6)
        for track in project["timeline"].get("audioTracks", [])
        for clip in track.get("clips", [])
        if float(clip["start"]) > 0.0
    })
    OUT_AUDIO_BOUNDARIES.write_text(json.dumps({
        "schema": "qingshan.audio_edit_boundaries.v1", "episode": "E21", "version": "V15",
        "boundaries": audio_starts, "source": str(OUT_PROJECT.relative_to(ROOT)),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    OUT_RECEIPT.write_text(json.dumps({
        "schema": "qingshan.production.task.v1",
        "task_id": "E21_AGENTCUT_V15_FAILED_ONLY_CI_REPAIR_20260719",
        "episode": "E21",
        "status": "PROJECT_BUILT_PENDING_RENDER",
        "project": str(OUT_PROJECT),
        "output": str(OUT_VIDEO),
        "source_ci": str(CI),
        "source_ci_sha256": hashlib.sha256(CI.read_bytes()).hexdigest(),
        "luma_sources": luma_sources,
        "audio_boundaries": str(OUT_AUDIO_BOUNDARIES),
        "rollback": str(BASE),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "project": str(OUT_PROJECT), "output": str(OUT_VIDEO)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
