#!/usr/bin/env python3
"""Replace one existing visual slot per E21 beat with its reviewed storyboard master."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/e21_agentcut_project_v17_dia021_verified_source_repair_20260719.json"
OUT = ROOT / "configs/e21_agentcut_project_v18_standard_storyboard_coverage_20260719.json"
ADMISSION = ROOT / "workflow/tasks/E21_STANDARD_STORYBOARD_SOURCE_ADMISSION_20260719.json"
QA_DIR = ROOT / "qa/e21_agentcut_v18_standard_storyboard_coverage_20260719"
TIMELINE = QA_DIR / "E21_FINAL_TIMELINE_SHOTS_V18.json"
REVIEW = ROOT / "qa/e21_standard_storyboard_rework_ai_review_20260719/E21_AI_REVIEW_WRAPPER.json"
SOURCES = {
    "B01": ("working_assets/e21_standard_storyboard_rework_r4_b01_object_free_20260719/candidates/E21_E21-B01-STANDARD-STORYBOARD-V1-R4-OBJECT-FREE_19943dd4-0678-4f5a-a505-efd08a94057d.mp4", "ed287dfa1389e87263e888de366019d4ac5ebc544aaacc91a1b93bd061b6653a", "REV-18D92CA7E50E672C"),
    "B02": ("working_assets/e21_standard_storyboard_rework_r3_visual_only_20260719/candidates/E21_E21-B02-STANDARD-STORYBOARD-V1-R3-VISUAL-ONLY_8d9be0be-6c89-41a4-9297-8b68632207e3.mp4", "ffa012b41a244ede7e852708a9a2ea6959b4808d008acc08cc10412b7860f1af", "REV-D12A56DF7F16967E"),
    "B03": ("working_assets/e21_standard_storyboard_rework_r2_textsafe_20260719/candidates/E21_E21-B03-STANDARD-STORYBOARD-V1-R2-TEXTSAFE_50c5f8d9-05fe-452c-89ed-443520fae581.mp4", "d4f6181b4be623e8e93bb4fd70b9333a587595dab80fe960e7ea81d3637a3944", "REV-C6C0AB38A91B1444"),
    "B04": ("working_assets/e21_standard_storyboard_rework_r3_visual_only_20260719/candidates/E21_E21-B04-STANDARD-STORYBOARD-V1-R3-VISUAL-ONLY_f37786dc-2c00-4285-a58e-c1710a0a9da2.mp4", "1f719aa6818d51d8e6e22c272465f669581580a471f571abfcef217d42bd08c6", "REV-801EB0783F3A4E93"),
    "B05": ("working_assets/e21_standard_storyboard_rework_r3_visual_only_20260719/candidates/E21_E21-B05-STANDARD-STORYBOARD-V1-R3-VISUAL-ONLY_b612bfc5-b1c1-41c5-b41a-145b0bf19e5e.mp4", "04832a29828ef78907fe4967e774fee9dd5f8d77aa73136c7a017b2752237fe5", "REV-53EAF0F087BC6ECA"),
    "B06": ("working_assets/e21_standard_storyboard_rework_v1_20260719/candidates/E21_E21-B06-STANDARD-STORYBOARD-V1_8e5e6737-2dec-4180-80df-5c321fead9a0.mp4", "329734a073bc12c01b305b266fba81f242f664a6a376f7a33f11c0383bcd0be6", "REV-6D4BABF43BE2F4FC"),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    project = json.loads(BASE.read_text(encoding="utf-8"))
    source_paths = {}
    admission = []
    for beat, (relative, expected, review_id) in SOURCES.items():
        path = ROOT / relative
        actual = sha256(path)
        if actual != expected:
            raise SystemExit(f"SHA mismatch for {beat}: {actual}")
        source_paths[beat] = str(path)
        admission.append({"beat_id": beat, "path": str(path), "sha256": actual, "review_id": review_id, "status": "PASS"})

    clips = project["timeline"]["videoTracks"][0]["clips"]
    selected = {}
    for index, clip in enumerate(clips):
        beat = (clip.get("metadata") or {}).get("beat_id")
        if beat in source_paths:
            selected[beat] = index
    if sorted(selected) != sorted(SOURCES):
        raise SystemExit(f"Missing beat slots: selected={selected}")
    replacements = []
    for beat, index in sorted(selected.items()):
        clip = clips[index]
        previous = clip["source"]
        clip["source"] = source_paths[beat]
        clip["in"] = 0.0
        clip.setdefault("metadata", {}).update({
            "source_qa": "PASS_STANDARD_STORYBOARD_AND_AI_REVIEW",
            "source_admission": str(ADMISSION),
            "coverage_source_version": "CL2X-356_STANDARD_STORYBOARD_V1",
            "visual_replacement_only": True,
            "audio_source_preserved": True,
            "rollback_video_source": previous,
        })
        replacements.append({"beat_id": beat, "clip_id": clip["id"], "timeline_start": clip["start"], "duration": clip["duration"], "old_source": previous, "new_source": clip["source"]})

    project["metadata"].update({
        "status": "V18_STANDARD_STORYBOARD_COVERAGE_NOT_FINAL",
        "parent_project": str(BASE),
        "rollback": str(BASE),
        "source_admission": str(ADMISSION),
        "ai_review": str(REVIEW),
        "change_scope": "One visual-only replacement per beat; preserve all audio clips, timeline starts, durations and total runtime.",
    })
    project["output"]["path"] = str(ROOT / "exports/e21/agentcut_v18_standard_storyboard_coverage_20260719/E21_AGENTCUT_V18_STANDARD_STORYBOARD_COVERAGE_NOT_FINAL.mp4")
    OUT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    QA_DIR.mkdir(parents=True, exist_ok=True)
    TIMELINE.write_text(json.dumps({
        "schema": "qingshan.final_timeline_shots.v1",
        "episode": "E21",
        "version": "V18",
        "shots": [{
            "shot_id": clip["id"],
            "scene_id": (clip.get("metadata") or {}).get("scene_id"),
            "start": clip["start"],
            "end": round(float(clip["start"]) + float(clip["duration"]), 6),
        } for clip in clips],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ADMISSION.write_text(json.dumps({
        "schema": "qingshan.standard_storyboard_source_admission.v1",
        "episode": "E21",
        "status": "PASS",
        "sources": admission,
        "ai_review": str(REVIEW),
        "agentcut_project": str(OUT),
        "timeline_evidence": str(TIMELINE),
        "replacements": replacements,
        "rollback": str(BASE),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "project": str(OUT), "replacements": replacements}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
