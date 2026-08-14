#!/usr/bin/env python3
"""Verify an explicit V27-bound decision without persisting it or its nonce."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from tools.e40_u18_v23_independent_authority_review import identity
from tools.e40_u18_v25_final_persistence_preaudit import CANONICAL, ROOT, WORK_QUEUE

V27_RECEIPT = (
    "qa/e40_preproduction_20260813/u18_v27_decision_packet_archive_v1/"
    "E40_U18_V27_DECISION_PACKET_ARCHIVE_TEST_RECEIPT_V1.json",
    "2ed575362f692cb59015b55c445dd12d17b44148284c5e21f77c80112b7fe016",
)
NONCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{15,127}$")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def timestamp_ok(value: object) -> bool:
    try:
        return isinstance(value, str) and datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def out(status: str, failures: list[str], proposal: dict | None) -> dict:
    return {
        "schema": "qingshan.e40.u18.v29.explicit_decision_trigger_result.v1",
        "status": status,
        "scope": "U18_ONLY",
        "blocks_other_lanes": False,
        "failures": sorted(set(failures)),
        "persistence_proposal": proposal,
        "nonce_registered": False,
        "replay_ledger_mutated": False,
        "formal_authorization_written": False,
        "formal_memory_written": False,
        "admission_permitted": False,
        "retry_permitted": False,
        "network_capability": False,
        "maximum_new_submissions": 0,
    }


def verify(archive_path: Path, decision_path: Path, replay_ledger_path: Path, project_root: Path = ROOT) -> dict:
    failures: list[str] = []
    if any(path.is_symlink() for path in (archive_path, decision_path, replay_ledger_path)):
        failures.append("SYMLINK_INPUT_REJECTED")
    try:
        archive = json.loads(archive_path.read_text(encoding="utf-8"))
    except Exception:
        archive = {}
        failures.append("V27_ARCHIVE_MISSING_OR_INVALID")
    try:
        decision = json.loads(decision_path.read_text(encoding="utf-8"))
    except Exception:
        decision = {}
        failures.append("EXPLICIT_DECISION_MISSING_OR_INVALID")
    try:
        ledger = json.loads(replay_ledger_path.read_text(encoding="utf-8"))
    except Exception:
        ledger = {}
        failures.append("REPLAY_LEDGER_MISSING_OR_INVALID")
    if archive.get("schema") != "qingshan.e40.u18.v27.immutable_no_execution_archive_manifest.v1" or archive.get("status") != "ARCHIVED_NO_EXECUTION_WAITING_EXPLICIT_DECISION":
        failures.append("V27_ARCHIVE_STATUS_INVALID")
    for label, (relative, expected_sha) in {**CANONICAL, "work_queue": WORK_QUEUE, "v27_receipt": V27_RECEIPT}.items():
        path = project_root / relative
        if not path.is_file() or sha256(path) != expected_sha:
            failures.append(f"{label.upper()}_PHYSICAL_SHA_LOCK_FAILED")
    locks = archive.get("content_locks") or {}
    if locks.get("canonical_script_sha256") != CANONICAL["script"][1] or locks.get("canonical_manifest_sha256") != CANONICAL["manifest"][1]:
        failures.append("ARCHIVE_CANONICAL_LOCKS_STALE")
    if locks.get("work_queue_sha256") != WORK_QUEUE[1]:
        failures.append("ARCHIVE_WORK_QUEUE_SHA_STALE")
    expected_type = "EXPLICIT_ROOT_DECISION" if archive.get("branch") == "ROOT_DECISION" else "EXPLICIT_MEMORY_DECISION" if archive.get("branch") == "MEMORY_DECISION" else None
    if decision.get("decision_type") != expected_type or (archive.get("wait_trigger") or {}).get("trigger_type") != expected_type:
        failures.append("WRONG_DECISION_BRANCH")
    if decision.get("archive_manifest_sha256") != archive.get("archive_manifest_sha256"):
        failures.append("ARCHIVE_MANIFEST_SHA_BINDING_MISMATCH")
    signer = decision.get("signer")
    reviewers = archive.get("reviewers") or {}
    if not isinstance(signer, str) or not signer.strip():
        failures.append("SIGNER_MISSING")
    elif identity(signer) in {identity(reviewers.get("human")), identity(reviewers.get("authority"))}:
        failures.append("SIGNER_NOT_INDEPENDENT")
    if not timestamp_ok(decision.get("signed_at")):
        failures.append("SIGNED_AT_MISSING_OR_INVALID")
    nonce = decision.get("nonce")
    if not isinstance(nonce, str) or not NONCE.fullmatch(nonce):
        failures.append("NONCE_MISSING_OR_INVALID")
    if ledger.get("schema") != "qingshan.e40.u18.v29.readonly_nonce_replay_ledger.v1" or not isinstance(ledger.get("used_nonces"), list):
        failures.append("REPLAY_LEDGER_SCHEMA_INVALID")
        used = []
    else:
        used = ledger.get("used_nonces")
    matches = sum(1 for value in used if value == nonce)
    if matches != 0 or decision.get("readonly_replay_query_matches") != 0:
        failures.append("NONCE_REPLAY_OR_NONZERO_QUERY")
    if failures:
        return out("TASK_LOCAL_REMOTE_WAIT", failures, None)

    common = {
        "signer": signer,
        "signed_at": decision.get("signed_at"),
        "nonce": nonce,
        "archive_manifest_path": str(archive_path),
        "archive_manifest_file_sha256": sha256(archive_path),
        "archive_manifest_sha256": archive.get("archive_manifest_sha256"),
        "decision_path": str(decision_path),
        "decision_sha256": sha256(decision_path),
        "replay_ledger_path": str(replay_ledger_path),
        "replay_ledger_sha256": sha256(replay_ledger_path),
        "readonly_replay_query_matches": 0,
        "nonce_registered": False,
        "persistence_performed": False,
    }
    if expected_type == "EXPLICIT_ROOT_DECISION":
        proposal = {"schema": "qingshan.e40.u18.v29.authorization_persistence_proposal.v1", "status": "AUTHORIZATION_PERSISTENCE_PROPOSAL_READY_NOT_WRITTEN", **common, "formal_authorization_written": False, "admission_permitted": False, "retry_permitted": False}
        status = "AUTHORIZATION_PERSISTENCE_PROPOSAL_READY_NOT_WRITTEN"
    else:
        proposal = {"schema": "qingshan.e40.u18.v29.formal_memory_persistence_proposal.v1", "status": "FORMAL_MEMORY_PERSISTENCE_PROPOSAL_READY_NOT_WRITTEN", **common, "formal_memory_written": False, "retry_permitted": False}
        status = "FORMAL_MEMORY_PERSISTENCE_PROPOSAL_READY_NOT_WRITTEN"
    return out(status, [], proposal)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive-manifest", required=True, type=Path)
    parser.add_argument("--explicit-decision", required=True, type=Path)
    parser.add_argument("--replay-ledger", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    value = verify(args.archive_manifest, args.explicit_decision, args.replay_ledger)
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0 if value["status"].endswith("READY_NOT_WRITTEN") else 3


if __name__ == "__main__":
    raise SystemExit(main())
