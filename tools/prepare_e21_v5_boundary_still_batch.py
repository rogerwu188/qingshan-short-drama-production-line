#!/usr/bin/env python3
"""Prepare the concurrent E21 V5 shot-specific boundary-still batch."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "configs/e21_agentcut_project_v4_us_drama_rewrite_20260719.json"
PROMPT_DIR = ROOT / "workflow/prompts/e21_v5_boundary_stills_20260719"
CONFIG = ROOT / "workflow/tasks/E21_v5_boundary_stills_parallel_config_20260719.json"
TARGETS = [
    "DIA-002", "DIA-003", "DIA-004", "DIA-027", "DIA-028", "DIA-007", "DIA-029",
    "DIA-011", "DIA-012", "DIA-013", "DIA-014", "DIA-031", "DIA-016", "DIA-033",
    "DIA-020", "DIA-021", "DIA-036", "DIA-024", "DIA-026", "DIA-037",
]
COMPOSITIONS = {
    "DIA-002": "tight reverse close-up on Chen Ji questioning the messenger, the listener's shoulder only at frame edge",
    "DIA-003": "over-shoulder evidence two-shot, messenger answering while Chen Ji holds the foreground axis",
    "DIA-004": "low three-quarter interruption on Bai Li, one raised hand stopping the exchange",
    "DIA-027": "isolated medium close-up on the messenger claiming the manor will not pursue the matter",
    "DIA-028": "sharp profile reaction on Chen Ji challenging why they came after dark",
    "DIA-007": "macro sleeve-cuff pressure-mark insert with Chen Ji's suspicious eyes visible above it",
    "DIA-029": "macro wet-ink fingertip evidence, folded official paper back facing camera with no visible writing",
    "DIA-011": "silent pressure reaction close-up on the messenger, eyes avoiding Chen Ji",
    "DIA-012": "over-shoulder accusation from Chen Ji with the messenger cornered at the doorway",
    "DIA-013": "side two-shot as Bai Li states the manor knew before the loss",
    "DIA-014": "frontal close-up on Chen Ji landing the deduction that the result was fixed first",
    "DIA-031": "high-angle defensive answer from the messenger under the eave",
    "DIA-016": "waist-level badge insert with Bai Li indicating the false rear-house credential",
    "DIA-033": "macro missing-cloud-pattern badge edge held between Bai Li's fingers",
    "DIA-020": "dynamic knife-reveal reverse angle on Bai Li warning the others",
    "DIA-021": "lantern-side close-up on Chen Ji at the instant before he shouts, mouth ready and lamp still burning",
    "DIA-036": "low defensive action angle as Bai Li shields the red thread from the attacker",
    "DIA-024": "ground-level white-cat and red-thread insert with Bai Li crouched in shallow focus",
    "DIA-026": "rear narrow-door reveal from behind Chen Ji, impossible doorway centered beyond him",
    "DIA-037": "final close reaction on Chen Ji watching the white cat face Wuyun without fear",
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
    clips = {
        clip["metadata"]["dialogue_id"]: clip
        for track in project["timeline"]["videoTracks"]
        for clip in track.get("clips", [])
    }
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    tasks = []
    for dia_id in TARGETS:
        clip = clips[dia_id]
        meta = clip["metadata"]
        beat_id = meta["beat_id"]
        reference = REFERENCES[beat_id]
        if not reference.is_file():
            raise SystemExit(f"missing reference for {dia_id}: {reference}")
        if meta["scene_id"].endswith("ALLEY"):
            location = "medical hall front door opening into the wet narrow alley"
            weather = "wet after rain, rain-stopped, no downpour"
        elif meta["scene_id"].endswith("DOOR"):
            location = "rear-house narrow door and threshold"
            weather = "still air, wet stone, only an occasional drip"
        else:
            location = "medical hall threshold"
            weather = "rain-stopped with only eave drips"
        prompt = (
            "Create a vertical 9:16 photorealistic shot-specific locked still for E21. "
            f"Preserve the supplied character identities, costumes, props, {location}, script-locked night timing, "
            f"{weather}, cold practical lantern lighting, and established 180-degree axis. "
            f"Composition: {COMPOSITIONS[dia_id]}. Narrative payload is exactly the approved dialogue beat "
            f"{meta['exact_dialogue']} and must not introduce another event. No readable writing, pseudo-writing, "
            "document face, subtitle, caption, logo, watermark, extra character, unrelated prop, or location change.\n"
        )
        prompt_path = PROMPT_DIR / f"{dia_id}.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        tasks.append({
            "task_key": f"E21-{dia_id}-STILL-V5-BOUNDARY",
            "tool_type": "image_generation",
            "source_id": dia_id,
            "dialogue_id": dia_id,
            "dia_id": dia_id,
            "beat_id": beat_id,
            "scene_id": meta["scene_id"],
            "visual_zone": f"{beat_id}_{dia_id.replace('-', '')}_V5_SHOT_SPECIFIC",
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
        "qa_dir": "qa/e21_v5_boundary_stills_20260719",
        "output_dir": "working_assets/e21_v5_boundary_stills_20260719/candidates",
        "max_retries": 1,
        "base_batch_note": "Generate twenty shot-specific first frames concurrently for the twenty visually merged V4 boundaries; preserve the seventeen already detected boundaries.",
        "tasks": tasks,
    }
    CONFIG.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "tasks": len(tasks), "config": str(CONFIG)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
