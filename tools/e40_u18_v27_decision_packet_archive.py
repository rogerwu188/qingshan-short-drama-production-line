#!/usr/bin/env python3
"""Validate and describe an immutable no-execution V25 decision-packet archive."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from tools.e40_u18_v23_independent_authority_review import EXPECTED, identity
from tools.e40_u18_v25_final_persistence_preaudit import CANONICAL, ROOT, WORK_QUEUE, safe_locked_json

V25_RECEIPT = (
    "qa/e40_preproduction_20260813/u18_v25_final_persistence_preaudit_v1/"
    "E40_U18_V25_FINAL_PERSISTENCE_PREAUDIT_TEST_RECEIPT_V1.json",
    "94f93efdc8ea69a0db778ad718dca86542a57044cf96f0e7ad40bc8adc4ecfef",
)
V25_AUDITOR = (
    "tools/e40_u18_v25_final_persistence_preaudit.py",
    "2f3bf17f02565eee39603d15be561cae444bfaf45ae09678c9b0fc24d25e9acf",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fail(failures: list[str]) -> dict:
    return {
        "schema": "qingshan.e40.u18.v27.decision_packet_archive_result.v1",
        "status": "TASK_LOCAL_REMOTE_WAIT",
        "scope": "U18_ONLY",
        "blocks_other_lanes": False,
        "failures": sorted(set(failures)),
        "archive_manifest": None,
        "formal_authorization_created": False,
        "formal_memory_written": False,
        "admission_permitted": False,
        "retry_permitted": False,
        "network_capability": False,
        "maximum_new_submissions": 0,
    }


def archive(packet_path: Path, project_root: Path = ROOT) -> dict:
    failures: list[str] = []
    if packet_path.is_symlink():
        return fail(["SYMLINK_PACKET_REJECTED"])
    try:
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
    except Exception:
        return fail(["DECISION_PACKET_MISSING_OR_INVALID"])
    packet_sha = sha256(packet_path)
    for label, (relative, expected_sha) in {
        **CANONICAL, "work_queue": WORK_QUEUE, "v25_receipt": V25_RECEIPT,
        "v25_auditor": V25_AUDITOR,
    }.items():
        path = project_root / relative
        if not path.is_file() or sha256(path) != expected_sha:
            failures.append(f"{label.upper()}_PHYSICAL_SHA_LOCK_FAILED")
    if packet.get("canonical_locks") != {key: expected for key, (_, expected) in CANONICAL.items()}:
        failures.append("PACKET_CANONICAL_LOCKS_STALE")
    if packet.get("work_queue_sha256") != WORK_QUEUE[1]:
        failures.append("PACKET_WORK_QUEUE_SHA_STALE")
    if packet.get("v23_receipt_sha256") != "508c9e65ed919f0e31eeddd06ac1aedadfbaf6282667e8cd953a9c1342f09c45":
        failures.append("PACKET_V23_RECEIPT_SHA_STALE")
    if identity(packet.get("authority_reviewer")) == identity(packet.get("human_reviewer")):
        failures.append("PACKET_REVIEWER_INDEPENDENCE_FAILED")

    schema = packet.get("schema")
    if schema == "qingshan.e40.u18.v25.root_decision_packet.v1":
        if packet.get("status") != "ROOT_DECISION_PACKET_READY_NOT_EXECUTED" or packet.get("root_decision_required") is not True:
            failures.append("ROOT_PACKET_STATUS_OR_TRIGGER_INVALID")
        if any(packet.get(key) is not False for key in ("formal_authorization_created", "admission_permitted", "retry_permitted")):
            failures.append("ROOT_PACKET_PERMISSION_FLAG_NOT_FALSE")
        subject = safe_locked_json(packet.get("subject_path"), packet.get("subject_sha256"), project_root, "V23_AUTH_REQUEST", failures)
        if subject.get("schema") != "qingshan.e40.u18.v23.authorization_request.v1":
            failures.append("V23_AUTH_REQUEST_SCHEMA_MISMATCH")
        if subject.get("binding_locks") != packet.get("binding_locks"):
            failures.append("ROOT_PACKET_BINDING_LOCKS_TAMPERED")
        packet_assets = {row.get("exact_task_id"): row for row in packet.get("assets") or []}
        subject_assets = {row.get("exact_task_id"): row for row in subject.get("assets") or []}
        for task_id, fingerprint in EXPECTED.items():
            archived = packet_assets.get(task_id) or {}
            source = subject_assets.get(task_id) or {}
            if archived != source or archived.get("transaction_fingerprint") != fingerprint or not archived.get("output_sha256"):
                failures.append(f"ROOT_PACKET_TASK_FINGERPRINT_OUTPUT_TAMPERED:{task_id}")
        if set(packet_assets) != set(EXPECTED) or set(subject_assets) != set(EXPECTED):
            failures.append("ROOT_PACKET_EXACT_TWO_ASSET_SET_MISMATCH")
        wait_trigger = {
            "trigger_type": "EXPLICIT_ROOT_DECISION",
            "required_binding": "archive_manifest_sha256",
            "automatic_authorization": False,
            "automatic_admission": False,
            "automatic_retry": False,
        }
        branch = "ROOT_DECISION"
    elif schema == "qingshan.e40.u18.v25.memory_decision_packet.v1":
        if packet.get("status") != "MEMORY_DECISION_PACKET_READY_NOT_WRITTEN" or packet.get("root_decision_required") is not True:
            failures.append("MEMORY_PACKET_STATUS_OR_TRIGGER_INVALID")
        if packet.get("formal_memory_written") is not False or packet.get("retry_permitted") is not False:
            failures.append("MEMORY_PACKET_PERMISSION_FLAG_NOT_FALSE")
        subject = safe_locked_json(packet.get("subject_path"), packet.get("subject_sha256"), project_root, "V23_MEMORY_PROPOSAL", failures)
        if subject.get("schema") != "qingshan.e40.u18.v23.formal_memory_update_proposal.v1":
            failures.append("V23_MEMORY_PROPOSAL_SCHEMA_MISMATCH")
        if packet.get("failures") != subject.get("failures") or packet.get("original_fingerprint_quarantine") != subject.get("original_fingerprint_quarantine") or packet.get("materially_changed_next_attempt_requirements") != subject.get("materially_changed_next_attempt_requirements"):
            failures.append("MEMORY_PACKET_FAILURE_OR_QUARANTINE_TAMPERED")
        wait_trigger = {
            "trigger_type": "EXPLICIT_MEMORY_DECISION",
            "required_binding": "archive_manifest_sha256",
            "automatic_formal_memory_write": False,
            "automatic_retry": False,
        }
        branch = "MEMORY_DECISION"
    else:
        failures.append("DECISION_PACKET_SCHEMA_NOT_ACCEPTED")
        wait_trigger = {}
        branch = None
    if failures:
        return fail(failures)

    content_locks = {
        "decision_packet_path": str(packet_path),
        "decision_packet_sha256": packet_sha,
        "v25_receipt_path": V25_RECEIPT[0],
        "v25_receipt_sha256": V25_RECEIPT[1],
        "v25_auditor_path": V25_AUDITOR[0],
        "v25_auditor_sha256": V25_AUDITOR[1],
        "canonical_script_sha256": CANONICAL["script"][1],
        "canonical_manifest_sha256": CANONICAL["manifest"][1],
        "work_queue_sha256": WORK_QUEUE[1],
    }
    immutable_identity = hashlib.sha256(json.dumps({"branch": branch, "content_locks": content_locks, "wait_trigger": wait_trigger}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    manifest = {
        "schema": "qingshan.e40.u18.v27.immutable_no_execution_archive_manifest.v1",
        "status": "ARCHIVED_NO_EXECUTION_WAITING_EXPLICIT_DECISION",
        "branch": branch,
        "archive_manifest_sha256": immutable_identity,
        "content_locks": content_locks,
        "binding_locks": packet.get("binding_locks"),
        "reviewers": {"human": packet.get("human_reviewer"), "authority": packet.get("authority_reviewer")},
        "wait_trigger": wait_trigger,
        "formal_authorization_created": False,
        "formal_memory_written": False,
        "admission_permitted": False,
        "retry_permitted": False,
        "provider_calls": 0,
        "transactions": 0,
        "credits": 0,
        "maximum_new_submissions": 0,
    }
    return {
        "schema": "qingshan.e40.u18.v27.decision_packet_archive_result.v1",
        "status": "IMMUTABLE_NO_EXECUTION_ARCHIVE_MANIFEST_READY",
        "scope": "U18_ONLY",
        "blocks_other_lanes": False,
        "failures": [],
        "archive_manifest": manifest,
        "formal_authorization_created": False,
        "formal_memory_written": False,
        "admission_permitted": False,
        "retry_permitted": False,
        "network_capability": False,
        "maximum_new_submissions": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--decision-packet", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    value = archive(args.decision_packet)
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0 if value["status"] == "IMMUTABLE_NO_EXECUTION_ARCHIVE_MANIFEST_READY" else 3


if __name__ == "__main__":
    raise SystemExit(main())
