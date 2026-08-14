#!/usr/bin/env python3
"""Build U04 R4 from the admitted R3 contract with a material species rewrite."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e39_claude_writer_v3_2726b69b_20260805"
SOURCE = BASE / "E39_U04_R3_INTERIOR_OVERRIDE_KEYFRAME_MANIFEST_V1.json"
OUT = BASE / "E39_U04_R4_INTERIOR_FOUR_SILHOUETTES_KEYFRAME_MANIFEST_V1.json"
PROMPT = BASE / "keyframes_v5/E39-U04-A1-R4-INTERIOR-FOUR-SILHOUETTES.txt"


def main() -> None:
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    task = data["tasks"][0]
    task["task_key"] = "E39-U04-A1-STILL-R4-INTERIOR-FOUR-SILHOUETTES"
    task["prompt_file"] = str(PROMPT.relative_to(ROOT))
    task["prompt_sha256"] = hashlib.sha256(PROMPT.read_bytes()).hexdigest()
    task["status"] = "AUTHORIZED_MATERIAL_REWRITE_READY"
    task["retry_policy"] = "SPECIES_SCALE_ROLE_COUNT_AND_PROP_OWNERSHIP_MATERIAL_REWRITE"
    task["prompt_memory_sha256"] = hashlib.sha256((ROOT / "workflow/local_lora/seedance2_prompt_failure_training.jsonl").read_bytes()).hexdigest()
    task["prompt_memory_sample_count"] = 43
    task["prompt_contract"]["source_action"] = "四个独立轮廓：陈迹霜指查账，云羊俯身准备拾还，官差双手失册，正常家猫大小的乌云完整四足身体擦过官差小腿，卷册独立下落。"
    task["prompt_contract"]["source_action_sha256"] = hashlib.sha256(task["prompt_contract"]["source_action"].encode("utf-8")).hexdigest()
    task["prompt_contract"]["species_scale_contract"] = {
        "wuyun": "COMPLETE_NORMAL_SIZE_FOUR_LEGGED_BLACK_HOUSE_CAT",
        "forbidden": ["GIANT_FURRY_HUMAN_LIMB", "HUMAN_ANIMAL_FUSION", "PARTIAL_CAT_SUBSTITUTE"],
        "role_count": 4,
        "independent_silhouettes_required": True
    }
    data["status"] = "AUTHORIZED_MATERIAL_REWRITE_READY_FOR_PREFLIGHT"
    data["output_dir"] = "working_assets/e39_keyframes_v5/u04_interior_override_r4_candidates"
    data["retry_policy"] = "SPECIES_SCALE_ROLE_COUNT_AND_PROP_OWNERSHIP_MATERIAL_REWRITE"
    data["paid_submit_gate"] = {
        "status": "AUTHORIZED",
        "authorization": "workflow/approvals/ROGER_E39_REPAIR_CREDIT_BATCH_6000_20260806.json",
        "effective_cap": 16000,
        "current_net_before_submit": 13719
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"path": str(OUT.relative_to(ROOT)), "sha256": hashlib.sha256(OUT.read_bytes()).hexdigest()}))


if __name__ == "__main__":
    main()
