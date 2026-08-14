#!/usr/bin/env python3
"""Build one AI-review request for every passed Writer Agent still candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build(receipt_path: Path, compiled_path: Path, scene_state_path: Path, out_dir: Path) -> dict:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    compiled = json.loads(compiled_path.read_text(encoding="utf-8"))
    scene_state = json.loads(scene_state_path.read_text(encoding="utf-8"))
    batch_config = json.loads(Path(receipt["config"]).read_text(encoding="utf-8"))
    source_script_sha256 = batch_config["writer_agent_provenance"]["generated_script_sha256"]
    if receipt.get("status") != "BATCH_COMPLETE":
        raise ValueError("image batch is not complete")
    shot_by_id = {row["shot_id"]: row for row in compiled["shot_contracts"]}
    scene_by_id = {row["scene_id"]: row for row in scene_state["scene_state"]}
    items = []
    for task in receipt["tasks"]:
        if task.get("state") != "image_pass":
            raise ValueError(f"image task is not a pass: {task.get('task_key')}")
        shot_id = task["shot_id"]
        shot = shot_by_id[shot_id]
        scene = scene_by_id[shot["scene_id"]]
        image_path = Path(task["output_path"])
        digest = sha256(image_path)
        if digest != task["sha256"]:
            raise ValueError(f"candidate SHA mismatch: {shot_id}")
        items.append({
            "path": str(image_path),
            "scope": "shot",
            "kind": "image",
            "importance": "critical",
            "pass_score": 4.5,
            "clip_id": shot_id,
            "metadata": {
                "episode": receipt["episode"],
                "scene_id": shot["scene_id"],
                "candidate_sha256": digest,
                "source_script_sha256": source_script_sha256,
                "review_focus": [
                    f"location must read as {scene['location']}",
                    f"time of day must read as {scene['time_of_day']}",
                    f"weather/environment must read as {scene['weather']}",
                    f"story action must clearly depict: {shot['action']}",
                    f"single decisive moment must read as: {shot['visual']}",
                    "canonical character identity, age, gender, costume and spirit-form continuity",
                    "Jiaotu spirit form must remain female with the rabbit-ear silhouette motif whenever present",
                    "Wuyun must remain an injured black cat whenever present",
                    "single continuous frame, not collage, contact sheet, split screen or storyboard grid",
                    "no readable or pseudo-readable text, watermark, logo, duplicated identity, fused limbs or extra people",
                    "grand cinematic quality must come from locked geography, depth, motivated light, material detail and action causality",
                ],
            },
            "required_capabilities": ["image_analysis", "ocr"],
            "run_regression_ci": True,
            "use_existing_tools": True,
        })
    episode = str(receipt["episode"]).upper()
    request = out_dir / f"{episode}_WRITER_AGENT_{len(items)}_STILL_AI_REVIEW_REQUEST.json"
    write_json(request, {"items": items, "workers": 4})
    return {"status": "PASS", "item_count": len(items), "request": str(request)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--compiled", required=True, type=Path)
    parser.add_argument("--scene-state", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()
    result = build(
        (ROOT / args.receipt).resolve(),
        (ROOT / args.compiled).resolve(),
        (ROOT / args.scene_state).resolve(),
        (ROOT / args.out_dir).resolve(),
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
