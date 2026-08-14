#!/usr/bin/env python3
"""Compile every ready dialogue line into one parallel multimodal video batch."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from giggle_api_client import STANDARD_VIDEO_MODEL
except ModuleNotFoundError:  # Imported as tools.compile_episode_dialogue_video_batch in tests.
    from tools.giggle_api_client import STANDARD_VIDEO_MODEL


def compile_batch(script: dict, image_receipt: dict, scene_state: dict, prompt_dir: Path) -> dict:
    episode = script["episode"]
    scenes = scene_state.get("scene_state") or []
    if len(scenes) != 1:
        raise ValueError(
            "legacy dialogue compiler supports exactly one scene; "
            "use compile_episode_parallel_prompt_batch.py for multi-scene episodes"
        )
    scene = scenes[0]
    images = {}
    for task in image_receipt.get("tasks", []):
        key = task.get("task_key", "")
        if task.get("state") == "image_pass" and task.get("output_path"):
            beat = key.split("-")[1]
            images[beat] = task["output_path"]
    tasks = []
    prompt_dir.mkdir(parents=True, exist_ok=True)
    for line in script.get("dialogue_draft", []):
        beat = line["beat_id"]
        if beat not in images:
            raise ValueError(f"missing admitted beat image: {beat}")
        dia_id = line["dia_id"]
        speaker = line["speaker"]
        prompt = (
            f"Animate the supplied script-locked {episode} {beat} still for five seconds, vertical 9:16, "
            f"inside the same {scene['time_of_day']} {scene['location']} in {scene['weather']} weather. "
            f"Preserve the exact canonical faces, wardrobe, props, lighting, room geography, and current beat action. "
            f"{speaker} speaks exactly once in natural Mandarin with restrained historical-drama performance: “{line['text']}” "
            f"Only {speaker}'s mouth moves for the line; all visible listeners react subtly and causally without speaking. "
            "Use native-speed human motion, clean room tone, script-locked scene ambience and only story-motivated practical sound. "
            "Do not add music, subtitles, captions, readable ledger marks, letters, numbers, signs, logos, watermarks, extra dialogue, paraphrase, repeated gesture, cyclic motion, slow motion, or time-of-day change."
        )
        prompt_path = prompt_dir / f"{dia_id}.txt"
        prompt_path.write_text(prompt + "\n", encoding="utf-8")
        tasks.append({
            "task_key": f"{episode}-{dia_id}-VIDEO",
            "scene_id": scene["scene_id"],
            "visual_zone": f"{beat}_{dia_id}_DIALOGUE",
            "tool_type": "video_generation",
            "prompt_file": str(prompt_path),
            "reference_images": [images[beat]],
            "model": STANDARD_VIDEO_MODEL,
            "duration": 5,
            "aspect_ratio": "9:16",
            "resolution": "720p",
            "metadata": {"beat_id": beat, "dia_id": dia_id, "speaker": speaker, "exact_dialogue": line["text"]},
        })
    return {
        "episode": episode,
        "scene_contract_ref": scene_state.get("_source_path"),
        "output_dir": f"working_assets/{episode.lower()}_v2_full_dialogue_video_wave_parallel_20260718/candidates",
        "qa_dir": f"qa/{episode.lower()}_v2_full_dialogue_video_wave_parallel_20260718",
        "max_retries": 1,
        "base_batch_note": "Submit every ready dialogue video in one fan-out. Preserve passes and retry only failed dialogue items.",
        "tasks": tasks,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--script", required=True, type=Path)
    parser.add_argument("--images", required=True, type=Path)
    parser.add_argument("--scene-state", required=True, type=Path)
    parser.add_argument("--prompt-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    script = json.loads(args.script.read_text(encoding="utf-8"))
    images = json.loads(args.images.read_text(encoding="utf-8"))
    scene_state = json.loads(args.scene_state.read_text(encoding="utf-8"))
    scene_state["_source_path"] = str(args.scene_state)
    batch = compile_batch(script, images, scene_state, args.prompt_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(batch, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "out": str(args.out), "task_count": len(batch["tasks"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
