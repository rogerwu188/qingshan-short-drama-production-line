#!/usr/bin/env python3
"""Build the concurrent E22 V11 dialogue-audibility repair batch."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/tasks/E22_v10_repeat_cluster_videos_config_20260719.json"
PROMPT_DIR = ROOT / "workflow/prompts/e22_v11_failed_dialogue_repairs_20260719"
CONFIG = ROOT / "workflow/tasks/E22_v11_failed_dialogue_repairs_config_20260719.json"
TARGETS = {"DIA-026", "DIA-034"}


def main() -> int:
    base = json.loads(BASE.read_text(encoding="utf-8"))
    source_tasks = {task["dialogue_id"]: task for task in base["tasks"]}
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    tasks = []
    for dialogue_id in sorted(TARGETS):
        task = dict(source_tasks[dialogue_id])
        dialogue = task["exact_dialogue"]
        duration = int(task["duration_seconds"])
        prompt = (
            "Animate the supplied locked first frame in the exact clear-afternoon Buddhist hall. Preserve identities, costumes, "
            "props, evidence layout, cats, daylight continuity, composition and 180-degree axis. Chen Ji must begin speaking "
            f"within the first 0.35 seconds and say exactly once, clearly and audibly in natural Mandarin: \"{dialogue}\" "
            f"Complete the full line by 2.8 seconds inside this {duration}-second native-speed shot. Keep his mouth visibly synchronized "
            "and the dialogue at normal conversational level above the room ambience. After the line, continue the existing restrained "
            "hand/eye-line performance without a frozen pose or repeated cadence. No external BGM, silent performance, whispered or "
            "inaudible line, paraphrase, extra dialogue, readable text, subtitle, logo, new event, prop, character, weather or location."
        )
        prompt_path = PROMPT_DIR / f"{dialogue_id}.txt"
        prompt_path.write_text(prompt + "\n", encoding="utf-8")
        task.update({
            "task_key": f"E22-{dialogue_id}-VIDEO-V11-AUDIBLE-DIALOGUE",
            "prompt_file": str(prompt_path.relative_to(ROOT)),
            "status": "READY_FOR_PARALLEL_SUBMIT",
            "repair_reason": "V10 final-window ASR empty and RMS below dialogue audibility",
        })
        tasks.append(task)
    payload = {
        "schema": "qingshan.episode_parallel_prompt_batch.v1",
        "episode": "E22",
        "scene_contract_ref": "configs/e22_scene_state_v1_20260718.json",
        "qa_dir": "qa/e22_v11_failed_dialogue_repairs_20260719",
        "output_dir": "working_assets/e22_v11_failed_dialogue_repairs_20260719/candidates",
        "max_retries": 1,
        "base_batch_note": "Regenerate only DIA-026 and DIA-034 together for immediate audible dialogue; preserve all other V10 sources.",
        "tasks": tasks,
    }
    CONFIG.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "tasks": len(tasks), "config": str(CONFIG)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
