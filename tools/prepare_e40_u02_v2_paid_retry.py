#!/usr/bin/env python3
"""Create the one-shot paid U02 V2 execution manifest after fail-closed checks."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = Path(
    "workflow/claude_writer_agent/production/"
    "e40_claude_writer_v3_140d4b7b_20260808/"
    "u02_v2_state_isolated_exact_start_frame_remediation_v1"
)
PACKAGE = ROOT / BASE / "E40_U02_V2_STATE_ISOLATED_IMAGE_MANIFEST_V1.json"
EXECUTION = ROOT / BASE / "E40_U02_V2_STATE_ISOLATED_PAID_RETRY_MANIFEST_V1.json"
GO_GATE = ROOT / "qa/e40_preproduction_20260814/u02_v2_state_isolated_package_qa_v1/E40_U02_V2_PAID_RETRY_GO_GATE_V1.json"
STATIC_GATE = ROOT / "qa/e40_preproduction_20260814/u02_v2_state_isolated_package_qa_v1/E40_U02_V2_STATE_ISOLATED_STATIC_AND_NEGATIVE_GATE_V1.json"
INSTALLED_PRECHECK = ROOT / "qa/e40_preproduction_20260814/u02_v2_state_isolated_package_qa_v1/E40_U02_V2_INSTALLED_PRECHECK_V1.json"
OLD_HARVEST = ROOT / "workflow/tasks/E40_U02_EXACT_START_FRAME_IMAGE_HARVEST_20260809.json"
FAILURE_MEMORY = ROOT / "workflow/claude_writer_agent/GENERATION_PROMPT_FAILURE_MEMORY.json"
WORK_QUEUE = ROOT / "workflow/work_queue.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    package = load(PACKAGE)
    static = load(STATIC_GATE)
    precheck = load(INSTALLED_PRECHECK)
    old = load(OLD_HARVEST)
    memory = load(FAILURE_MEMORY)
    queue = load(WORK_QUEUE)
    task = package["tasks"][0]
    old_result = old["results"][0]
    pf21 = next((row for row in memory.get("rules", []) if row.get("id") == "PF-021"), None)

    checks = {
        "standing_episode_authorization": queue.get("authorization_ref") == "ROGER_STANDING_EPISODE_CREDIT_CAP_10000_20260730",
        "remaining_credit_positive": queue.get("e40_credits", {}).get("remaining", 0) >= 11,
        "old_task_terminal": old_result.get("remote_status") == "completed" and old.get("all_completed") is True,
        "old_credit_classified": old_result.get("credit") == 5.0 and old_result.get("credit_status") == "KNOWN_BATCH_LEDGER_EXACT_COUNT",
        "failure_memory_present": pf21 is not None,
        "prompt_materially_changed": task.get("prompt_sha256") != "0d4879ac9bff9310ab6f01dffcb45db2089581274519843d38aab802410de810",
        "failed_pixels_excluded": task.get("failed_asset_exclusions") == [{"sha256": "6d05770f9f0324e540c1eb53f109072eae0b6510d1be99c748f0c8ee8c8e9fd6"}],
        "state_isolated_reference_shas": [row.get("sha256") for row in task.get("reference_bindings", [])] == ["c5a2ff2da4239b20c3ea61fae2e8286cf334b791a036fbd3554894fd5092bf1d", "921fe9db441ac18e986cbc3015d67cb9861de2ad73528330f381230e83e530b4"],
        "static_negative_gate_pass": static.get("status") == "PASS" and static.get("negative_cases_rejected") == static.get("negative_case_count") == 6,
        "installed_precheck_pass": precheck.get("status") == "PASS" and precheck.get("precheck_pass") == 1 and precheck.get("submitted") == 0,
        "expected_cost_within_cap": task.get("expected_pay_upper", 999) <= 11,
    }
    if not all(checks.values()):
        raise SystemExit("paid retry certification failed: " + ", ".join(k for k, v in checks.items() if not v))

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    execution = copy.deepcopy(package)
    execution["schema"] = "qingshan.giggle_image_manifest.v2"
    execution["created_at"] = now
    execution["status"] = "AUTHORIZED_EXACTLY_ONE_PAID_RETRY_AFTER_TERMINAL_CREDIT_PF021_AND_MATERIAL_CHANGE"
    execution["machine_gate_reports"] = list(execution["machine_gate_reports"]) + [str(GO_GATE.relative_to(ROOT))]
    execution["tasks"][0]["task_key"] = "E40-U02-EXACT-START-FRAME-V2-STATE-ISOLATED-RETRY1"
    execution["tasks"][0]["status"] = "PAID_GO_EXACTLY_ONE"
    execution["tasks"][0]["paid_submission_allowed"] = True
    execution["submission_policy"] = {
        "root_only": True,
        "authorized": True,
        "provider_post_allowed": True,
        "transaction_creation_required_before_post": True,
        "bind_task_id_immediately_after_response": True,
        "maximum_new_submissions": 1,
        "expected_pay_upper": 11,
        "unchanged_retry_forbidden": True,
        "do_not_retry_on_script_error": True,
    }

    gate = {
        "schema": "qingshan.e40.u02.v2.paid_retry_go_gate.v1",
        "recorded_at": now,
        "status": "PASS",
        "authorization_ref": queue["authorization_ref"],
        "checks": checks,
        "old_provider_task_id": old_result["task_id"],
        "old_terminal_asset_sha256": old_result["sha256"],
        "old_credit": {"pay": 5, "refund": 0, "net": 5},
        "failure_memory": "PF-021",
        "new_prompt_sha256": task["prompt_sha256"],
        "new_reference_sha256": [row["sha256"] for row in task["reference_bindings"]],
        "maximum_new_submissions": 1,
        "transaction_required_before_post": True,
        "provider_calls": 0,
        "transactions": 0,
        "credits": 0,
    }
    write(GO_GATE, gate)
    write(EXECUTION, execution)
    print(json.dumps({"status": "PASS", "execution_manifest": str(EXECUTION.relative_to(ROOT)), "execution_manifest_sha256": sha(EXECUTION), "go_gate_sha256": sha(GO_GATE)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
