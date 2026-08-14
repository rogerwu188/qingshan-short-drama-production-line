#!/usr/bin/env python3
"""Build the concurrent E21 V7 failed-only cadence repair batch."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/tasks/E21_v7_missing_boundary_videos_config_20260719.json"
PROMPT_DIR = ROOT / "workflow/prompts/e21_v7_failed_only_r2_20260719"
CONFIG = ROOT / "workflow/tasks/E21_v7_failed_only_r2_config_20260719.json"
MOTION = {
    "DIA-002": "Chen Ji leans in, changes his head angle, tightens his brow and shifts his questioning eye-line while the messenger shoulder at frame edge reacts and eave drips keep moving",
    "DIA-004": "Bai Li steps half a pace into frame, raises then lowers the stopping hand, shifts weight and turns her shoulders while both listeners make distinct restrained reactions",
    "DIA-017": "the messenger steps back, turns his shoulders toward escape, shifts his gaze between both investigators and tightens his jaw while cloth edges and eave drips continue moving",
}


def main() -> int:
    base = json.loads(BASE.read_text(encoding="utf-8"))
    source_tasks = {task["dialogue_id"]: task for task in base["tasks"]}
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    tasks = []
    for dialogue_id, motion in MOTION.items():
        task = dict(source_tasks[dialogue_id])
        duration = int(task["duration_seconds"])
        prompt = (
            "Animate the supplied locked frame at the medical hall threshold at night after rain, with only eave drips. Preserve identities, "
            "costumes, props, practical lantern lighting, composition and 180-degree axis. Begin the performance immediately and keep "
            f"continuous native-speed motion for the full {duration} seconds: {motion}. {task['speaker']} speaks exactly once in natural "
            f"Mandarin: \"{task['exact_dialogue']}\" Only {task['speaker']} speaks. Keep synchronized practical ambience and effects. "
            "No external BGM, frozen hold, repeated pose, periodic duplicate cadence, cyclic gesture, slow motion, readable text, subtitle, "
            "logo, paraphrase, extra dialogue, invented event, location, weather, character or prop."
        )
        prompt_path = PROMPT_DIR / f"{dialogue_id}.txt"
        prompt_path.write_text(prompt + "\n", encoding="utf-8")
        task.update({
            "task_key": f"E21-{dialogue_id}-VIDEO-V7-R2-CADENCE",
            "prompt_file": str(prompt_path.relative_to(ROOT)),
            "status": "READY_FOR_PARALLEL_SUBMIT",
            "repair_reason": "V7 frame-cadence terminal failure only",
        })
        tasks.append(task)
    payload = {
        "schema": "qingshan.episode_parallel_prompt_batch.v1",
        "episode": "E21",
        "scene_contract_ref": "configs/e21_scene_state_v1_20260718.json",
        "qa_dir": "qa/e21_v7_failed_only_r2_20260719",
        "output_dir": "working_assets/e21_v7_failed_only_r2_20260719/candidates",
        "max_retries": 1,
        "base_batch_note": "Retry only DIA-002, DIA-004 and DIA-017 together for continuous native-speed cadence; preserve 13 admitted V7 sources.",
        "tasks": tasks,
    }
    CONFIG.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "tasks": len(tasks), "config": str(CONFIG)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
