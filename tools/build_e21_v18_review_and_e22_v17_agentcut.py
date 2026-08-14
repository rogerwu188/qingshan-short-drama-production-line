#!/usr/bin/env python3
"""Start E21 V18 full-cut review and build E22 V17 storyboard coverage."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
E21_VIDEO = ROOT / "exports/e21/agentcut_v18_standard_storyboard_coverage_20260719/E21_AGENTCUT_V18_STANDARD_STORYBOARD_COVERAGE_NOT_FINAL.mp4"
E21_QA = ROOT / "qa/e21_agentcut_v18_standard_storyboard_coverage_20260719"
E21_REQUEST = E21_QA / "E21_AI_REVIEW_REQUEST.json"
E21_CONFIG = ROOT / "configs/E21_agentcut_v18_ai_review_20260719.json"

E22_BASE = ROOT / "configs/e22_agentcut_project_v16_dia016_luma_repair_20260719.json"
E22_OUT = ROOT / "configs/e22_agentcut_project_v17_standard_storyboard_coverage_20260719.json"
E22_ADMISSION = ROOT / "workflow/tasks/E22_STANDARD_STORYBOARD_SOURCE_ADMISSION_20260719.json"
E22_QA = ROOT / "qa/e22_agentcut_v17_standard_storyboard_coverage_20260719"
E22_TIMELINE = E22_QA / "E22_FINAL_TIMELINE_SHOTS_V17.json"
E22_VIDEO = ROOT / "exports/e22/agentcut_v17_standard_storyboard_coverage_20260719/E22_AGENTCUT_V17_STANDARD_STORYBOARD_COVERAGE_NOT_FINAL.mp4"
E22_SOURCES = {
    "B01": ("working_assets/e22_standard_storyboard_rework_v1_20260719/candidates/E22_E22-B01-STANDARD-STORYBOARD-V1_a3726948-2a30-46c9-afe4-51e37fb99117.mp4", "REV-7D116769E0BD4F4C"),
    "B02": ("working_assets/e22_standard_storyboard_rework_v1_20260719/candidates/E22_E22-B02-STANDARD-STORYBOARD-V1_2ea41fc2-13bb-4624-8e9e-098d07fef979.mp4", "REV-DFBF8FD75F77DB46"),
    "B03": ("working_assets/e22_standard_storyboard_rework_r2_textsafe_20260719/candidates/E22_E22-B03-STANDARD-STORYBOARD-V1-R2-TEXTSAFE_aae9c116-75d6-4be0-bf09-6766ebae6cca.mp4", "REV-6C5C6E44C4F1E8EA"),
    "B04": ("working_assets/e22_standard_storyboard_rework_v1_20260719/candidates/E22_E22-B04-STANDARD-STORYBOARD-V1_8035a0a7-88d1-4e9e-a8ae-d8d5692088d2.mp4", "REV-1957C52D09817A9B"),
    "B05": ("working_assets/e22_standard_storyboard_rework_r3_b05_b06_object_free_20260719/candidates/E22_E22-B05-STANDARD-STORYBOARD-V1-R3-OBJECT-FREE_fc66131d-dd98-404e-b57d-eee520488b93.mp4", "REV-6319B65304F40519"),
    "B06": ("working_assets/e22_standard_storyboard_rework_r4_b06_reference_clean_20260719/candidates/E22_E22-B06-STANDARD-STORYBOARD-V1-R4-REFERENCE-CLEAN_b9bbf364-aef7-4146-83cc-063165e2503a.mp4", "REV-52F59677E78F1078"),
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_e21() -> None:
    E21_REQUEST.write_text(json.dumps({"items": [{
        "path": str(E21_VIDEO),
        "scope": "full_cut",
        "kind": "video",
        "importance": "critical",
        "pass_score": 4.5,
        "clip_id": "E21-AGENTCUT-V18-FULL-CUT",
        "metadata": {
            "episode": "E21",
            "candidate_sha256": sha(E21_VIDEO),
            "acceptance_mode": "FINAL_CUT_AI_REVIEW_AFTER_OBJECTIVE_QA",
            "review_focus": ["human viewing experience", "story clarity", "pacing", "identity continuity", "motivated cuts", "no visual contamination"],
        },
        "required_capabilities": ["media_probe", "video_analysis", "audio_analysis", "ocr"],
        "run_regression_ci": True,
        "use_existing_tools": True,
    }]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    E21_CONFIG.write_text(json.dumps({
        "schema": "qingshan.episode_parallel_prompt_batch.v1",
        "episode": "E21",
        "scene_contract_ref": "configs/e21_scene_state_v1_20260718.json",
        "output_dir": str(E21_QA.relative_to(ROOT)),
        "qa_dir": str(E21_QA.relative_to(ROOT)),
        "max_retries": 0,
        "base_batch_note": "Full-cut AI review after all five V18 objective QA gates passed.",
        "tasks": [{
            "task_key": "E21-AGENTCUT-V18-FULL-CUT-AI-REVIEW",
            "tool_type": "ai_review",
            "scene_id": "E21-S01-MEDICAL-HALL-THRESHOLD",
            "visual_zone": "FULL_CUT_AI_REVIEW",
            "prompt_file": "workflow/prompts/e21_v2_us_drama_parallel_20260719/videos/DIA-001.txt",
            "video": str(E21_VIDEO.relative_to(ROOT)),
            "command": [".ai_review_env/bin/qingshan-review", "review-many", str(E21_REQUEST.relative_to(ROOT))],
            "report": str((E21_QA / "E21_AI_REVIEW_WRAPPER.json").relative_to(ROOT)),
        }],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_e22() -> None:
    project = json.loads(E22_BASE.read_text(encoding="utf-8"))
    sources = {beat: str(ROOT / row[0]) for beat, row in E22_SOURCES.items()}
    admitted = [{"beat_id": beat, "path": sources[beat], "sha256": sha(Path(sources[beat])), "review_id": row[1], "status": "PASS"} for beat, row in E22_SOURCES.items()]
    clips = project["timeline"]["videoTracks"][0]["clips"]
    selected = {}
    for index, clip in enumerate(clips):
        beat = (clip.get("metadata") or {}).get("beat_id")
        if beat in sources:
            selected[beat] = index
    if sorted(selected) != sorted(sources):
        raise SystemExit(f"Missing E22 beat slots: {selected}")
    replacements = []
    for beat, index in sorted(selected.items()):
        clip = clips[index]
        old = clip["source"]
        clip["source"] = sources[beat]
        clip["in"] = 0.0
        clip.setdefault("metadata", {}).update({
            "source_qa": "PASS_STANDARD_STORYBOARD_AND_AI_REVIEW",
            "source_admission": str(E22_ADMISSION),
            "coverage_source_version": "CL2X-356_STANDARD_STORYBOARD_V1",
            "visual_replacement_only": True,
            "audio_source_preserved": True,
            "rollback_video_source": old,
        })
        replacements.append({"beat_id": beat, "clip_id": clip["id"], "start": clip["start"], "duration": clip["duration"], "old_source": old, "new_source": clip["source"]})
    project["metadata"].update({
        "status": "V17_STANDARD_STORYBOARD_COVERAGE_NOT_FINAL",
        "version": "E22_AGENTCUT_V17_STANDARD_STORYBOARD_COVERAGE",
        "parent_project": str(E22_BASE),
        "rollback": str(E22_BASE),
        "source_admission": str(E22_ADMISSION),
        "change_scope": "Replace one visual-only slot per beat; preserve every audio clip, timing and full runtime.",
    })
    project["output"]["path"] = str(E22_VIDEO)
    E22_OUT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    E22_QA.mkdir(parents=True, exist_ok=True)
    E22_TIMELINE.write_text(json.dumps({
        "schema": "qingshan.final_timeline_shots.v1",
        "episode": "E22",
        "version": "V17",
        "shots": [{"shot_id": clip["id"], "scene_id": (clip.get("metadata") or {}).get("scene_id"), "start": clip["start"], "end": round(float(clip["start"]) + float(clip["duration"]), 6)} for clip in clips],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    E22_ADMISSION.write_text(json.dumps({
        "schema": "qingshan.standard_storyboard_source_admission.v1",
        "episode": "E22",
        "status": "PASS",
        "sources": admitted,
        "agentcut_project": str(E22_OUT),
        "replacements": replacements,
        "rollback": str(E22_BASE),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    build_e21()
    build_e22()
    print(json.dumps({"status": "PASS", "e21_review": str(E21_CONFIG), "e22_project": str(E22_OUT), "e22_output": str(E22_VIDEO)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
