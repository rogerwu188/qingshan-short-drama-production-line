#!/usr/bin/env python3
"""Compile a no-write dry-run bundle for future atomic U18 persistence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from tools.e40_u18_v25_final_persistence_preaudit import CANONICAL, ROOT, WORK_QUEUE

FORMAL_MEMORY = (
    "workflow/claude_writer_agent/GENERATION_PROMPT_FAILURE_MEMORY.json",
    "e257682e39b941d8b994beb238591268ad9c059b2cbfc9787f9330151844a50b",
)
V29_RECEIPT = (
    "qa/e40_preproduction_20260813/u18_v29_explicit_decision_trigger_v1/"
    "E40_U18_V29_EXPLICIT_DECISION_TRIGGER_TEST_RECEIPT_V1.json",
    "a9f11ab449ed3eaecb7f9dbe146c25c46f11b4dd5a16d00623fe2e539940c541",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fail(failures: list[str], simulation: dict | None = None) -> dict:
    return {
        "schema": "qingshan.e40.u18.v31.atomic_persistence_bundle_result.v1",
        "status": "TASK_LOCAL_REMOTE_WAIT",
        "scope": "U18_ONLY",
        "blocks_other_lanes": False,
        "failures": sorted(set(failures)),
        "bundle": None,
        "simulation": simulation,
        "dry_run_only": True,
        "nonce_registered": False,
        "target_written": False,
        "formal_authorization_written": False,
        "formal_memory_written": False,
        "network_capability": False,
        "maximum_new_submissions": 0,
    }


def locked(path_value: object, expected_sha: object, root: Path, label: str, failures: list[str]) -> dict:
    if not isinstance(path_value, str) or not isinstance(expected_sha, str):
        failures.append(f"{label}_PATH_OR_SHA_MISSING")
        return {}
    path = Path(path_value)
    if not path.is_absolute():
        path = root / path
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except Exception:
        failures.append(f"{label}_OUTSIDE_ROOT_OR_MISSING")
        return {}
    if path.is_symlink() or sha256(resolved) != expected_sha:
        failures.append(f"{label}_SHA_MISMATCH")
        return {}
    try:
        return json.loads(resolved.read_text(encoding="utf-8"))
    except Exception:
        failures.append(f"{label}_INVALID_JSON")
        return {}


def simulate_atomic(nonce: str, used_nonces: list, target_exists: bool, fail_at: object = None) -> dict:
    before = {"used_nonces": list(used_nonces), "target_exists": target_exists}
    working = {"used_nonces": list(used_nonces), "target_exists": target_exists}
    steps = []
    try:
        if nonce in working["used_nonces"]:
            raise ValueError("NONCE_RACE_DETECTED_AT_COMMIT")
        working["used_nonces"].append(nonce)
        steps.append("REGISTER_NONCE_FIRST")
        if fail_at == "AFTER_NONCE_REGISTER":
            raise ValueError("SIMULATED_FAILURE_AFTER_NONCE_REGISTER")
        if working["target_exists"]:
            raise ValueError("TARGET_EXISTS_AT_COMMIT")
        working["target_exists"] = True
        steps.append("WRITE_BRANCH_TARGET_SECOND")
        if fail_at == "AFTER_TARGET_WRITE":
            raise ValueError("SIMULATED_FAILURE_AFTER_TARGET_WRITE")
    except ValueError as exc:
        working = {"used_nonces": list(before["used_nonces"]), "target_exists": before["target_exists"]}
        return {"status": "ROLLBACK_SIMULATED_NO_DISK_WRITE", "steps_attempted": steps, "failure": str(exc), "rollback_complete": working == before, "before": before, "after": working}
    return {"status": "COMMIT_SEQUENCE_VALIDATED_DRY_RUN_ONLY", "steps_attempted": steps, "failure": None, "rollback_complete": None, "before": before, "after_simulated": working, "disk_write_performed": False}


def compile_bundle(proposal_path: Path, target_path: Path, project_root: Path = ROOT, simulate_failure_at: object = None) -> dict:
    failures: list[str] = []
    if proposal_path.is_symlink() or target_path.is_symlink():
        failures.append("SYMLINK_INPUT_OR_TARGET_REJECTED")
    try:
        proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    except Exception:
        proposal = {}
        failures.append("V29_PROPOSAL_MISSING_OR_INVALID")
    proposal_sha = sha256(proposal_path) if proposal_path.is_file() else None
    for label, (relative, expected_sha) in {**CANONICAL, "work_queue": WORK_QUEUE, "formal_memory": FORMAL_MEMORY, "v29_receipt": V29_RECEIPT}.items():
        path = project_root / relative
        if not path.is_file() or sha256(path) != expected_sha:
            failures.append(f"{label.upper()}_PHYSICAL_SHA_LOCK_FAILED")

    schema = proposal.get("schema")
    if schema == "qingshan.e40.u18.v29.authorization_persistence_proposal.v1":
        if proposal.get("status") != "AUTHORIZATION_PERSISTENCE_PROPOSAL_READY_NOT_WRITTEN" or proposal.get("formal_authorization_written") is not False:
            failures.append("AUTHORIZATION_PROPOSAL_BOUNDARY_INVALID")
        branch = "AUTHORIZATION"
        expected_target_parent = project_root / "workflow/approvals"
    elif schema == "qingshan.e40.u18.v29.formal_memory_persistence_proposal.v1":
        if proposal.get("status") != "FORMAL_MEMORY_PERSISTENCE_PROPOSAL_READY_NOT_WRITTEN" or proposal.get("formal_memory_written") is not False:
            failures.append("MEMORY_PROPOSAL_BOUNDARY_INVALID")
        branch = "FORMAL_MEMORY_UPDATE_EVENT"
        expected_target_parent = project_root / "workflow/claude_writer_agent/formal_memory_updates"
    else:
        failures.append("V29_PROPOSAL_SCHEMA_NOT_ACCEPTED")
        branch = None
        expected_target_parent = project_root / "__invalid__"

    try:
        target_resolved_parent = target_path.parent.resolve(strict=False)
        expected_parent = expected_target_parent.resolve(strict=False)
        target_resolved_parent.relative_to(expected_parent)
    except Exception:
        failures.append("TARGET_PATH_OUTSIDE_BRANCH_NAMESPACE")
    if target_path.exists() or target_path.is_symlink():
        failures.append("TARGET_PATH_ALREADY_EXISTS")

    archive = locked(proposal.get("archive_manifest_path"), proposal.get("archive_manifest_file_sha256"), project_root, "V27_ARCHIVE", failures)
    decision = locked(proposal.get("decision_path"), proposal.get("decision_sha256"), project_root, "EXPLICIT_DECISION", failures)
    ledger = locked(proposal.get("replay_ledger_path"), proposal.get("replay_ledger_sha256"), project_root, "NONCE_LEDGER", failures)
    nonce = proposal.get("nonce")
    used_nonces = ledger.get("used_nonces") if isinstance(ledger.get("used_nonces"), list) else []
    matches = sum(1 for value in used_nonces if value == nonce)
    if matches != 0 or proposal.get("readonly_replay_query_matches") != 0:
        failures.append("NONCE_LEDGER_NOT_ZERO_MATCH")
    if proposal.get("archive_manifest_sha256") != archive.get("archive_manifest_sha256") or decision.get("archive_manifest_sha256") != archive.get("archive_manifest_sha256"):
        failures.append("ARCHIVE_DECISION_PROPOSAL_SHA_BINDING_MISMATCH")
    expected_decision_type = "EXPLICIT_ROOT_DECISION" if branch == "AUTHORIZATION" else "EXPLICIT_MEMORY_DECISION" if branch else None
    if decision.get("decision_type") != expected_decision_type:
        failures.append("DECISION_BRANCH_MISMATCH")

    if failures:
        return fail(failures)
    simulation = simulate_atomic(nonce, used_nonces, False, simulate_failure_at)
    if simulation["status"] != "COMMIT_SEQUENCE_VALIDATED_DRY_RUN_ONLY":
        return fail([simulation["failure"]], simulation)
    locks = {
        "v29_proposal_path": str(proposal_path), "v29_proposal_sha256": proposal_sha,
        "v27_archive_path": proposal.get("archive_manifest_path"), "v27_archive_file_sha256": proposal.get("archive_manifest_file_sha256"), "v27_archive_manifest_sha256": proposal.get("archive_manifest_sha256"),
        "explicit_decision_path": proposal.get("decision_path"), "explicit_decision_sha256": proposal.get("decision_sha256"),
        "nonce_ledger_path": proposal.get("replay_ledger_path"), "nonce_ledger_sha256": proposal.get("replay_ledger_sha256"), "nonce_zero_matches": 0,
        "target_path": str(target_path), "target_absent": True,
        "canonical_script_sha256": CANONICAL["script"][1], "canonical_manifest_sha256": CANONICAL["manifest"][1],
        "work_queue_sha256": WORK_QUEUE[1], "current_formal_memory_sha256": FORMAL_MEMORY[1], "v29_receipt_sha256": V29_RECEIPT[1],
    }
    bundle_id = hashlib.sha256(json.dumps({"branch": branch, "locks": locks, "nonce": nonce, "cas_order": ["REGISTER_NONCE_FIRST", "WRITE_BRANCH_TARGET_SECOND"]}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    bundle = {
        "schema": "qingshan.e40.u18.v31.atomic_persistence_bundle.v1",
        "status": "ATOMIC_PERSISTENCE_BUNDLE_READY_DRY_RUN_ONLY",
        "branch": branch,
        "bundle_sha256": bundle_id,
        "locks": locks,
        "nonce": nonce,
        "simulated_cas_order": ["RECHECK_ALL_LOCKS", "REGISTER_NONCE_FIRST", "WRITE_BRANCH_TARGET_SECOND", "COMMIT_BOTH_OR_ROLLBACK_BOTH"],
        "rollback_policy": "ANY_FAILURE_RESTORES_NONCE_LEDGER_AND_LEAVES_TARGET_ABSENT",
        "simulation": simulation,
        "dry_run_only": True,
        "nonce_registered": False,
        "target_written": False,
        "formal_authorization_written": False,
        "formal_memory_written": False,
    }
    return {**fail([], simulation), "status": "ATOMIC_PERSISTENCE_BUNDLE_READY_DRY_RUN_ONLY", "bundle": bundle, "failures": []}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v29-proposal", required=True, type=Path)
    parser.add_argument("--target-path", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    value = compile_bundle(args.v29_proposal, args.target_path)
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0 if value["status"] == "ATOMIC_PERSISTENCE_BUNDLE_READY_DRY_RUN_ONLY" else 3


if __name__ == "__main__":
    raise SystemExit(main())
