#!/usr/bin/env python3
"""Admit E24/E25 standard-storyboard masters into separate AgentCut projects."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

EPISODES = {
    "E24": {
        "base": "configs/e24_agentcut_project_v1_final_20260719.json",
        "project": "configs/e24_agentcut_project_v2_standard_storyboard_coverage_20260719.json",
        "admission": "workflow/tasks/E24_STANDARD_STORYBOARD_SOURCE_ADMISSION_20260719.json",
        "output": "exports/e24/agentcut_v2_standard_storyboard_coverage_20260719/E24_AGENTCUT_V2_STANDARD_STORYBOARD_COVERAGE_NOT_FINAL.mp4",
        "sources": {
            "B01": "working_assets/e24_standard_storyboard_failed_only_r1_20260719/candidates/E24_E24-B01-STANDARD-STORYBOARD-V1-R1-TEXTSOURCE-REMOVED_582e12b5-014f-4f09-bb3b-eb7d599a2761.mp4",
            "B02": "working_assets/e24_standard_storyboard_rework_v1_20260719/candidates/E24_E24-B02-STANDARD-STORYBOARD-V1_63d7cee1-2afb-4ff7-8e3c-74649d7481e1.mp4",
            "B03": "working_assets/e24_standard_storyboard_failed_only_r1_20260719/candidates/E24_E24-B03-STANDARD-STORYBOARD-V1-R1-TEXTSOURCE-REMOVED_880710ff-747a-44c8-88a3-3a627c08e0cb.mp4",
            "B04": "working_assets/e24_standard_storyboard_failed_only_r1_20260719/candidates/E24_E24-B04-STANDARD-STORYBOARD-V1-R1-TEXTSOURCE-REMOVED_a7b30875-69da-4fd4-aa7a-0765329ea6e8.mp4",
            "B05": "working_assets/e24_standard_storyboard_rework_v1_20260719/candidates/E24_E24-B05-STANDARD-STORYBOARD-V1_cc397d66-1881-4c1f-8626-4d0cc6762550.mp4",
            "B06": "working_assets/e24_standard_storyboard_failed_only_r1_20260719/candidates/E24_E24-B06-STANDARD-STORYBOARD-V1-R1-TEXTSOURCE-REMOVED_c51254e8-14a2-4b23-a475-94ed0d31a420.mp4",
        },
    },
    "E25": {
        "base": "configs/e25_agentcut_project_v1_full_dialogue_20260719.json",
        "project": "configs/e25_agentcut_project_v2_standard_storyboard_coverage_20260719.json",
        "admission": "workflow/tasks/E25_STANDARD_STORYBOARD_SOURCE_ADMISSION_20260719.json",
        "output": "exports/e25/agentcut_v2_standard_storyboard_coverage_20260719/E25_AGENTCUT_V2_STANDARD_STORYBOARD_COVERAGE_NOT_FINAL.mp4",
        "sources": {
            "B01": "working_assets/e25_standard_storyboard_rework_v1_20260719/candidates/E25_E25-B01-STANDARD-STORYBOARD-V1_d1122d03-d640-42da-b821-ee35007e72ab.mp4",
            "B02": "working_assets/e25_standard_storyboard_rework_v1_20260719/candidates/E25_E25-B02-STANDARD-STORYBOARD-V1_10e1abb8-f496-4637-9ec9-4e8149476671.mp4",
            "B03": "working_assets/e25_standard_storyboard_rework_v1_20260719/candidates/E25_E25-B03-STANDARD-STORYBOARD-V1_9217e94d-ec49-4ccd-a314-8a57711f3377.mp4",
            "B04": "working_assets/e25_standard_storyboard_rework_v1_20260719/candidates/E25_E25-B04-STANDARD-STORYBOARD-V1_bb06b4bb-8b4f-4367-8fde-887e1b5ea570.mp4",
            "B05": "working_assets/e25_standard_storyboard_rework_v1_20260719/candidates/E25_E25-B05-STANDARD-STORYBOARD-V1_5df46982-b8dc-47bd-a868-9a2512b9d00f.mp4",
            "B06": "working_assets/e25_standard_storyboard_rework_v1_20260719/candidates/E25_E25-B06-STANDARD-STORYBOARD-V1_cd2b29d5-16c6-45da-8b3a-81ccd5b99004.mp4",
        },
    },
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(episode: str, spec: dict) -> dict:
    base_path = ROOT / spec["base"]
    project_path = ROOT / spec["project"]
    admission_path = ROOT / spec["admission"]
    output_path = ROOT / spec["output"]
    project = json.loads(base_path.read_text(encoding="utf-8"))
    clips = project["timeline"]["videoTracks"][0]["clips"]
    first_slot: dict[str, dict] = {}
    for clip in clips:
        beat_id = str((clip.get("metadata") or {}).get("beat_id") or "")
        if beat_id in spec["sources"] and beat_id not in first_slot:
            first_slot[beat_id] = clip
    missing = sorted(set(spec["sources"]) - set(first_slot))
    if missing:
        raise SystemExit(f"{episode} missing AgentCut beat slots: {missing}")

    replacements = []
    admitted = []
    for beat_id, source_ref in spec["sources"].items():
        source = ROOT / source_ref
        if not source.is_file():
            raise SystemExit(f"{episode} missing admitted source: {source}")
        clip = first_slot[beat_id]
        old_source = clip["source"]
        clip["source"] = str(source)
        clip["in"] = 0.0
        clip.setdefault("metadata", {}).update({
            "source_qa": "PASS_STANDARD_STORYBOARD_OBJECTIVE_AND_AI_REVIEW",
            "source_admission": str(admission_path),
            "coverage_source_version": "CL2X-378_STANDARD_STORYBOARD_V1",
            "visual_replacement_only": True,
            "audio_source_preserved": True,
            "rollback_video_source": old_source,
        })
        source_sha = sha256(source)
        replacements.append({
            "beat_id": beat_id,
            "clip_id": clip["id"],
            "start": clip["start"],
            "duration": clip["duration"],
            "old_source": old_source,
            "new_source": str(source),
        })
        admitted.append({"beat_id": beat_id, "path": str(source), "sha256": source_sha, "status": "PASS"})

    project.setdefault("metadata", {}).update({
        "status": "V2_STANDARD_STORYBOARD_COVERAGE_NOT_FINAL",
        "version": f"{episode}_AGENTCUT_V2_STANDARD_STORYBOARD_COVERAGE",
        "parent_project": str(base_path),
        "rollback": str(base_path),
        "source_admission": str(admission_path),
        "change_scope": "Replace one visual-only slot per beat; preserve every audio clip, timing and runtime.",
    })
    project["output"]["path"] = str(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    admission_path.write_text(json.dumps({
        "schema": "qingshan.standard_storyboard_source_admission.v1",
        "episode": episode,
        "status": "PASS",
        "sources": admitted,
        "agentcut_project": str(project_path),
        "replacements": replacements,
        "rollback": str(base_path),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"episode": episode, "project": str(project_path), "output": str(output_path), "replacements": len(replacements)}


def main() -> int:
    results = [build(episode, spec) for episode, spec in EPISODES.items()]
    print(json.dumps({"status": "PASS", "results": results}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
