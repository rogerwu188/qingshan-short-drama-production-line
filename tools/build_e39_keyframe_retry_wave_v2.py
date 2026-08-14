#!/usr/bin/env python3
"""Build E39's failed-only R2 plus ungenerated-first-attempt keyframe wave."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e39_claude_writer_v3_2726b69b_20260805/E39_INITIAL_KEYFRAME_WAVE_V1.json"
OUT = ROOT / "workflow/claude_writer_agent/production/e39_claude_writer_v3_2726b69b_20260805/E39_KEYFRAME_FAILED_ONLY_R2_AND_UNGENERATED_V2.json"
PREFLIGHT = "qa/e39_preproduction_20260805/E39_FAILED_KEYFRAME_R2_PROMPT_PREFLIGHT_V1.json"
MEMORY_SHA = "34cca0c01bda93ff59bddaae7d7e45bf9409b3b0a9918e1970161cc25949216e"
RETRY_UNITS = {"U01", "U02", "U05", "U10", "U11", "U12", "U13", "U14", "U15"}
FIRST_ATTEMPT_UNITS = {"U03", "U04", "U06"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    source = json.loads(BASE.read_text(encoding="utf-8"))
    tasks = []
    for original in source["tasks"]:
        unit = original["video_unit_id"].split("-")[-1]
        if unit not in RETRY_UNITS | FIRST_ATTEMPT_UNITS:
            continue
        task = copy.deepcopy(original)
        if unit in RETRY_UNITS:
            task["task_key"] = f"E39-{unit}-A1-STILL-R2"
            task["prompt_file"] = (
                "workflow/claude_writer_agent/production/"
                "e39_claude_writer_v3_2726b69b_20260805/keyframes_v2/"
                f"E39-{unit}-A1-R2.txt"
            )
            prompt_path = ROOT / task["prompt_file"]
            task["prompt_sha256"] = sha256(prompt_path)
            task["retry_policy"] = "FAILED_ONLY_MATERIAL_PROMPT_REWRITE"
            task["prompt_memory_sha256"] = MEMORY_SHA
            task["prompt_memory_sample_count"] = 27
        else:
            task["retry_policy"] = "FIRST_ATTEMPT_PREVIOUS_CLIENT_TIMEOUT_ZERO_CHARGE"
        tasks.append(task)

    output = copy.deepcopy(source)
    output["schema"] = "qingshan.episode_parallel_batch.v2"
    output["batch_id"] = "E39_KEYFRAME_FAILED_ONLY_R2_AND_UNGENERATED_V2"
    output["machine_gate_reports"] = [*source["machine_gate_reports"], PREFLIGHT]
    output["consumer_contract"] = {
        "purpose": "E39_FAILED_ONLY_R2_AND_UNGENERATED_FIRST_ATTEMPTS",
        "video_unit_count": 12,
        "planned_anchor_count": 12,
        "new_image_submit_count": 12,
        "dependent_anchor_count": 0,
        "all_required_anchors_planned_before_submit": True,
    }
    output["tasks"] = tasks
    output["accounting_contract"] = {
        "prior_pay": 330,
        "prior_refund": 0,
        "prior_net": 330,
        "maximum_new_pay_if_all_accepted": 132,
        "episode_net_cap": 10000,
        "duplicate_prior_task_ids_prohibited": True,
        "prior_duplicate_units": ["U11", "U12", "U14"],
    }
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"path": str(OUT), "sha256": sha256(OUT), "tasks": len(tasks)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
