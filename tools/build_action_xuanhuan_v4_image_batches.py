#!/usr/bin/env python3
"""Build six-way keyframe batches from approved action-xuanhuan manifests."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def build(episode: str) -> Path:
    manifest_path = ROOT / f"configs/{episode}_action_xuanhuan_prompt_manifest_v4_20260719.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    reference_path = ROOT / f"configs/{episode.lower()}_v3_locked_beat_reference_map_20260719.json"
    reference_map = json.loads(reference_path.read_text(encoding="utf-8"))["beats"]
    tasks = []
    for source in manifest["image_tasks"]:
        task = dict(source)
        references = reference_map[task["beat_id"]]
        if not isinstance(references, list):
            references = [references]
        task.update({
            "task_key": f"{task['task_key']}-AXV4",
            "tool_type": "image_generation",
            "model": "gpt-image-2-pro",
            "aspect_ratio": "9:16",
            "resolution": "1K",
            "reference_images": references,
            "status": "REFERENCE_BOUND_READY_FOR_REROLL",
        })
        tasks.append(task)
    lower = episode.lower()
    out = ROOT / f"configs/{episode}_action_xuanhuan_v4_six_images_20260719.json"
    payload = {
        "schema": "qingshan.episode_parallel_batch.v1",
        "episode": episode,
        "source_sheet": manifest["source_sheet"],
        "scene_contract_ref": manifest["scene_state"],
        "action_xuanhuan_gate": manifest["action_xuanhuan_gate"],
        "status": "READY_TO_SUBMIT_CONCURRENTLY",
        "parallel_submission": True,
        "concurrency": len(tasks),
        "max_retries": 0,
        "output_dir": f"working_assets/{lower}_action_xuanhuan_v4_six_images_20260719/candidates",
        "qa_dir": f"qa/{lower}_action_xuanhuan_v4_six_images_20260719",
        "base_batch_note": "Generate all six approved action-xuanhuan beat keyframes concurrently; preserve passes and retry failed beats only.",
        "tasks": tasks,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def main() -> int:
    outputs = [build("E26"), build("E27")]
    print(json.dumps({"status": "PASS", "outputs": [str(path) for path in outputs]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
