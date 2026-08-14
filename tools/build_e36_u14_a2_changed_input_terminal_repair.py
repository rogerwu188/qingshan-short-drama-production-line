#!/usr/bin/env python3
"""Build the sole changed-input terminal-state repair for E36 U14-A2."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/recovery_10000_20260730/u14_images/E36_U14_A2_AFTER_A1_ACCEPTANCE_BATCH_V1.json"
FAIL_QA = ROOT / "qa/e36_agentcut_20260730/u14_image_runtime/E36_U14_A2_FIRST_ATTEMPT_DIRECT_VISUAL_QA_V1.json"
PROMPT = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/recovery_10000_20260730/u14_images/E36-CW-U14-A2-STILL-V4-CHANGED-INPUT-TERMINAL-REPAIR.txt"
OUT = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/recovery_10000_20260730/u14_images/E36_U14_A2_CHANGED_INPUT_TERMINAL_REPAIR_BATCH_V1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    base = json.loads(BASE.read_text(encoding="utf-8"))
    fail_qa = json.loads(FAIL_QA.read_text(encoding="utf-8"))
    if fail_qa.get("verdict") != "FAIL_REPAIRABLE_NOT_ADMITTED_U14_A2_V3":
        raise SystemExit("U14-A2 preserved failure authority is missing")

    task = copy.deepcopy(base["tasks"][0])
    task["task_key"] = "E36-CW-U14-A2-STILL-V4-CHANGED-INPUT-TERMINAL-REPAIR"
    task["prompt_file"] = str(PROMPT.relative_to(ROOT))
    task["prompt_sha256"] = sha256(PROMPT)
    task["prompt_contract"]["repair_of_task_id"] = fail_qa["task_id"]
    task["prompt_contract"]["repair_of_image_sha256"] = fail_qa["image_sha256"]
    task["prompt_contract"]["changed_input_failures"] = fail_qa["failures"]
    task["prompt_contract"]["recovery_state"] = "terminal_state_changed_input_repair"
    task["prompt_contract"]["recovery_target_state"] = "陈迹完全站直，以分开的食指和中指分别压住相隔一掌的两道不同方向空白折痕；皎兔正面确认两层信息"
    task["prompt_contract"]["status"] = "PASS"
    task["status"] = "AUTHORIZED_SINGLE_CHANGED_INPUT_REPAIR_AFTER_PRECHECK"
    task["generation_authority"]["episode_credits_before_submit"] = 7372
    task["generation_authority"]["episode_credits_after_success"] = 7383

    payload = {
        "schema": "qingshan.image_batch_manifest.v2",
        "episode": "E36",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_cl2x": "CL2X-826",
        "source_mailbox_sha256": "67c6be5a4ecb408c42a70a8cc8d3a615d93fa827875356fdff35f71d07c263ec",
        "source_script_sha256": base["source_script_sha256"],
        "generation_authority": {
            "episode_credit_ceiling": 10000,
            "current_episode_credits": 7372,
            "batch_planned_credits": 11,
            "episode_credits_after_batch_success": 7383,
            "attributable_headroom_after_batch_success": 2617,
            "unchanged_paid_retry_allowed": False,
            "automatic_changed_input_repair_number_for_u14_a2": 1,
            "automatic_changed_input_repair_maximum_for_u14_a2": 1
        },
        "consumer_contract": {
            "consumer": "U14-A2 repair QA, then immediate natural-unit U14 video prompt assembly",
            "submission_policy": "Submit this changed-input repair exactly once; no further automatic paid U14-A2 repair."
        },
        "machine_gate_reports": base["machine_gate_reports"],
        "preceding_state_authority": base["preceding_state_authority"],
        "failure_authority": {"path": str(FAIL_QA.relative_to(ROOT)), "sha256": sha256(FAIL_QA)},
        "tasks": [task]
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(OUT), "sha256": sha256(OUT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
