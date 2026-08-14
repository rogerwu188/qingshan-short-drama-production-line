#!/usr/bin/env python3
"""Certify that current U12 gates forbid any further authorized production action."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V77 = ROOT / "qa/e40_preproduction_20260813/u12_v77_production_state/E40_U12_V77_STATE.json"
V77_SHA = "413ac1795066d9de4dc7c296c50f910f14c4300862da55fa20c64883aa146e72"
STATE = ROOT / "workflow/production_line/E40_TASK_LANES_V1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    v77 = json.loads(V77.read_text())
    scheduler = json.loads(STATE.read_text())
    independent_active = [
        task["task_id"]
        for task in scheduler.get("tasks", [])
        if task.get("task_id") != "E40-U12-V78-AUTHORIZED-EXECUTION-BOUNDARY-CERTIFICATION-NO-SUBMIT"
        and (
            task.get("state") in {"RUNNING", "QA"}
            or (
                task.get("state") == "REMOTE_WAIT"
                and task.get("wait_scope") == "TASK_LOCAL"
            )
        )
    ]
    checks = {
        "v77_sha_exact": sha256(V77) == V77_SHA,
        "v77_status_exact": v77.get("status") == "PASS_CURRENT_STATE_EXACT_EPISODE_NONTERMINAL_FAIL_CLOSED",
        "generation_has_no_candidate": v77.get("gates", {}).get("generation") == "PASS_25_OF_25_NO_FOURTH_FAST720_CANDIDATE",
        "u12_retry_forbidden": v77.get("gates", {}).get("u12_qa") == "QUARANTINED_NO_RETRY",
        "final_chain_disabled": v77.get("gates", {}).get("assets_final_chain") == "PASS_EXACT_U29A_TO_U29B_READINESS_BINDING_FINAL_CHAIN_SLOT_DISABLED_NO_ASSEMBLY",
        "no_active_remote_pay": v77.get("credits", {}).get("active_remote_image_pay") == 0 and v77.get("credits", {}).get("active_remote_video_pay") == 0,
        "episode_nonterminal": v77.get("episode_terminal") is False,
        "independent_global_continuity_present": bool(independent_active),
    }
    ok = all(checks.values())
    result = {
        "schema": "qingshan.e40.u12.v78.execution_boundary.v1",
        "status": "PASS_U12_HARD_BOUNDARY_GLOBAL_QA_CONTINUITY_PRESENT" if ok else "FAIL",
        "checks": checks,
        "independent_active_tasks": independent_active,
        "blocked_by": ["NEW_ADMITTED_U12_SOURCE_NOT_PRESENT", "EXPLICIT_RETRY_OR_ASSEMBLY_AUTHORITY_NOT_PRESENT"],
        "authorization": False,
        "maximum_new_submissions": 0,
        "provider_calls": 0,
        "transactions": 0,
        "credits": 0,
    }
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
