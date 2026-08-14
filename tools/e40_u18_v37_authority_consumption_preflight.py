#!/usr/bin/env python3
"""Read-only V37 preflight. It never consumes authority or writes nonce/target."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from tools.e40_u18_v23_independent_authority_review import identity
from tools.e40_u18_v31_atomic_persistence_bundle import FORMAL_MEMORY, ROOT
from tools.e40_u18_v35_authority_document_verifier import PINS, verify as verify_v35

WITNESS_FIELDS = {
    "schema", "scope", "witness", "witnessed_at", "authority_document_sha256",
    "v31_bundle_file_sha256", "v31_bundle_sha256", "v29_proposal_sha256",
    "explicit_decision_sha256", "nonce_ledger_sha256", "target_path", "nonce",
    "canonical_script_sha256", "canonical_manifest_sha256", "work_queue_sha256",
    "formal_memory_sha256", "nonce_zero_matches", "target_absent",
    "authority_consumed", "nonce_registered", "target_written",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def result(failures: list[str], locks: dict | None = None) -> dict:
    return {
        "schema": "qingshan.e40.u18.v37.authority_consumption_preflight_result.v1",
        "status": "AUTHORITY_CONSUMPTION_PREFLIGHT_READY_NOT_EXECUTED" if not failures else "TASK_LOCAL_REMOTE_WAIT",
        "scope": "U18_ONLY",
        "blocks_other_lanes": False,
        "failures": sorted(set(failures)),
        "revalidated_locks": locks if not failures else None,
        "authority_consumed": False,
        "execution_authorized": False,
        "nonce_registered": False,
        "nonce_ledger_mutated": False,
        "target_written": False,
        "formal_authorization_written": False,
        "formal_memory_written": False,
        "provider_calls": 0,
        "transactions": 0,
        "credits": 0,
        "maximum_new_submissions": 0,
    }


def load(path: Path, label: str, failures: list[str]) -> dict:
    if path.is_symlink():
        failures.append(f"{label}_SYMLINK_REJECTED")
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        failures.append(f"{label}_MISSING_OR_INVALID")
        return {}


def under_root(path_value: object, project_root: Path, label: str, failures: list[str], *, must_exist: bool = True) -> Path | None:
    if not isinstance(path_value, str) or not path_value:
        failures.append(f"{label}_PATH_MISSING")
        return None
    path = Path(path_value)
    if not path.is_absolute():
        path = project_root / path
    try:
        root_resolved = project_root.resolve(strict=True)
        resolved = path.resolve(strict=must_exist)
        resolved.relative_to(root_resolved)
    except Exception:
        failures.append(f"{label}_OUTSIDE_ROOT_OR_MISSING")
        return None
    if path.is_symlink():
        failures.append(f"{label}_SYMLINK_REJECTED")
        return None
    return resolved


def timestamp_ok(value: object) -> bool:
    try:
        return isinstance(value, str) and datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def verify(
    authority_path: Path,
    bundle_path: Path,
    witness_path: Path,
    project_root: Path = ROOT,
    now: datetime | None = None,
) -> dict:
    failures: list[str] = []
    now = now or datetime.now(timezone.utc)
    authority = load(authority_path, "AUTHORITY_DOCUMENT", failures)
    bundle = load(bundle_path, "V31_BUNDLE", failures)
    witness = load(witness_path, "LOCAL_WITNESS", failures)
    locks = bundle.get("locks") or {}
    ledger_path = under_root(locks.get("nonce_ledger_path"), project_root, "NONCE_LEDGER", failures)
    proposal_path = under_root(locks.get("v29_proposal_path"), project_root, "V29_PROPOSAL", failures)
    decision_path = under_root(locks.get("explicit_decision_path"), project_root, "EXPLICIT_DECISION", failures)
    target_path = under_root(locks.get("target_path"), project_root, "TARGET", failures, must_exist=False)

    if ledger_path is None:
        v35 = {"status": "INVALID_AUTHORITY_DOCUMENT", "failures": ["LEDGER_UNAVAILABLE"]}
    else:
        v35 = verify_v35(authority_path, bundle_path, ledger_path, now, project_root)
    if v35.get("status") != "VALID_AUTHORITY_DOCUMENT_NOT_EXECUTED":
        failures.append("V35_VALID_AUTHORITY_DOCUMENT_NOT_EXECUTED_REQUIRED")
        failures.extend(f"V35:{item}" for item in v35.get("failures", []))

    if bundle.get("schema") != "qingshan.e40.u18.v31.atomic_persistence_bundle.v1" or bundle.get("status") != "ATOMIC_PERSISTENCE_BUNDLE_READY_DRY_RUN_ONLY":
        failures.append("V31_BUNDLE_STATUS_INVALID")
    if any(bundle.get(key) is not False for key in ("nonce_registered", "target_written", "formal_authorization_written", "formal_memory_written")):
        failures.append("V31_BUNDLE_NO_WRITE_BOUNDARY_INVALID")
    expected_bundle_id = hashlib.sha256(json.dumps({
        "branch": bundle.get("branch"), "locks": locks, "nonce": bundle.get("nonce"),
        "cas_order": ["REGISTER_NONCE_FIRST", "WRITE_BRANCH_TARGET_SECOND"],
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if bundle.get("bundle_sha256") != expected_bundle_id:
        failures.append("V31_BUNDLE_ID_STALE_OR_TAMPERED")

    proposal = load(proposal_path, "V29_PROPOSAL", failures) if proposal_path else {}
    decision = load(decision_path, "EXPLICIT_DECISION", failures) if decision_path else {}
    ledger = load(ledger_path, "NONCE_LEDGER", failures) if ledger_path else {}
    proposal_sha = sha256(proposal_path) if proposal_path and proposal_path.is_file() else None
    decision_sha = sha256(decision_path) if decision_path and decision_path.is_file() else None
    ledger_sha = sha256(ledger_path) if ledger_path and ledger_path.is_file() else None
    if proposal_sha != locks.get("v29_proposal_sha256") or proposal_sha != authority.get("v29_proposal_sha256"):
        failures.append("V29_PROPOSAL_SHA_LOCK_STALE")
    if decision_sha != locks.get("explicit_decision_sha256") or decision_sha != authority.get("explicit_decision_sha256") or proposal.get("decision_sha256") != decision_sha:
        failures.append("EXPLICIT_DECISION_SHA_LOCK_STALE")
    if ledger_sha != locks.get("nonce_ledger_sha256") or ledger_sha != authority.get("nonce_ledger_sha256") or proposal.get("replay_ledger_sha256") != ledger_sha:
        failures.append("NONCE_LEDGER_SHA_LOCK_STALE")
    nonce = authority.get("nonce")
    used_nonces = ledger.get("used_nonces") if isinstance(ledger.get("used_nonces"), list) else []
    nonce_matches = sum(1 for value in used_nonces if value == nonce)
    if nonce_matches != 0 or locks.get("nonce_zero_matches") != 0 or proposal.get("readonly_replay_query_matches") != 0:
        failures.append("NONCE_RACE_DETECTED")
    if target_path is None or target_path.exists() or target_path.is_symlink() or locks.get("target_absent") is not True:
        failures.append("TARGET_RACE_DETECTED")

    if bundle.get("branch") == "AUTHORIZATION":
        expected_proposal_schema = "qingshan.e40.u18.v29.authorization_persistence_proposal.v1"
        expected_proposal_status = "AUTHORIZATION_PERSISTENCE_PROPOSAL_READY_NOT_WRITTEN"
        expected_decision_type = "EXPLICIT_ROOT_DECISION"
        if proposal.get("formal_authorization_written") is not False:
            failures.append("V29_PROPOSAL_ALREADY_WRITTEN_OR_INVALID")
    elif bundle.get("branch") == "FORMAL_MEMORY_UPDATE_EVENT":
        expected_proposal_schema = "qingshan.e40.u18.v29.formal_memory_persistence_proposal.v1"
        expected_proposal_status = "FORMAL_MEMORY_PERSISTENCE_PROPOSAL_READY_NOT_WRITTEN"
        expected_decision_type = "EXPLICIT_MEMORY_DECISION"
        if proposal.get("formal_memory_written") is not False:
            failures.append("V29_PROPOSAL_ALREADY_WRITTEN_OR_INVALID")
    else:
        expected_proposal_schema = expected_proposal_status = expected_decision_type = None
        failures.append("V31_BRANCH_INVALID")
    if proposal.get("schema") != expected_proposal_schema or proposal.get("status") != expected_proposal_status:
        failures.append("V29_PROPOSAL_STATUS_OR_BRANCH_INVALID")
    if proposal.get("nonce") != nonce or decision.get("nonce") != nonce:
        failures.append("PROPOSAL_DECISION_NONCE_BINDING_MISMATCH")
    if decision.get("decision_type") != expected_decision_type or decision.get("readonly_replay_query_matches") != 0:
        failures.append("EXPLICIT_DECISION_BRANCH_OR_REPLAY_STATE_INVALID")

    for label, relative, expected in (
        ("CANONICAL_SCRIPT", "workflow/claude_writer_agent/scripts/E40剧本_ClaudeWriter_v3.md", PINS["canonical_script_sha256"]),
        ("CANONICAL_MANIFEST", "workflow/claude_writer_agent/scripts/E40_manifest_v3.json", PINS["canonical_manifest_sha256"]),
        ("WORK_QUEUE", "workflow/work_queue.json", PINS["work_queue_sha256"]),
        ("FORMAL_MEMORY", FORMAL_MEMORY[0], PINS["formal_memory_sha256"]),
    ):
        physical = project_root / relative
        if not physical.is_file() or physical.is_symlink() or sha256(physical) != expected:
            failures.append(f"{label}_PHYSICAL_SHA_LOCK_STALE")
    declared_pins = {
        "canonical_script_sha256": locks.get("canonical_script_sha256"),
        "canonical_manifest_sha256": locks.get("canonical_manifest_sha256"),
        "work_queue_sha256": locks.get("work_queue_sha256"),
        "formal_memory_sha256": locks.get("current_formal_memory_sha256"),
    }
    if declared_pins != PINS or any(authority.get(key) != value for key, value in PINS.items()):
        failures.append("CANONICAL_QUEUE_MEMORY_DECLARED_LOCK_STALE")

    archive_path = under_root(proposal.get("archive_manifest_path"), project_root, "V27_ARCHIVE", failures)
    archive = load(archive_path, "V27_ARCHIVE", failures) if archive_path else {}
    if archive.get("schema") != "qingshan.e40.u18.v27.immutable_no_execution_archive_manifest.v1" or archive.get("status") != "ARCHIVED_NO_EXECUTION_WAITING_EXPLICIT_DECISION":
        failures.append("V27_ARCHIVE_STATUS_INVALID")
    if decision.get("archive_manifest_sha256") != archive.get("archive_manifest_sha256") or proposal.get("archive_manifest_sha256") != archive.get("archive_manifest_sha256"):
        failures.append("ARCHIVE_PROPOSAL_DECISION_BINDING_MISMATCH")
    reviewers = archive.get("reviewers") or {}
    authority_signer = (authority.get("signer") or {}).get("identity")
    root_signer = decision.get("signer")
    human_reviewer = reviewers.get("human")
    authority_reviewer = reviewers.get("authority")
    witness_identity = witness.get("witness")
    identities = [authority_signer, root_signer, human_reviewer, authority_reviewer]
    if not isinstance(witness_identity, str) or not witness_identity.strip():
        failures.append("LOCAL_WITNESS_IDENTITY_MISSING")
    elif identity(witness_identity) in {identity(value) for value in identities if isinstance(value, str)}:
        failures.append("LOCAL_WITNESS_SIGNER_COLLISION")
    if len({identity(value) for value in [root_signer, human_reviewer, authority_reviewer] if isinstance(value, str)}) != 3:
        failures.append("UPSTREAM_SIGNER_REVIEWER_COLLISION")

    expected_witness = {
        "schema": "qingshan.e40.u18.v37.local_preflight_witness.v1",
        "scope": "AUTHORITY_CONSUMPTION_PREFLIGHT_ONLY",
        "authority_document_sha256": sha256(authority_path) if authority_path.is_file() else None,
        "v31_bundle_file_sha256": sha256(bundle_path) if bundle_path.is_file() else None,
        "v31_bundle_sha256": bundle.get("bundle_sha256"),
        "v29_proposal_sha256": proposal_sha,
        "explicit_decision_sha256": decision_sha,
        "nonce_ledger_sha256": ledger_sha,
        "target_path": locks.get("target_path"),
        "nonce": nonce,
        **PINS,
        "nonce_zero_matches": 0,
        "target_absent": True,
        "authority_consumed": False,
        "nonce_registered": False,
        "target_written": False,
    }
    if set(witness) != WITNESS_FIELDS:
        failures.append("WITNESS_EXACT_FIELD_SET_REQUIRED")
    for key, value in expected_witness.items():
        if witness.get(key) != value:
            failures.append(f"WITNESS_{key.upper()}_LOCK_MISMATCH")
    if not timestamp_ok(witness.get("witnessed_at")):
        failures.append("WITNESS_TIME_MISSING_OR_INVALID")

    revalidated = {
        "authority_document_sha256": expected_witness["authority_document_sha256"],
        "v31_bundle_file_sha256": expected_witness["v31_bundle_file_sha256"],
        "v31_bundle_sha256": bundle.get("bundle_sha256"),
        "v29_proposal_sha256": proposal_sha,
        "explicit_decision_sha256": decision_sha,
        "nonce_ledger_sha256": ledger_sha,
        "nonce_zero_matches": nonce_matches,
        "target_path": locks.get("target_path"),
        "target_absent": target_path is not None and not target_path.exists(),
        **PINS,
        "witness": witness_identity,
        "witness_scope": witness.get("scope"),
        "root_signer": root_signer,
        "human_reviewer": human_reviewer,
        "authority_reviewer": authority_reviewer,
    }
    return result(failures, revalidated)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--authority-document", required=True, type=Path)
    parser.add_argument("--v31-bundle", required=True, type=Path)
    parser.add_argument("--local-witness", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    value = verify(args.authority_document, args.v31_bundle, args.local_witness)
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0 if value["status"] == "AUTHORITY_CONSUMPTION_PREFLIGHT_READY_NOT_EXECUTED" else 3


if __name__ == "__main__":
    raise SystemExit(main())
