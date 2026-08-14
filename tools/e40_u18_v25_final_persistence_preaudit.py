#!/usr/bin/env python3
"""Final local pre-persistence audit; emits non-executable decision packets only."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from tools.e40_u18_v23_independent_authority_review import EXPECTED, identity, json_sha, safe_locked_json

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = {
    "script": (
        "workflow/claude_writer_agent/scripts/E40剧本_ClaudeWriter_v3.md",
        "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b",
    ),
    "manifest": (
        "workflow/claude_writer_agent/scripts/E40_manifest_v3.json",
        "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1",
    ),
}
WORK_QUEUE = ("workflow/work_queue.json", "ddeb34ddb5a5b8ff80ac7cf68a5b21557f6d524006f5496e79fb08cca3977b43")
V23_RECEIPT = (
    "qa/e40_preproduction_20260813/u18_v23_independent_authority_review_v1/"
    "E40_U18_V23_INDEPENDENT_AUTHORITY_REVIEW_TEST_RECEIPT_V1.json",
    "508c9e65ed919f0e31eeddd06ac1aedadfbaf6282667e8cd953a9c1342f09c45",
)
ZERO_KEYS = {
    "provider_calls", "provider_queries", "downloads", "polls", "submissions",
    "transactions", "credits", "generation", "composite", "assembly",
    "formal_authorization_writes", "formal_memory_writes", "admissions", "retries",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def result(status: str, failures: list[str], packet: dict | None) -> dict:
    return {
        "schema": "qingshan.e40.u18.v25.final_persistence_preaudit_result.v1",
        "status": status,
        "scope": "U18_ONLY",
        "blocks_other_lanes": False,
        "failures": sorted(set(failures)),
        "decision_packet": packet,
        "formal_authorization_created": False,
        "formal_memory_written": False,
        "admission_permitted": False,
        "retry_permitted": False,
        "provider_post_allowed": False,
        "maximum_new_submissions": 0,
        "network_capability": False,
    }


def audit(subject_path: Path, envelope_path: Path, project_root: Path = ROOT) -> dict:
    failures: list[str] = []
    if subject_path.is_symlink() or envelope_path.is_symlink():
        failures.append("SYMLINK_INPUT_REJECTED")
    try:
        subject = json.loads(subject_path.read_text(encoding="utf-8"))
    except Exception:
        subject = {}
        failures.append("V23_SUBJECT_MISSING_OR_INVALID")
    try:
        envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
    except Exception:
        envelope = {}
        failures.append("PREAUDIT_ENVELOPE_MISSING_OR_INVALID")
    subject_sha = sha256(subject_path) if subject_path.is_file() else None
    if envelope.get("v23_subject_sha256") != subject_sha:
        failures.append("V23_SUBJECT_SHA_STALE_OR_MISSING")

    for label, (relative, expected_sha) in {**CANONICAL, "work_queue": WORK_QUEUE, "v23_receipt": V23_RECEIPT}.items():
        path = project_root / relative
        if not path.is_file() or sha256(path) != expected_sha:
            failures.append(f"{label.upper()}_PHYSICAL_SHA_LOCK_FAILED")
        declared = (envelope.get("physical_locks") or {}).get(label + "_sha256")
        if declared != expected_sha:
            failures.append(f"{label.upper()}_DECLARED_SHA_LOCK_FAILED")
    try:
        queue = json.loads((project_root / WORK_QUEUE[0]).read_text(encoding="utf-8"))
    except Exception:
        queue = {}
    canonical = queue.get("canonical") or {}
    if canonical.get("script_sha256") != CANONICAL["script"][1] or canonical.get("manifest_sha256") != CANONICAL["manifest"][1]:
        failures.append("WORK_QUEUE_CANONICAL_PINS_MISMATCH")

    side_effects = envelope.get("side_effects")
    if not isinstance(side_effects, dict) or set(side_effects) != ZERO_KEYS or any(side_effects.get(key) != 0 for key in ZERO_KEYS):
        failures.append("NO_SIDE_EFFECTS_EXACT_ZERO_PROOF_REQUIRED")

    schema = subject.get("schema")
    if schema == "qingshan.e40.u18.v23.authorization_request.v1":
        if subject.get("status") != "AUTHORIZATION_REQUEST_READY_NOT_AUTHORIZED" or subject.get("authorization_granted") is not False:
            failures.append("V23_AUTHORIZATION_REQUEST_BOUNDARY_INVALID")
        if any(subject.get(key) is not False for key in ("direct_admission_permitted", "composite_permitted", "video_authorization_permitted")):
            failures.append("V23_REQUEST_PERMISSION_FLAG_NOT_FALSE")
        v21 = safe_locked_json(envelope.get("v21_subject_path"), subject.get("subject_sha256"), project_root, "V21_PASS_PROPOSAL", failures)
        if v21.get("schema") != "qingshan.e40.u18.v21.asset_admission_proposal.v1":
            failures.append("V21_PASS_PROPOSAL_SCHEMA_MISMATCH")
        if identity(v21.get("reviewer")) == identity(subject.get("authority_reviewer")):
            failures.append("FORGED_OR_NONINDEPENDENT_REVIEWER")
        locks = v21.get("source_locks") or {}
        human = safe_locked_json(locks.get("human_qa_manifest_path"), locks.get("human_qa_manifest_sha256"), project_root, "V19_HUMAN_MANIFEST", failures)
        input_locks = human.get("input_locks") or {}
        promotion = safe_locked_json(input_locks.get("v17_promotion_path"), input_locks.get("v17_promotion_sha256"), project_root, "V17_PROMOTION", failures)
        credit = promotion.get("credit_classification") or {}
        credit_snapshot_sha = ((promotion.get("source_snapshot_locks") or {}).get("authoritative_credit") or {}).get("sha256")
        expected_binding_locks = {
            "v19_human_manifest_sha256": locks.get("human_qa_manifest_sha256"),
            "v17_promotion_sha256": input_locks.get("v17_promotion_sha256"),
            "credit_classification_sha256": json_sha(credit),
            "authoritative_credit_snapshot_sha256": credit_snapshot_sha,
        }
        if subject.get("binding_locks") != expected_binding_locks:
            failures.append("CREDIT_OR_UPSTREAM_BINDING_LOCKS_MISMATCH")
        if any(credit.get(key) is None for key in ("pay", "refund", "net", "status")) or credit.get("net") != credit.get("pay") - credit.get("refund") or not isinstance(credit_snapshot_sha, str):
            failures.append("CREDIT_CLASSIFICATION_LOCK_INVALID")
        request_assets = {row.get("exact_task_id"): row for row in subject.get("assets") or []}
        human_assets = {row.get("exact_task_id"): row for row in human.get("assets") or []}
        for task_id, fingerprint in EXPECTED.items():
            request_asset = request_assets.get(task_id) or {}
            human_asset = human_assets.get(task_id) or {}
            if request_asset.get("transaction_fingerprint") != fingerprint or human_asset.get("transaction_fingerprint") != fingerprint:
                failures.append(f"TASK_OR_FINGERPRINT_LOCK_MISMATCH:{task_id}")
            if request_asset.get("output_sha256") != human_asset.get("output_sha256") or not human_asset.get("output_sha256"):
                failures.append(f"OUTPUT_SHA_LOCK_MISMATCH:{task_id}")
            if not str(human_asset.get("provenance") or "").strip() or not str(human_asset.get("license_or_local_authorship") or "").strip():
                failures.append(f"PROVENANCE_OR_RIGHTS_LOCK_MISSING:{task_id}")
        if set(request_assets) != set(EXPECTED) or set(human_assets) != set(EXPECTED):
            failures.append("EXACT_TWO_ASSET_SET_MISMATCH")
        if failures:
            return result("TASK_LOCAL_REMOTE_WAIT", failures, None)
        packet = {
            "schema": "qingshan.e40.u18.v25.root_decision_packet.v1",
            "status": "ROOT_DECISION_PACKET_READY_NOT_EXECUTED",
            "subject_path": str(subject_path),
            "subject_sha256": subject_sha,
            "canonical_locks": {key: sha for key, (_, sha) in CANONICAL.items()},
            "work_queue_sha256": WORK_QUEUE[1],
            "v23_receipt_sha256": V23_RECEIPT[1],
            "authority_reviewer": subject.get("authority_reviewer"),
            "human_reviewer": v21.get("reviewer"),
            "binding_locks": expected_binding_locks,
            "assets": sorted(subject.get("assets"), key=lambda row: row["exact_task_id"]),
            "formal_authorization_created": False,
            "admission_permitted": False,
            "retry_permitted": False,
            "root_decision_required": True,
        }
        return result("ROOT_DECISION_PACKET_READY_NOT_EXECUTED", [], packet)

    if schema == "qingshan.e40.u18.v23.formal_memory_update_proposal.v1":
        if subject.get("status") != "FORMAL_MEMORY_UPDATE_PROPOSAL_ONLY_NOT_WRITTEN" or subject.get("formal_memory_write_permitted") is not False or subject.get("retry_authorized") is not False:
            failures.append("V23_MEMORY_PROPOSAL_BOUNDARY_INVALID")
        v21 = safe_locked_json(envelope.get("v21_subject_path"), subject.get("subject_sha256"), project_root, "V21_FAILURE_DRAFT", failures)
        if v21.get("schema") != "qingshan.e40.u18.v21.failure_memory_draft.v1":
            failures.append("V21_FAILURE_DRAFT_SCHEMA_MISMATCH")
        if identity(v21.get("reviewer")) == identity(subject.get("authority_reviewer")):
            failures.append("FORGED_OR_NONINDEPENDENT_REVIEWER")
        if subject.get("failures") != v21.get("failures") or not subject.get("failures"):
            failures.append("FAILURE_SET_STALE_OR_EMPTY")
        if set(subject.get("original_fingerprint_quarantine") or []) != set(EXPECTED.values()):
            failures.append("ORIGINAL_FINGERPRINT_QUARANTINE_MISMATCH")
        requirements = subject.get("materially_changed_next_attempt_requirements") or {}
        if not requirements or any(value is not True for value in requirements.values()):
            failures.append("MATERIAL_CHANGE_REQUIREMENTS_INCOMPLETE")
        if failures:
            return result("TASK_LOCAL_REMOTE_WAIT", failures, None)
        packet = {
            "schema": "qingshan.e40.u18.v25.memory_decision_packet.v1",
            "status": "MEMORY_DECISION_PACKET_READY_NOT_WRITTEN",
            "subject_path": str(subject_path),
            "subject_sha256": subject_sha,
            "canonical_locks": {key: sha for key, (_, sha) in CANONICAL.items()},
            "work_queue_sha256": WORK_QUEUE[1],
            "v23_receipt_sha256": V23_RECEIPT[1],
            "authority_reviewer": subject.get("authority_reviewer"),
            "human_reviewer": v21.get("reviewer"),
            "failures": subject.get("failures"),
            "original_fingerprint_quarantine": subject.get("original_fingerprint_quarantine"),
            "materially_changed_next_attempt_requirements": requirements,
            "formal_memory_written": False,
            "retry_permitted": False,
            "root_decision_required": True,
        }
        return result("MEMORY_DECISION_PACKET_READY_NOT_WRITTEN", [], packet)

    failures.append("V23_SUBJECT_SCHEMA_NOT_ACCEPTED")
    return result("TASK_LOCAL_REMOTE_WAIT", failures, None)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v23-subject", required=True, type=Path)
    parser.add_argument("--preaudit-envelope", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    value = audit(args.v23_subject, args.preaudit_envelope)
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0 if value["status"] in {"ROOT_DECISION_PACKET_READY_NOT_EXECUTED", "MEMORY_DECISION_PACKET_READY_NOT_WRITTEN"} else 3


if __name__ == "__main__":
    raise SystemExit(main())
