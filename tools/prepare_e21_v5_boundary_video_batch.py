#!/usr/bin/env python3
"""Compile the twenty E21 V5 boundary videos for one concurrent submit."""

from __future__ import annotations

import json
from pathlib import Path

from prepare_e21_v5_boundary_still_batch import COMPOSITIONS
from shot_duration_policy import plan_dialogue_duration


ROOT = Path(__file__).resolve().parents[1]
STILL_RECEIPT = ROOT / "workflow/tasks/E21_v5_boundary_stills_parallel_receipt_20260719.json"
PROJECT = ROOT / "configs/e21_agentcut_project_v4_us_drama_rewrite_20260719.json"
PROMPT_DIR = ROOT / "workflow/prompts/e21_v5_boundary_video_parallel_20260719"
CONFIG = ROOT / "workflow/tasks/E21_v5_boundary_video_parallel_config_20260719.json"


SCENE_TEXT = {
    "E21-S01-MEDICAL-HALL-THRESHOLD": "at the medical hall threshold at night after the rain has stopped, with only eave drips",
    "E21-S02-ESCAPE-ALLEY": "from the medical hall front door into the wet narrow alley at night, rain-stopped with no downpour",
    "E21-S03-REAR-NARROW-DOOR": "at the rear-house narrow door and threshold at night, with still air, wet stone and only an occasional drip",
}


def main() -> int:
    receipt = json.loads(STILL_RECEIPT.read_text(encoding="utf-8"))
    stills = {
        task["dialogue_id"]: task
        for task in receipt.get("tasks", [])
        if task.get("state") == "image_pass" and task.get("output_path")
    }
    if len(stills) != 20:
        raise SystemExit(f"expected 20 admitted stills, found {len(stills)}")

    project = json.loads(PROJECT.read_text(encoding="utf-8"))
    clips = {
        clip["metadata"]["dialogue_id"]: clip
        for track in project["timeline"]["videoTracks"]
        for clip in track.get("clips", [])
    }
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    tasks = []
    for dia_id, still in stills.items():
        clip = clips[dia_id]
        meta = clip["metadata"]
        duration_plan = plan_dialogue_duration(
            meta["exact_dialogue"],
            "medium",
            meta.get("narrative_function") or meta["exact_dialogue"],
            performance_context=COMPOSITIONS[dia_id],
        )
        duration = int(duration_plan["duration_seconds"])
        scene_text = SCENE_TEXT[meta["scene_id"]]
        prompt = (
            f"Animate the supplied shot-specific locked still as one continuous vertical 9:16 multimodal source {scene_text}. "
            "Preserve the exact locked composition, identities, costumes, props, practical lantern lighting and established 180-degree axis. "
            f"Begin immediately on the new shot-specific frame. {meta['speaker']} performs the visible narrative action once and speaks exactly once "
            f"in natural Mandarin: \"{meta['exact_dialogue']}\" Only {meta['speaker']} speaks. Target {duration} seconds at native speed with synchronized "
            "practical ambience and effects. Keep motion continuous and non-repeating. NEGATIVE_PROMPT: No external BGM; no readable text, pseudo-writing, "
            "document face, subtitle, caption, logo, watermark, shared establishing master, repeated pose, periodic duplicate cadence, cyclic gesture, slow motion, "
            "paraphrase, extra dialogue, invented event, location, weather, character or prop.\n"
        )
        prompt_path = PROMPT_DIR / f"{dia_id}.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        tasks.append({
            "task_key": f"E21-{dia_id}-VIDEO-V5-BOUNDARY",
            "tool_type": "video_generation",
            "source_id": dia_id,
            "dialogue_id": dia_id,
            "dia_id": dia_id,
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
        "qa_dir": "qa/e21_v5_boundary_video_parallel_20260719",
        "output_dir": "working_assets/e21_v5_boundary_video_parallel_20260719/candidates",
        "max_retries": 1,
        "base_batch_note": "Twenty missing V4 visual boundaries submitted concurrently from twenty admitted shot-specific stills; preserve the seventeen already detected sources.",
        "tasks": tasks,
    }
    CONFIG.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "tasks": len(tasks), "config": str(CONFIG)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
