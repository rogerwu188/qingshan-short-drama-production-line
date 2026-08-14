#!/usr/bin/env python3
"""Build one concurrent video batch from the admitted E21 V7 boundary stills."""

from __future__ import annotations

import json
from pathlib import Path

from build_e21_v7_missing_boundary_stills import COMPOSITIONS
from shot_duration_policy import plan_dialogue_duration


ROOT = Path(__file__).resolve().parents[1]
STILL_RECEIPT = ROOT / "workflow/tasks/E21_v7_missing_boundary_stills_receipt_20260719.json"
PROJECT = ROOT / "configs/e21_agentcut_project_v6_tail_trim_20260719.json"
PROMPT_DIR = ROOT / "workflow/prompts/e21_v7_missing_boundary_videos_20260719"
CONFIG = ROOT / "workflow/tasks/E21_v7_missing_boundary_videos_config_20260719.json"

SCENE_TEXT = {
    "E21-S01-MEDICAL-HALL-THRESHOLD": "at the medical hall threshold at night after rain, with only eave drips",
    "E21-S02-ESCAPE-ALLEY": "from the medical hall front door into the wet narrow alley at night, after rain with no downpour",
    "E21-S03-REAR-NARROW-DOOR": "at the rear-house narrow door and threshold at night, with still air and only an occasional drip",
}


def main() -> int:
    receipt = json.loads(STILL_RECEIPT.read_text(encoding="utf-8"))
    stills = {
        task["dialogue_id"]: task
        for task in receipt.get("tasks", [])
        if task.get("status") == "image_pass" and task.get("output_path")
    }
    if set(stills) != set(COMPOSITIONS):
        raise SystemExit(f"expected 16 admitted stills, found {len(stills)}")
    project = json.loads(PROJECT.read_text(encoding="utf-8"))
    clips = {
        clip["metadata"]["dialogue_id"]: clip
        for track in project["timeline"]["videoTracks"]
        for clip in track.get("clips", [])
    }
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    tasks = []
    for dialogue_id, still in stills.items():
        meta = clips[dialogue_id]["metadata"]
        duration_plan = plan_dialogue_duration(
            meta["exact_dialogue"],
            "medium",
            meta.get("narrative_function") or meta["exact_dialogue"],
            performance_context=COMPOSITIONS[dialogue_id],
        )
        duration = int(duration_plan["duration_seconds"])
        prompt = (
            f"Animate the supplied locked frame as one continuous vertical 9:16 multimodal source {SCENE_TEXT[meta['scene_id']]}. "
            "Preserve the exact composition, identities, costumes, props, practical lantern lighting and established 180-degree axis. "
            f"Begin immediately on this distinct frame. {meta['speaker']} performs the visible beat once and speaks exactly once in natural "
            f"Mandarin: \"{meta['exact_dialogue']}\" Only {meta['speaker']} speaks. Target {duration} seconds at native speed, with synchronized "
            "dialogue, practical ambience and effects. Motion must remain continuous and non-repeating. No external BGM, readable text, "
            "pseudo-writing, document face, subtitle, caption, logo, watermark, repeated pose, periodic duplicate cadence, cyclic gesture, "
            "slow motion, paraphrase, extra dialogue, invented event, location, weather, character or prop."
        )
        prompt_path = PROMPT_DIR / f"{dialogue_id}.txt"
        prompt_path.write_text(prompt + "\n", encoding="utf-8")
        tasks.append({
            "task_key": f"E21-{dialogue_id}-VIDEO-V7-MISSING-BOUNDARY",
            "tool_type": "video_generation",
            "source_id": dialogue_id,
            "dialogue_id": dialogue_id,
            "dia_id": dialogue_id,
            "beat_id": meta["beat_id"],
            "scene_id": meta["scene_id"],
            "visual_zone": still["visual_zone"].replace("STILL", "VIDEO"),
            "speaker": meta["speaker"],
            "exact_dialogue": meta["exact_dialogue"],
            "duration_seconds": duration,
            "duration": duration,
            "duration_plan": duration_plan,
            "model": "seedance-2.0-pro",
            "aspect_ratio": "9:16",
            "resolution": "720p",
            "prompt_file": str(prompt_path.relative_to(ROOT)),
            "reference_images": [still["output_path"]],
            "status": "READY_FOR_PARALLEL_SUBMIT",
        })
    payload = {
        "schema": "qingshan.episode_parallel_prompt_batch.v1",
        "episode": "E21",
        "scene_contract_ref": "configs/e21_scene_state_v1_20260718.json",
        "qa_dir": "qa/e21_v7_missing_boundary_videos_20260719",
        "output_dir": "working_assets/e21_v7_missing_boundary_videos_20260719/candidates",
        "max_retries": 1,
        "base_batch_note": "Submit all 16 missing-boundary videos concurrently with per-dialogue dynamic durations; preserve all already detected V6 boundaries.",
        "tasks": tasks,
    }
    CONFIG.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PASS",
        "tasks": len(tasks),
        "durations": {task["dialogue_id"]: task["duration_seconds"] for task in tasks},
        "config": str(CONFIG),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
