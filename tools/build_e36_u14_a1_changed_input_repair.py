#!/usr/bin/env python3
"""Build the one permitted changed-input repair for E36 U14-A1."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/recovery_10000_20260730/u14_images/E36_U14_RECOVERY_IMAGE_BATCH_V1.json"
PROMPT = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/recovery_10000_20260730/u14_images/E36-CW-U14-A1-STILL-V4-CHANGED-INPUT-REPAIR.txt"
QA = ROOT / "qa/e36_agentcut_20260730/u14_image_runtime/E36_U14_A1_RECOVERY_IMAGE_DIRECT_VISUAL_QA_V1.json"
OUT = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/recovery_10000_20260730/u14_images/E36_U14_A1_CHANGED_INPUT_REPAIR_BATCH_V1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    base = json.loads(BASE.read_text(encoding="utf-8"))
    qa = json.loads(QA.read_text(encoding="utf-8"))
    if qa.get("verdict") != "FAIL_REPAIRABLE_NOT_ADMITTED_U14_A1_V3":
        raise SystemExit("repair source QA is not the preserved U14-A1 V3 failure")
    source = next(row for row in base["tasks"] if row["task_key"] == "E36-CW-U14-A1-STILL-V3-RECOVERY-10000")
    task = copy.deepcopy(source)
    task["task_key"] = "E36-CW-U14-A1-STILL-V4-CHANGED-INPUT-REPAIR"
    task["prompt_file"] = str(PROMPT.relative_to(ROOT))
    task["prompt_sha256"] = sha256(PROMPT)
    task["prompt_contract"]["repair_of_task_id"] = qa["task_id"]
    task["prompt_contract"]["repair_of_image_sha256"] = qa["image_sha256"]
    task["prompt_contract"]["changed_input_failures"] = qa["failures"]
    task["prompt_contract"]["status"] = "PASS"
    task["status"] = "AUTHORIZED_SINGLE_CHANGED_INPUT_REPAIR_AFTER_PRECHECK"
    task["generation_authority"]["episode_credits_before_submit"] = 7350
    task["generation_authority"]["episode_credits_after_success"] = 7361
    payload = {
        "schema": "qingshan.image_batch_manifest.v2",
        "episode": "E36",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_cl2x": "CL2X-825",
        "source_mailbox_sha256": "b83bdb784856d282140c1219a03c7904d753e9bf5c2ec4606c27e1eb1692cc0e",
        "source_script_sha256": base["source_script_sha256"],
        "generation_authority": {
            "episode_credit_ceiling": 10000,
            "current_episode_credits": 7350,
            "batch_planned_credits": 11,
            "episode_credits_after_batch_success": 7361,
            "attributable_headroom_after_batch_success": 2639,
            "unchanged_paid_retry_allowed": False,
            "automatic_changed_input_repair_number": 1,
            "automatic_changed_input_repair_maximum": 1
        },
        "consumer_contract": {
            "consumer": "U14-A1 repair image QA before U14-A2 or any U14 video",
            "submission_policy": "Submit this changed-input repair exactly once; no further automatic paid U14-A1 repair."
        },
        "machine_gate_reports": base["machine_gate_reports"],
        "failure_authority": {"path": str(QA.relative_to(ROOT)), "sha256": sha256(QA)},
        "tasks": [task]
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(OUT), "sha256": sha256(OUT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
