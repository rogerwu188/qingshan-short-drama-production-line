#!/usr/bin/env python3
"""Build the first U14-A2 anchor attempt after U14-A1 repair acceptance."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/recovery_10000_20260730/u14_images/E36_U14_RECOVERY_IMAGE_BATCH_V1.json"
A1_QA = ROOT / "qa/e36_agentcut_20260730/u14_image_runtime/E36_U14_A1_CHANGED_INPUT_REPAIR_DIRECT_VISUAL_QA_V1.json"
A1_IMAGE = ROOT / "working_assets/e36_recovery_10000_20260730/u14_a1_repair/E36-CW-U14-A1-STILL-V4-CHANGED-INPUT-REPAIR_b9b3d8e5-7cbe-4f77-acea-18e0cee50913.png"
OUT = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/recovery_10000_20260730/u14_images/E36_U14_A2_AFTER_A1_ACCEPTANCE_BATCH_V1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    base = json.loads(BASE.read_text(encoding="utf-8"))
    a1_qa = json.loads(A1_QA.read_text(encoding="utf-8"))
    if a1_qa.get("verdict") != "PASS_ACCEPTED_U14_A1_CHANGED_INPUT_REPAIR_ONLY":
        raise SystemExit("U14-A1 accepted continuity authority is missing")
    if sha256(A1_IMAGE) != a1_qa.get("image_sha256"):
        raise SystemExit("U14-A1 accepted image SHA drift")

    source = next(row for row in base["tasks"] if row["task_key"] == "E36-CW-U14-A2-STILL-V3-RECOVERY-10000")
    task = copy.deepcopy(source)
    continuity = {
        "role": "preceding_state_continuity_authority",
        "entity_id": "E36-CW-U14-A1-ACCEPTED",
        "path": str(A1_IMAGE.relative_to(ROOT)),
        "sha256": sha256(A1_IMAGE),
        "qa_status": "PASS_ACCEPTED_U14_A1_CHANGED_INPUT_REPAIR_ONLY"
    }
    task["reference_images"].append(continuity["path"])
    task["reference_bindings"].append(continuity)
    task["prompt_contract"]["reference_bindings"].append(continuity)
    task["prompt_contract"]["preceding_state_authority"] = {
        "image": continuity["path"],
        "image_sha256": continuity["sha256"],
        "qa": str(A1_QA.relative_to(ROOT)),
        "qa_sha256": sha256(A1_QA)
    }
    task["generation_authority"]["episode_credits_before_submit"] = 7361
    task["generation_authority"]["episode_credits_after_success"] = 7372
    task["status"] = "AUTHORIZED_FIRST_ATTEMPT_AFTER_FOCUSED_PRECHECK"

    payload = {
        "schema": "qingshan.image_batch_manifest.v2",
        "episode": "E36",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_cl2x": "CL2X-826",
        "source_mailbox_sha256": "67c6be5a4ecb408c42a70a8cc8d3a615d93fa827875356fdff35f71d07c263ec",
        "source_script_sha256": base["source_script_sha256"],
        "generation_authority": {
            "episode_credit_ceiling": 10000,
            "current_episode_credits": 7361,
            "batch_planned_credits": 11,
            "episode_credits_after_batch_success": 7372,
            "attributable_headroom_after_batch_success": 2628,
            "unchanged_paid_retry_allowed": False,
            "automatic_changed_input_repair_count_for_u14_a2": 0,
            "automatic_changed_input_repair_maximum_for_u14_a2": 1
        },
        "consumer_contract": {
            "consumer": "U14-A2 image QA, then immediate natural-unit U14 video prompt assembly",
            "submission_policy": "Submit this first A2 attempt exactly once; preserve any failure and do not replay unchanged."
        },
        "machine_gate_reports": base["machine_gate_reports"],
        "preceding_state_authority": continuity,
        "tasks": [task]
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(OUT), "sha256": sha256(OUT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
