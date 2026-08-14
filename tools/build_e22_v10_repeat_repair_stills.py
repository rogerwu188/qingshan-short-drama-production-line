#!/usr/bin/env python3
"""Build the E22 V10 failed-cluster still batch from script-locked actions."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "configs/e22_dialogue_beat_sheet_v4_production_gate_open_20260719.json"
PROMPT_DIR = ROOT / "workflow/prompts/e22_v10_repeat_cluster_stills_20260719"
CONFIG = ROOT / "workflow/tasks/E22_v10_repeat_cluster_stills_config_20260719.json"

SHOT_INTENTS = {
    "DIA-007": "Extreme low floor-level composition: the white cat and black cat sniff opposite edges of the same blood-marked cloth, their noses and contradictory body tension dominate foreground; Chenji crouches behind them in a narrow upper-third strip.",
    "DIA-014": "Tight over-Chenji-shoulder reverse toward Yunfei as she extends one folded paper with its blank back facing camera; her fingers and guarded expression dominate, no paper face is visible.",
    "DIA-018": "Macro evidence composition of wet fresh-ink sheen along the folded paper edge held sideways to the warm window beam; Chenji's inspecting eye and fingertips remain soft in the background, no marks are readable.",
    "DIA-025": "Straight overhead evidence view: two physically separated medicine-dreg piles in shallow dishes, Baili's pointing hand enters from one side and the white cat's paw rests at the opposite edge.",
    "DIA-026": "Profile two-plane composition: Chenji compares the two medicine-dreg piles with both hands while the accusing attendant remains defocused behind the Buddha base; emphasize impossible timing through his physical comparison, add no new prop.",
    "DIA-030": "High diagonal table insert: blood-marked cloth is the dominant first evidence in foreground, the folded blank-backed paper and medicine dregs recede behind it, Chenji's hand identifies only the cloth.",
    "DIA-031": "Very low tabletop reverse across the folded paper's blank back toward Chenji; blood cloth and medicine dishes become blurred side shapes, making the second evidence visually distinct without readable writing.",
    "DIA-034": "Wide triangular confrontation already required by the script: Chenji stands at the evidence table and points across the three opposing household parties; Yunfei and the attendant occupy separated sides, both cats sit together in foreground.",
    "DIA-038": "High-angle Buddha-point-of-view closing composition over the full investigation group: Chenji has pushed the three evidence sets back and looks toward the unseen higher hand, Baili and both cats register the final realization below.",
}

REFERENCE = {
    "B01": ROOT / "working_assets/e22_full_dialogue_parallel_20260719/reference_stills/B01.png",
    "B03": ROOT / "working_assets/e22_failed_only_r3_plus_video_wave_parallel_20260718/candidates/E22_E22-B03-R3-FRONTAL_27ad7497-65d5-4f6b-bca1-b9b0959a70dc.png",
    "B04": ROOT / "working_assets/e22_full_dialogue_parallel_20260719/reference_stills/B04.png",
    "B05": ROOT / "working_assets/e22_full_dialogue_parallel_20260719/reference_stills/B05.png",
    "B06": ROOT / "working_assets/e22_full_dialogue_parallel_20260719/reference_stills/B06.png",
}


def main() -> int:
    script = json.loads(SCRIPT.read_text(encoding="utf-8"))
    rows = {row["dia_id"]: row for row in script["dialogue_draft"]}
    tasks = []
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    for dia_id, intent in SHOT_INTENTS.items():
        row = rows[dia_id]
        beat_id = row["beat_id"]
        reference = REFERENCE[beat_id]
        if not reference.is_file():
            raise SystemExit(f"missing locked reference: {reference}")
        prompt = (
            "Create one cinematic vertical 9:16 shot-specific first frame in the established Yunfei small Buddhist hall, "
            "clear afternoon with warm gold window light and incense haze. Preserve the locked identities, costumes, "
            "white cat, black cat, Buddha hall, evidence props, 180-degree axis and story continuity. "
            f"Script-locked shot intent: {intent} The associated exact dialogue is '{row['text']}' by {row['speaker']}; "
            "do not add or alter any event, character, location, weather or prop. No readable text, pseudo-writing, "
            "paper face, subtitle, caption, logo, watermark, collage, split screen or any alternate time or weather state."
        )
        prompt_path = PROMPT_DIR / f"{dia_id}.txt"
        prompt_path.write_text(prompt + "\n", encoding="utf-8")
        tasks.append({
            "task_key": f"E22-{dia_id}-STILL-V10-REPEAT-REPAIR",
            "tool_type": "image_generation",
            "source_id": dia_id,
            "dialogue_id": dia_id,
            "dia_id": dia_id,
            "beat_id": beat_id,
            "scene_id": "E22-S01-YUNFEI-BUDDHIST-HALL",
            "visual_zone": f"{beat_id}_{dia_id}_V10_REPEAT_CLUSTER_REPAIR",
            "speaker": row["speaker"],
            "exact_dialogue": row["text"],
            "prompt_file": str(prompt_path.relative_to(ROOT)),
            "reference_images": [str(reference)],
            "model": "gpt-image-2-pro",
            "aspect_ratio": "9:16",
            "resolution": "1K",
            "status": "READY_FOR_PARALLEL_SUBMIT",
        })
    payload = {
        "schema": "qingshan.episode_parallel_prompt_batch.v1",
        "episode": "E22",
        "scene_contract_ref": "configs/e22_scene_state_v1_20260718.json",
        "qa_dir": "qa/e22_v10_repeat_cluster_stills_20260719",
        "output_dir": "working_assets/e22_v10_repeat_cluster_stills_20260719/candidates",
        "max_retries": 1,
        "base_batch_note": "Nine frozen-regression repeat-cluster failures regenerated concurrently as script-locked, composition-distinct first frames; no story changes.",
        "tasks": tasks,
    }
    CONFIG.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "config": str(CONFIG), "tasks": len(tasks)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
