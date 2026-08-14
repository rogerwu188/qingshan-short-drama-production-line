#!/usr/bin/env python3
"""Admit the six reviewed E23 storyboard masters into AgentCut coverage slots."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/e23_agentcut_project_v12_roomtone_hiss_repaired_20260719.json"
OUT = ROOT / "configs/e23_agentcut_project_v13_standard_storyboard_coverage_20260719.json"
ADMISSION = ROOT / "workflow/tasks/E23_STANDARD_STORYBOARD_SOURCE_ADMISSION_20260719.json"
REVIEW = ROOT / "qa/e23_standard_storyboard_rework_ai_review_20260719/E23_AI_REVIEW_WRAPPER.json"

SOURCES = {
    "B01": ("working_assets/e23_standard_storyboard_rework_v1_20260719/candidates/E23_E23-B01-STANDARD-STORYBOARD-V1_a4d58378-e7e1-46d6-8b6a-23be26e8187f.mp4", "653addac5a8c61ef9233a810bccf01f2672e5e5a7b45be12e704a3750f5d7d95", "REV-9F629E18B007B5B2"),
    "B02": ("working_assets/e23_standard_storyboard_rework_r2_textsafe_20260719/candidates/E23_E23-B02-STANDARD-STORYBOARD-V1-R2-TEXTSAFE_7cff4a8b-cd75-4362-ae04-03579d484b87.mp4", "9ff52237ee5ab27691eb084c3b97f7bf9b392849a0cfa7fe37cad338c1bc024b", "REV-B728DC350CCAD37D"),
    "B03": ("working_assets/e23_standard_storyboard_rework_r2_textsafe_20260719/candidates/E23_E23-B03-STANDARD-STORYBOARD-V1-R2-TEXTSAFE_7ee5be2b-1373-4b3a-8262-cfdde5288219.mp4", "da89d184349552162c08a8e2daf8cf22ee16f9c19d354204702bf103eb6ab441", "REV-E7A4AC8AC5D76BB5"),
    "B04": ("working_assets/e23_standard_storyboard_rework_v1_20260719/candidates/E23_E23-B04-STANDARD-STORYBOARD-V1_fe297c07-ca0a-4529-a639-0a1bf9a36b84.mp4", "6f6a0ee39f6dd16d52aabdb06648768a59c3c3d10c5def0b4db5dc47e2cc087d", "REV-30D1C080C3B93EF0"),
    "B05": ("working_assets/e23_standard_storyboard_rework_v1_20260719/candidates/E23_E23-B05-STANDARD-STORYBOARD-V1_e02da7a6-8b99-43f8-bc5b-1b1ca18fdba2.mp4", "e896af18e3afcc3b0841fb360a005a613c8b0154fba4375dbdfeac1a59a929b8", "REV-1B64BCAD1415997B"),
    "B06": ("working_assets/e23_standard_storyboard_rework_v1_20260719/candidates/E23_E23-B06-STANDARD-STORYBOARD-V1_d0bfcbce-05ed-4875-9541-ad213da268b6.mp4", "005fa7cde899049e1f51776ecb3903a96ec9d40d3fb7f759ca71fff1e1808fc2", "REV-8B5D39E6842331F0"),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    project = json.loads(BASE.read_text(encoding="utf-8"))
    admitted = []
    absolute_sources = {}
    for beat, (relative, expected_sha, review_id) in SOURCES.items():
        path = ROOT / relative
        actual_sha = sha256(path)
        if actual_sha != expected_sha:
            raise SystemExit(f"SHA mismatch for {beat}: {actual_sha}")
        absolute_sources[beat] = str(path)
        admitted.append({
            "beat_id": beat,
            "path": str(path),
            "sha256": actual_sha,
            "source_qa": "PASS",
            "ai_review": "PASS_WITH_NONBLOCKING_WARNINGS",
            "review_id": review_id,
        })

    replaced_video = []
    preserved_audio = []
    for track in project["timeline"]["videoTracks"]:
        for clip in track["clips"]:
            beat = (clip.get("metadata") or {}).get("beat_id")
            if beat in absolute_sources and "COVERAGE" in clip.get("id", ""):
                clip["source"] = absolute_sources[beat]
                clip.setdefault("metadata", {}).update({
                    "source_qa": "PASS_STANDARD_STORYBOARD_AND_AI_REVIEW",
                    "source_admission": str(ADMISSION),
                    "coverage_source_version": "CL2X-356_STANDARD_STORYBOARD_V1",
                    "audio_policy": "NATIVE_SFX_AMBIENCE_NO_DIALOGUE_NO_EXTERNAL_BGM",
                })
                replaced_video.append(beat)
    for track in project["timeline"]["audioTracks"]:
        for clip in track["clips"]:
            if "COVERAGE" not in clip.get("id", ""):
                continue
            preserved_audio.append(clip["id"])
    if sorted(replaced_video) != sorted(SOURCES) or len(preserved_audio) != 6:
        raise SystemExit(f"Expected six video replacements and six preserved audio slots, got video={replaced_video}, audio={preserved_audio}")

    project = copy.deepcopy(project)
    project["metadata"].update({
        "status": "STANDARD_STORYBOARD_COVERAGE_ADMITTED_NOT_FINAL",
        "project_id": "E23_AGENTCUT_V13_STANDARD_STORYBOARD_COVERAGE",
        "parent_project": str(BASE),
        "rollback": str(BASE),
        "source_admission": str(ADMISSION),
        "ai_review": str(REVIEW),
        "change_scope": "Replace only the six 3-second motivated video coverage slots; preserve 24 admitted dialogue clips, timing, and all existing audio sources.",
    })
    project["output"]["path"] = str(ROOT / "exports/e23/agentcut_v13_standard_storyboard_coverage_20260719/E23_AGENTCUT_V13_STANDARD_STORYBOARD_COVERAGE_NOT_FINAL.mp4")
    OUT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ADMISSION.parent.mkdir(parents=True, exist_ok=True)
    ADMISSION.write_text(json.dumps({
        "schema": "qingshan.standard_storyboard_source_admission.v1",
        "episode": "E23",
        "status": "PASS",
        "source_count": len(admitted),
        "sources": admitted,
        "ai_review_batch": str(REVIEW),
        "agentcut_project": str(OUT),
        "replacement_scope": {"video_coverage_slots": replaced_video, "preserved_audio_sfx_slots": preserved_audio},
        "rollback": str(BASE),
        "recorded_at": now,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "project": str(OUT), "admission": str(ADMISSION), "replaced_video": replaced_video, "preserved_audio": preserved_audio}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
