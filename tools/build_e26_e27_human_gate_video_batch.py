#!/usr/bin/env python3
"""Build the four source-isolated E26/E27 human-gate video retries."""

from __future__ import annotations

import copy
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_json(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def select(config: dict, source_ids: set[str]) -> list[dict]:
    return [copy.deepcopy(task) for task in config["tasks"] if task.get("source_id") in source_ids]


def main() -> int:
    e26 = read_json("configs/E26_standard_storyboard_v4_sheetbound_20260719.json")
    e27 = read_json("configs/E27_standard_storyboard_v4_sheetbound_20260719.json")
    tasks = select(e26, {"B06-P1", "B06-P2"}) + select(e27, {"B02-P1", "B04-P1"})
    image_by_key = {
        "E26-B06-P1-STANDARD-STORYBOARD-V1": "working_assets/e26_e27_human_gate_failed_only_images_r1_20260720/candidates/E26_E27_E26-B06-TEXTSAFE-SCENE-R1_414b8cb5-03ab-41ef-ad0e-e8ade3026417.png",
        "E26-B06-P2-STANDARD-STORYBOARD-V1": "working_assets/e26_e27_human_gate_failed_only_images_r1_20260720/candidates/E26_E27_E26-B06-TEXTSAFE-SCENE-R1_414b8cb5-03ab-41ef-ad0e-e8ade3026417.png",
        "E27-B02-P1-STANDARD-STORYBOARD-V1": "working_assets/e26_e27_human_gate_failed_only_images_r1_20260720/candidates/E26_E27_E27-B02-TEXTSAFE-SCENE-R1_3a63192e-6c64-4a83-9f54-ec186b22e716.png",
        "E27-B04-P1-STANDARD-STORYBOARD-V1": "working_assets/e26_e27_human_gate_failed_only_images_r1_20260720/candidates/E26_E27_E27-B04-TEXTSAFE-SCENE-R1_7b154478-24dc-45db-ad40-2ce9131049de.png",
    }
    prompt_by_key = {
        key: f"workflow/prompts/e26_e27_human_gate_failed_only_videos_r1_20260720/{key.split('-STANDARD-')[0]}.txt"
        for key in image_by_key
    }
    for task in tasks:
        old_key = task["task_key"]
        task["task_key"] = f"{old_key}-HUMAN-GATE-R1"
        task["retry_of_task_key"] = old_key
        task["reference_images"] = [image_by_key[old_key]]
        task["prompt_file"] = prompt_by_key[old_key]
        task["duration_plan"]["policy"] = "qingshan.shot_generation_duration.v4"
        task["status"] = "READY_FOR_PARALLEL_SUBMIT"

    output = {
        "schema": "qingshan.episode_parallel_prompt_batch.v1",
        "episode": "E26_E27",
        "status": "READY_FOR_PARALLEL_SUBMIT",
        "parallel_submission": True,
        "concurrency": 4,
        "max_retries": 0,
        "scene_contract_ref": "configs/e26_e27_human_gate_repair_scene_state_v1_20260720.json",
        "output_dir": "working_assets/e26_e27_human_gate_failed_only_videos_r1_20260720/candidates",
        "qa_dir": "qa/e26_e27_human_gate_failed_only_videos_r1_20260720",
        "base_batch_note": "Retry only four human-viewing-gate failures; preserve every previously passed source and its native audio.",
        "tasks": tasks,
    }
    path = ROOT / "configs/E26_E27_human_gate_failed_only_video_batch_r1_20260720.json"
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"config": str(path), "task_count": len(tasks)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
