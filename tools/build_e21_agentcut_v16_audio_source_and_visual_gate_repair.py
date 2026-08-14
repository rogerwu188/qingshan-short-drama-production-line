#!/usr/bin/env python3
"""Build E21 V16 by repairing only residual V15 frozen-CI failures."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/e21_agentcut_project_v15_failed_only_ci_repair_20260719.json"
ORIGINAL = ROOT / "configs/e21_agentcut_project_v14_runtime_and_cut_separation_repair_20260719.json"
CI = ROOT / "qa/e21_agentcut_v15_failed_only_ci_repair_20260719/E21_REGRESSION_CI_V15_FROZEN_THRESHOLDS.json"
OUT_PROJECT = ROOT / "configs/e21_agentcut_project_v16_audio_source_and_visual_gate_repair_20260719.json"
OUT_QA = ROOT / "qa/e21_agentcut_v16_audio_source_and_visual_gate_repair_20260719"
OUT_TIMELINE = OUT_QA / "E21_FINAL_TIMELINE_SHOTS_V16.json"
OUT_AUDIO_BOUNDARIES = OUT_QA / "E21_AUDIO_EDIT_BOUNDARIES_V16.json"
OUT_RECEIPT = ROOT / "workflow/tasks/E21_AGENTCUT_V16_AUDIO_SOURCE_AND_VISUAL_GATE_REPAIR_20260719.json"
OUT_VIDEO = ROOT / "exports/e21/agentcut_v16_audio_source_and_visual_gate_repair_20260719/E21_AGENTCUT_V16_AUDIO_SOURCE_AND_VISUAL_GATE_REPAIR_NOT_FINAL.mp4"
ASSET_DIR = ROOT / "working_assets/e21_v16_failed_only_ci_repair_20260719"

EXPECTED_FAILURES = {
    "too_many_long_shots:7",
    "repeated_frame_cluster:3",
    "speech_density_below_threshold:14.35",
    "scene_luma_jump:E21-DIA-007-VIDEO->E21-DIA-008-VIDEO:25.26",
    "scene_luma_jump:E21-DIA-024-VIDEO->E21-DIA-025-VIDEO:26.88",
}
REFRAMES = {
    "DIA-007": (0, -640),
    "DIA-009-B": (-720, -640),
    "DIA-010-B": (0, -640),
    "DIA-013": (-720, -640),
    "DIA-016": (0, -640),
    "DIA-017": (-720, -640),
    "DIA-018-B": (0, -640),
    "DIA-024": (-720, -640),
    "DIA-026": (0, -640),
}
LUMA_REPAIRS = {"DIA-008": 0.030, "DIA-025": 0.050}


def dialogue_id(clip: dict) -> str | None:
    explicit = clip.get("metadata", {}).get("dialogue_id") or clip.get("dialogue_id")
    if explicit:
        return explicit
    for index in range(1, 38):
        candidate = f"DIA-{index:03d}"
        if candidate in clip.get("id", ""):
            return candidate
    return None


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def make_luma_source(source: Path, target: Path, brightness: float) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    expression = f"eq=brightness='{brightness}*(1-min(t/1.2\\,1))':eval=frame"
    run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
        "-vf", expression, "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264",
        "-preset", "medium", "-crf", "17", "-c:a", "copy", "-movflags", "+faststart", str(target),
    ])


def make_audio_source(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
        "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy", "-af", "volume=18dB",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(target),
    ])


def main() -> int:
    project = json.loads(BASE.read_text(encoding="utf-8"))
    original = json.loads(ORIGINAL.read_text(encoding="utf-8"))
    ci = json.loads(CI.read_text(encoding="utf-8"))
    if set(ci.get("failures", [])) != EXPECTED_FAILURES:
        raise SystemExit(f"Unexpected V15 failure set: {ci.get('failures')}")

    original_video_sources = {
        dialogue_id(clip): Path(clip["source"])
        for clip in original["timeline"]["videoTracks"][0]["clips"]
    }
    luma_sources: dict[str, str] = {}
    for dia_id, brightness in LUMA_REPAIRS.items():
        target = ASSET_DIR / f"E21_{dia_id}_V16_OPENING_LUMA_RAMP.mp4"
        make_luma_source(original_video_sources[dia_id], target, brightness)
        luma_sources[dia_id] = str(target)

    for clip in project["timeline"]["videoTracks"][0]["clips"]:
        dia_id = dialogue_id(clip)
        if dia_id in luma_sources:
            clip["source"] = luma_sources[dia_id]
            clip.setdefault("metadata", {})["v16_opening_luma_ramp"] = {
                "seconds": 1.2, "brightness": LUMA_REPAIRS[dia_id], "video_only": True,
            }
        key = f"{dia_id}-B" if clip.get("id", "").endswith("-V15B") else dia_id
        if key in REFRAMES:
            x, y = REFRAMES[key]
            clip["size"] = {"width": 1440, "height": 2560}
            clip["position"] = {"x": x, "y": y}
            clip.setdefault("metadata", {})["v16_detectable_reaction_reframe"] = {
                "scale": 2.0, "position": {"x": x, "y": y},
            }

    audio_repaired = 0
    for track in project["timeline"].get("audioTracks", []):
        for clip in track.get("clips", []):
            if dialogue_id(clip) != "DIA-021":
                continue
            source = Path(clip["source"])
            normalized = ASSET_DIR / "E21_DIA-021_V16_SOURCE_AUDIO_PLUS18DB.mp4"
            make_audio_source(source, normalized)
            clip["source"] = str(normalized)
            clip["volume"] = 0.72
            clip.setdefault("metadata", {})["v16_source_audio_normalization"] = {
                "gain_db": 18.0,
                "reason": "V15 timeline gain caused global premaster attenuation and reduced ASR density",
                "rollback_source": str(source),
            }
            audio_repaired += 1
    if audio_repaired != 1:
        raise SystemExit(f"Expected one DIA-021 audio clip, found {audio_repaired}")

    project["metadata"].update({
        "status": "V16_AUDIO_SOURCE_AND_VISUAL_GATE_REPAIR_NOT_FINAL",
        "version": "E21_AGENTCUT_V16_AUDIO_SOURCE_AND_VISUAL_GATE_REPAIR",
        "source_project": str(BASE.relative_to(ROOT)),
        "change_scope": "Only V15 residual failures: source-level DIA-021 audio normalization, detectable reaction reframes, and two opening luma ramps",
        "rollback": str(BASE.relative_to(ROOT)),
    })
    project["output"]["path"] = str(OUT_VIDEO)
    OUT_PROJECT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    OUT_QA.mkdir(parents=True, exist_ok=True)
    video_clips = project["timeline"]["videoTracks"][0]["clips"]
    OUT_TIMELINE.write_text(json.dumps({
        "schema": "qingshan.final_timeline_shots.v1", "episode": "E21", "version": "V16",
        "shots": [{
            "shot_id": clip["id"], "scene_id": clip.get("metadata", {}).get("scene_id"),
            "start": clip["start"], "end": round(float(clip["start"]) + float(clip["duration"]), 6),
        } for clip in video_clips],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    boundaries = sorted({
        round(float(clip["start"]), 6)
        for track in project["timeline"].get("audioTracks", [])
        for clip in track.get("clips", [])
        if float(clip["start"]) > 0.0
    })
    OUT_AUDIO_BOUNDARIES.write_text(json.dumps({
        "schema": "qingshan.audio_edit_boundaries.v1", "episode": "E21", "version": "V16",
        "boundaries": boundaries, "source": str(OUT_PROJECT.relative_to(ROOT)),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    OUT_RECEIPT.write_text(json.dumps({
        "schema": "qingshan.production.task.v1",
        "task_id": "E21_AGENTCUT_V16_AUDIO_SOURCE_AND_VISUAL_GATE_REPAIR_20260719",
        "episode": "E21", "status": "PROJECT_BUILT_PENDING_RENDER",
        "project": str(OUT_PROJECT), "output": str(OUT_VIDEO),
        "source_ci": str(CI), "source_ci_sha256": hashlib.sha256(CI.read_bytes()).hexdigest(),
        "luma_sources": luma_sources, "audio_boundaries": str(OUT_AUDIO_BOUNDARIES),
        "rollback": str(BASE),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "project": str(OUT_PROJECT), "output": str(OUT_VIDEO)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
