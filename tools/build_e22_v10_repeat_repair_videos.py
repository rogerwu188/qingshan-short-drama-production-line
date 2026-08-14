#!/usr/bin/env python3
"""Build the E22 V10 repeat-cluster video fan-out from admitted stills."""

from __future__ import annotations

import json
from pathlib import Path

from build_e22_v10_repeat_repair_stills import ROOT, SCRIPT, SHOT_INTENTS
from shot_duration_policy import plan_dialogue_duration


STILL_RECEIPT = ROOT / "workflow/tasks/E22_v10_repeat_cluster_stills_receipt_20260719.json"
PROMPT_DIR = ROOT / "workflow/prompts/e22_v10_repeat_cluster_videos_20260719"
CONFIG = ROOT / "workflow/tasks/E22_v10_repeat_cluster_videos_config_20260719.json"


def main() -> int:
    script = json.loads(SCRIPT.read_text(encoding="utf-8"))
    rows = {row["dia_id"]: row for row in script["dialogue_draft"]}
    receipt = json.loads(STILL_RECEIPT.read_text(encoding="utf-8"))
    admitted = {
        task["dia_id"]: Path(task["output_path"])
        for task in receipt.get("tasks", [])
        if task.get("state") == "image_pass" and task.get("output_path")
    }
    missing = sorted(set(SHOT_INTENTS) - set(admitted))
    if receipt.get("status") != "BATCH_COMPLETE" or missing:
        raise SystemExit(f"V10 still batch is not fully admitted; missing={','.join(missing)}")

    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    tasks = []
    for dia_id, shot_intent in SHOT_INTENTS.items():
        row = rows[dia_id]
        reference = admitted[dia_id]
        if not reference.is_file():
            raise SystemExit(f"missing admitted V10 still: {reference}")
        duration_plan = plan_dialogue_duration(
            row["text"],
            str(row.get("pace") or "medium"),
            str(row.get("function") or row.get("payload") or "dialogue"),
            performance_context=shot_intent,
        )
        duration = int(duration_plan["duration_seconds"])
        prompt = (
            "Animate the supplied script-locked first frame as one continuous cinematic vertical 9:16 shot. "
            "Keep the established Yunfei small Buddhist hall, clear afternoon, warm window light, incense haze, "
            "locked identities, costumes, evidence props, cats, screen direction and 180-degree axis unchanged. "
            f"Shot-specific action and composition: {shot_intent} "
            f"{row['speaker']} speaks exactly once in natural Mandarin: '{row['text']}' "
            "Only the named speaker talks; listeners may react causally without dialogue. "
            f"Complete the physical action and exact line naturally within {duration} seconds, then hold only a brief motivated reaction. "
            "Use native-speed human and animal motion, synchronized dialogue, practical sound effects and room ambience. "
            "Do not add external music, a new event, character, prop, location, time or weather state. "
            "No paraphrase, extra dialogue, cyclic gesture, slow motion, readable paper face, pseudo-writing, subtitle, caption, logo or watermark."
        )
        prompt_path = PROMPT_DIR / f"{dia_id}.txt"
        prompt_path.write_text(prompt + "\n", encoding="utf-8")
        tasks.append({
            "task_key": f"E22-{dia_id}-VIDEO-V10-REPEAT-REPAIR",
            "tool_type": "video_generation",
            "source_id": dia_id,
            "dialogue_id": dia_id,
            "dia_id": dia_id,
            "beat_id": row["beat_id"],
            "scene_id": "E22-S01-YUNFEI-BUDDHIST-HALL",
            "visual_zone": f"{row['beat_id']}_{dia_id}_V10_REPEAT_CLUSTER_REPAIR",
            "speaker": row["speaker"],
            "exact_dialogue": row["text"],
            "payload": row.get("payload") or row.get("function"),
            "payload_source": "payload" if row.get("payload") else "function",
            "duration_seconds": duration,
            "duration": duration,
            "duration_plan": duration_plan,
            "model": "seedance-2.0-pro",
            "aspect_ratio": "9:16",
            "resolution": "720p",
            "prompt_file": str(prompt_path.relative_to(ROOT)),
            "reference_images": [str(reference)],
            "status": "READY_FOR_PARALLEL_SUBMIT",
        })

    payload = {
        "schema": "qingshan.episode_parallel_prompt_batch.v1",
        "episode": "E22",
        "scene_contract_ref": "configs/e22_scene_state_v1_20260718.json",
        "qa_dir": "qa/e22_v10_repeat_cluster_videos_20260719",
        "output_dir": "working_assets/e22_v10_repeat_cluster_videos_20260719/candidates",
        "max_retries": 1,
        "base_batch_note": "Nine repeat-cluster source replacements generated concurrently from admitted script-locked V10 stills; keep passes and retry failed items only.",
        "tasks": tasks,
    }
    CONFIG.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "config": str(CONFIG), "tasks": len(tasks), "durations": {task["dia_id"]: task["duration"] for task in tasks}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
