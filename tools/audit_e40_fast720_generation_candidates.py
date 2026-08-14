#!/usr/bin/env python3
"""One-shot read-only audit for immediately legal E40 Fast720 video work."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808"
VIDEO_TX = ROOT / "workflow/tasks/giggle_video_submit_transactions/E40"
QUEUE = ROOT / "workflow/work_queue.json"
FULL25 = PRODUCTION / "full25_next_unit_audit_v1/E40_FULL25_NEXT_UNIT_AUDIT_V1.json"
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E40剧本_ClaudeWriter_v3.md"
MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E40_manifest_v3.json"
SCRIPT_SHA = "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b"
MANIFEST_SHA = "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1"


AUTHORIZATIONS = {
    "E40-U12-MOUTH-NONVISIBLE-FAST720-SILENT-VISUAL-EXACTLY-ONE-V1":
        "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_mouth_nonvisible_fast720_exactly_one_v1/E40_U12_MOUTH_NONVISIBLE_FAST720_SILENT_VISUAL_AUTHORIZED_MANIFEST_V1.json",
    "E40-U12-V4-NEW-PLATE-MOUTH-ABSENT-FAST720-SILENT-EXACTLY-ONE-V1":
        "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v4_new_plate_fast720_v1/E40_U12_V4_NEW_PLATE_MOUTH_ABSENT_FAST720_SILENT_AUTHORIZED_MANIFEST_V1.json",
    "E40-U28A-BAILI-BEGIN-TURN-V3-FAST720-EXACT-FIRST-FRAME-V1":
        "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u25_u28_u29_v3_split_implementation_v1/zero_cost_source_plate_acquisition_v1/changed_representation_audit_v1/acquisition_preflight_v1/post_helper_bound_v1/u28a_fast720_no_submit_v1/E40_U28A_ROOT_EXACTLY_ONE_VIDEO_AUTHORIZATION_V1.json",
    "E40-U29A-BAILI-JADE-RETRACT-V3-FAST720-EXACT-FIRST-FRAME-V2":
        "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/next_generatable_unit_readiness_audit_v2/E40_U29A_FAST720_ROOT_EXACTLY_ONE_EXECUTION_AUTHORIZATION_V2.json",
    "E40-U29A-BAILI-JADE-RETRACT-V3-FAST720-EXACT-FIRST-FRAME-V3-NO-SUBMIT":
        "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/next_generatable_unit_readiness_audit_v2/E40_U29A_V3_FAST720_EXACTLY_ONE_EXECUTION_AUTHORIZATION.json",
    "E40-U29B-CHENJI-ASHUAN-REACTION-V3-INDEPENDENT-FAST720-EXACT-FIRST-FRAME-EXACTLY-ONE-V1":
        "workflow/approvals/E40_U29B_INDEPENDENT_FAST720_EXACTLY_ONE_AUTHORIZATION_20260809.json",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    queue = load(QUEUE)
    full25 = load(FULL25)
    transactions = []
    by_key = {}
    for path in sorted(VIDEO_TX.glob("*.json")):
        row = load(path)
        key = row.get("task_key")
        record = {
            "task_key": key,
            "path": str(path.relative_to(ROOT)),
            "sha256": sha256(path),
            "model": row.get("model"),
            "state": row.get("state"),
            "task_id": row.get("task_id"),
            "task_id_bound": bool(row.get("task_id")),
            "maximum_new_submissions": row.get("maximum_new_submissions"),
        }
        transactions.append(record)
        by_key[key] = record

    authorization_rows = []
    for task_key, ref in AUTHORIZATIONS.items():
        tx = by_key.get(task_key)
        auth_path = ROOT / ref
        authorization_rows.append({
            "task_key": task_key,
            "authorization_ref": ref,
            "authorization_sha256": sha256(auth_path),
            "transaction_ref": tx.get("path") if tx else None,
            "provider_task_id": tx.get("task_id") if tx else None,
            "transaction_state": tx.get("state") if tx else None,
            "authorization_consumed": bool(tx and tx.get("task_id_bound")),
            "eligible_now": False,
            "reason": "EXACTLY_ONE_ALREADY_CONSUMED_TASK_ID_BOUND" if tx and tx.get("task_id_bound") else "UNRESOLVED",
        })

    fast = [row for row in transactions if row["model"] == "seedance-2.0-fast"]
    forbidden = [row for row in transactions if row["model"] != "seedance-2.0-fast"]
    credits = queue.get("e40_credits", {})
    full25_no_candidate = full25.get("candidate_decision", {}).get("independent_fast720_candidate_outside_exclusions") is None
    checks = {
        "canonical_script_exact": sha256(SCRIPT) == SCRIPT_SHA,
        "canonical_manifest_exact": sha256(MANIFEST) == MANIFEST_SHA,
        "queue_canonical_exact": queue.get("canonical", {}).get("script_sha256") == SCRIPT_SHA and queue.get("canonical", {}).get("manifest_sha256") == MANIFEST_SHA,
        "fast_transactions_all_task_id_bound": len(fast) == 12 and all(row["task_id_bound"] for row in fast),
        "all_exactly_one_authorizations_consumed": len(authorization_rows) == 6 and all(row["authorization_consumed"] for row in authorization_rows),
        "only_unbound_video_transaction_is_forbidden_standard": len(forbidden) == 1 and forbidden[0]["model"] == "seedance-2.0" and not forbidden[0]["task_id_bound"],
        "full25_has_no_outside_candidate": full25_no_candidate,
        "u12_failed_quarantined_no_retry": queue.get("latest_e40_u12_v4_new_plate_fast720_terminal_quarantine", {}).get("status") == "QUARANTINED_NO_RETRY",
        "u29c_failed_quarantined_no_retry": queue.get("latest_e40_u29c_fast720_terminal_quarantine", {}).get("status") == "FAIL_HARD_FRAME0_AUDIO_ACTION_MOUTH_QUARANTINED_NO_RETRY",
        "credits_exact": (credits.get("gross_pay"), credits.get("refund"), credits.get("net")) == (1437, 128, 1309),
        "active_remote_pay_zero": credits.get("active_remote_image_pay") == 0 and credits.get("active_remote_video_pay") == 0,
        "model_policy_fast_only": queue.get("rules", {}).get("only_video_model") == "seedance-2.0-fast",
    }
    ok = all(checks.values())
    result = {
        "schema": "qingshan.e40.fast720.immediate_candidate_audit.v1",
        "status": "PASS_NO_LEGAL_IMMEDIATE_VIDEO_CANDIDATE" if ok else "FAIL_INVENTORY_OR_LEDGER_MISMATCH",
        "checks": checks,
        "decision": {
            "immediately_legal_video_task_key": None,
            "candidate_count": 0,
            "reason": "ALL_DISCOVERED_EXACTLY_ONE_VIDEO_AUTHORIZATIONS_HAVE_BOUND_TASK_IDS; ALL_OTHER UNITS FAIL MATERIAL_DEPENDENCY_OR_AUTHORIZATION GATES",
            "next_production_unlock": "NEW_ADMITTED_CHANGED_REPRESENTATION_SOURCE_PLUS_FRESH_EXACTLY_ONE_AUTHORIZATION",
        },
        "exactly_one_authorizations": authorization_rows,
        "video_transaction_inventory": {
            "directory": str(VIDEO_TX.relative_to(ROOT)),
            "total": len(transactions),
            "states": dict(sorted(Counter(row["state"] for row in transactions).items())),
            "seedance_fast_total": len(fast),
            "seedance_fast_task_id_bound": sum(row["task_id_bound"] for row in fast),
            "forbidden_or_legacy": forbidden,
            "rows": transactions,
        },
        "credits": {k: credits.get(k) for k in ("gross_pay", "refund", "net", "remaining", "active_remote_image_pay", "active_remote_video_pay")},
        "canonical": {"script_sha256": sha256(SCRIPT), "manifest_sha256": sha256(MANIFEST)},
        "work_queue_sha256": sha256(QUEUE),
        "provider_calls": 0,
        "transactions_created": 0,
        "credits_spent": 0,
        "authorization": False,
        "maximum_new_submissions": 0,
    }
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
