#!/usr/bin/env python3
"""Build one concurrent still batch for E21 V6's missing visual boundaries."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "configs/e21_agentcut_project_v6_tail_trim_20260719.json"
RECONCILIATION = ROOT / "qa/e21_agentcut_v6_tail_trim_20260719/E21_V6_VISUAL_BOUNDARY_RECONCILIATION.json"
PROMPT_DIR = ROOT / "workflow/prompts/e21_v7_missing_boundary_stills_20260719"
CONFIG = ROOT / "workflow/tasks/E21_v7_missing_boundary_stills_config_20260719.json"

COMPOSITIONS = {
    "DIA-002": "extreme 85mm frontal close-up on Chen Ji, only his face and one questioning eye-line; no messenger body in center frame",
    "DIA-003": "hard 90-degree profile close-up on the messenger answering toward screen left, Chen Ji reduced to a dark shoulder edge",
    "DIA-004": "low-angle three-quarter medium close-up on Bai Li stepping into the exchange with one raised stopping hand",
    "DIA-007": "true macro insert of the compressed sleeve-cuff ring, Chen Ji's two suspicious eyes sharply visible in a thin upper strip",
    "DIA-008": "high-angle defensive close-up on the messenger pulling the marked cuff against his chest, gaze dropped away from camera",
    "DIA-011": "locked dead-frontal silent reaction close-up on the messenger, face centered and isolated against the doorway",
    "DIA-012": "aggressive 28mm over-shoulder from behind the messenger toward Chen Ji leaning into the accusation",
    "DIA-013": "clean side two-shot led by Bai Li in profile, messenger small and trapped against the opposite frame edge",
    "DIA-032": "low 35mm push-in composition on Chen Ji pointing offscreen for the absent servant, clear empty space in his indicated direction",
    "DIA-016": "waist-level macro badge insert in Bai Li's fingers, badge back and damaged edge only, no readable face or writing",
    "DIA-017": "canted tight close-up on the messenger after the threat, jaw set and shoulders turning toward escape",
    "DIA-020": "ground-low reverse action angle on Bai Li seeing the knife enter foreground silhouette, Bai Li sharply warning across frame",
    "DIA-021": "lantern-side extreme close-up on Chen Ji shouting toward the burning practical lamp, open mouth and urgent pointing hand both visible",
    "DIA-024": "ground-level macro on the white cat gripping the red thread, Chen Ji crouched as a soft-focus reaction behind it",
    "DIA-026": "deep-focus rear reveal from behind Chen Ji, the impossible narrow door centered and fully legible as the new spatial fact",
    "DIA-037": "final eye-line match close-up on Chen Ji watching the white cat face Wuyun, cat silhouettes occupying opposite lower corners",
}

REFERENCES = {
    "B01": ROOT / "working_assets/e21_full_dialogue_parallel_20260719/reference_stills/B01.png",
    "B02": ROOT / "working_assets/e21_full_dialogue_parallel_20260719/reference_stills/B02.png",
    "B03": ROOT / "working_assets/e21_full_ready_wave_r1_parallel_20260718/candidates/E21_E21-B03-TIME-MISMATCH-IMAGE_a8c95b48-4de7-4bd4-828a-54343b10272d.png",
    "B04": ROOT / "working_assets/e21_full_dialogue_parallel_20260719/reference_stills/B04.png",
    "B05": ROOT / "working_assets/e21_failed_only_r2_plus_video_wave_parallel_20260718/candidates/E21_E21-B05-R2-THREEQUARTER_5a7556d5-2a24-4c03-af7e-386185107e96.png",
    "B06": ROOT / "working_assets/e21_failed_only_r2_plus_video_wave_parallel_20260718/candidates/E21_E21-B06-R2-PROFILE_e680f938-d04a-43f9-a14c-ea871621a189.png",
}


def main() -> int:
    project = json.loads(PROJECT.read_text(encoding="utf-8"))
    reconciliation = json.loads(RECONCILIATION.read_text(encoding="utf-8"))
    targets = reconciliation["missing_dialogue_ids"]
    if set(targets) != set(COMPOSITIONS):
        raise SystemExit("composition map does not exactly match reconciled missing boundaries")
    clips = {
        clip["metadata"]["dialogue_id"]: clip
        for track in project["timeline"]["videoTracks"]
        for clip in track.get("clips", [])
    }
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    tasks = []
    for dialogue_id in targets:
        clip = clips[dialogue_id]
        meta = clip["metadata"]
        beat_id = meta["beat_id"]
        reference = REFERENCES[beat_id]
        if not reference.is_file():
            raise SystemExit(f"missing identity reference: {reference}")
        if meta["scene_id"].endswith("THRESHOLD"):
            location_weather = "medical hall threshold at night, rain stopped with only eave drips"
        elif meta["scene_id"].endswith("ALLEY"):
            location_weather = "medical hall front door opening into the wet narrow alley at night, after rain with no downpour"
        elif meta["scene_id"].endswith("DOOR"):
            location_weather = "rear-house narrow door and threshold at night, still air with only an occasional drip"
        else:
            raise SystemExit(f"unmapped scene authority: {meta['scene_id']}")
        prompt = (
            "Create a vertical 9:16 photorealistic first frame for E21. Preserve the supplied identities, costumes, "
            f"props, exact script location ({location_weather}), practical lantern lighting, "
            "and the established 180-degree axis. This frame must be unmistakably different from the immediately "
            f"preceding dialogue shot. Composition: {COMPOSITIONS[dialogue_id]}. The only narrative payload is "
            f"{meta['exact_dialogue']} Do not add, remove, or relocate any story event, person, clue, weapon, animal, "
            "door, weather state, or light source. No readable writing, pseudo-writing, document face, subtitle, caption, "
            "logo, or watermark."
        )
        prompt_path = PROMPT_DIR / f"{dialogue_id}.txt"
        prompt_path.write_text(prompt + "\n", encoding="utf-8")
        tasks.append({
            "task_key": f"E21-{dialogue_id}-STILL-V7-MISSING-BOUNDARY",
            "tool_type": "image_generation",
            "source_id": dialogue_id,
            "dialogue_id": dialogue_id,
            "dia_id": dialogue_id,
            "beat_id": beat_id,
            "scene_id": meta["scene_id"],
            "visual_zone": f"{beat_id}_{dialogue_id.replace('-', '')}_V7_DISTINCT_BOUNDARY",
            "speaker": meta["speaker"],
            "exact_dialogue": meta["exact_dialogue"],
            "prompt_file": str(prompt_path.relative_to(ROOT)),
            "reference_images": [str(reference)],
            "model": "gpt-image-2-pro",
            "aspect_ratio": "9:16",
            "resolution": "1K",
            "status": "READY_FOR_PARALLEL_SUBMIT",
        })
    payload = {
        "schema": "qingshan.episode_parallel_prompt_batch.v1",
        "episode": "E21",
        "scene_contract_ref": "configs/e21_scene_state_v1_20260718.json",
        "qa_dir": "qa/e21_v7_missing_boundary_stills_20260719",
        "output_dir": "working_assets/e21_v7_missing_boundary_stills_20260719/candidates",
        "max_retries": 1,
        "base_batch_note": "Generate all 16 reconciled V6 missing visual boundaries concurrently; preserve the 20 detected boundaries and do not add cuts for ASL alone.",
        "reconciliation": str(RECONCILIATION.relative_to(ROOT)),
        "tasks": tasks,
    }
    CONFIG.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "tasks": len(tasks), "config": str(CONFIG)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
