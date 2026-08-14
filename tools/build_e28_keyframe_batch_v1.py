#!/usr/bin/env python3
"""Build E28's six script-locked keyframes as one concurrent image batch."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SHEET = ROOT / "configs/e28_dialogue_beat_sheet_v5_readiness_20260719.json"
SCENE_STATE = ROOT / "configs/e28_scene_state_v1_script_locked_20260719.json"
REFERENCE_MAP = ROOT / "configs/e28_v1_locked_beat_reference_map_20260719.json"
SCRIPT_GATE = ROOT / "qa/e28_preproduction_20260719/E28_SCRIPT_READINESS_GATE_V5.json"
PROMPT_DIR = ROOT / "workflow/prompts/e28_keyframes_v1_20260719"
CONFIG = ROOT / "configs/E28_keyframes_v1_six_images_20260719.json"

CAMERAS = {
    "B01": "top-down medium-wide evidence-table composition, hands and three evidence groups readable as objects but with no legible writing",
    "B02": "over-shoulder medium-wide room-defense composition, three defenders working at separate entrances while the protected clerk remains central",
    "B03": "low-angle wide action composition, rope descent, blade block and counterattack in one spatially clear instant",
    "B04": "macro side-angle evidence composition, two cut directions compared on a plain cloth target, faces held in the background",
    "B05": "dynamic lateral wide action composition, instructor revealed behind the screen as Jiaotu blocks and Yunyang closes the escape",
    "B06": "ground-level wide snowy-alley composition, Yunyang stopping at altered footprints while Chen Ji presses blank tracing paper to snow",
}


def compact(value: object) -> str:
    if isinstance(value, list):
        return "; ".join(str(item) for item in value)
    return str(value or "")


def main() -> int:
    sheet = json.loads(SHEET.read_text(encoding="utf-8"))
    scene_state = json.loads(SCENE_STATE.read_text(encoding="utf-8"))
    references = json.loads(REFERENCE_MAP.read_text(encoding="utf-8"))["beats"]
    script_gate = json.loads(SCRIPT_GATE.read_text(encoding="utf-8"))
    if script_gate.get("status") != "PASS":
        raise SystemExit("E28 script readiness gate is not PASS")

    authority_by_beat = {}
    for scene in scene_state.get("scene_state", []):
        for beat_id in scene.get("beats", []):
            authority_by_beat[beat_id] = scene

    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    tasks = []
    for beat in sheet["structure"]:
        beat_id = beat["beat_id"]
        authority = authority_by_beat[beat_id]
        refs = references[beat_id]
        for ref in refs:
            if not (ROOT / ref).is_file():
                raise SystemExit(f"Missing E28 reference: {ref}")
        location_tokens = authority.get("location_prompt_tokens") or [authority["location"]]
        prompt = (
            f"Scene authority: {location_tokens[0]}; {authority['time_of_day']}; {authority['weather']}. "
            f"Create one script-locked E28 {beat_id} photographic keyframe, vertical 9:16, realistic American prestige-drama cinematography. "
            f"Camera and composition: {CAMERAS[beat_id]}. "
            f"Show only this scripted event: {compact(beat.get('must_show'))}. "
            f"Action spine: {beat['action_spine']} Xuanhuan element: {beat['xuanhuan_element']} "
            f"Power visualization: {beat['power_visualization']} Preserve supplied character identities, wardrobe and geography. "
            "One continuous frame, one decisive moment, native anatomy, motivated practical light, no collage or storyboard layout. "
            "NEGATIVE_PROMPT: invented time, weather, location, character or event; readable writing; subtitle; caption; watermark; logo; modern object; duplicate body; extra limbs."
        )
        prompt_path = PROMPT_DIR / f"E28-{beat_id}-KEYFRAME-V1.txt"
        prompt_path.write_text(prompt + "\n", encoding="utf-8")
        tasks.append({
            "task_key": f"E28-{beat_id}-KEYFRAME-V1",
            "tool_type": "image_generation",
            "beat_id": beat_id,
            "scene_id": authority["scene_id"],
            "visual_zone": f"{beat_id}_SCRIPT_KEYFRAME",
            "prompt_file": str(prompt_path.relative_to(ROOT)),
            "reference_images": refs,
            "model": "gpt-image-2-pro",
            "aspect_ratio": "9:16",
            "resolution": "1K",
            "status": "READY_FOR_PARALLEL_SUBMIT",
        })

    payload = {
        "schema": "qingshan.episode_parallel_batch.v1",
        "episode": "E28",
        "scene_contract_ref": str(SCENE_STATE.relative_to(ROOT)),
        "script_readiness_report": str(SCRIPT_GATE.relative_to(ROOT)),
        "status": "READY_TO_SUBMIT_CONCURRENTLY",
        "parallel_submission": True,
        "concurrency": len(tasks),
        "max_retries": 0,
        "output_dir": "working_assets/e28_keyframes_v1_six_images_20260719/candidates",
        "qa_dir": "qa/e28_keyframes_v1_six_images_20260719",
        "base_batch_note": "Submit all six script-locked E28 keyframes concurrently; preserve passes and retry failed beats only.",
        "tasks": tasks,
    }
    CONFIG.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "config": str(CONFIG), "task_count": len(tasks)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
