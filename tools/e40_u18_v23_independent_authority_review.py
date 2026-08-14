#!/usr/bin/env python3
"""Independent local review of a V21 proposal or failure-memory draft."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

from tools.e40_u18_v21_human_qa_decision_intake import HARD_GATES

ROOT = Path(__file__).resolve().parents[1]
V21_RECEIPT = (
    "qa/e40_preproduction_20260813/u18_v21_human_qa_decision_intake_v1/"
    "E40_U18_V21_HUMAN_QA_DECISION_INTAKE_TEST_RECEIPT_V1.json",
    "46e1720843edcbd623f41d153f2ab2dad2e91a46ce3b7ce4c49f610978fb66c4",
)
EXPECTED = {
    "17939df6-4f2c-4148-91c3-38f26870b6dc": "9c30d6f2df49d060c554e84220ca2a7b3917086eaf0ac177e83a8cf0bf8f3dea",
    "bac46b24-b9a2-4a17-ab48-c2327b82b67a": "23efa6a39dfe8c7d79be2a6340da613909447fd9a708f3c997dca0f12da86adf",
}
SCALES = {"ORIGINAL_RESOLUTION", "AUDIENCE_SCALE_720X1280"}
REQUIREMENTS = {
    "persist_failure_memory_before_retry",
    "materially_change_prompt_or_representation",
    "use_new_task_key",
    "use_new_submission_fingerprint",
    "obtain_new_independent_authorization",
    "persist_transaction_before_provider_post",
    "classify_authoritative_credit_before_retry_decision",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_sha(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def timestamp_ok(value: object) -> bool:
    try:
        return isinstance(value, str) and datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def identity(value: object) -> str:
    return " ".join(str(value or "").split()).casefold()


def safe_locked_json(path_value: object, expected_sha: object, root: Path, label: str, failures: list[str]) -> dict:
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
        failures.append(f"{label}_PHYSICAL_SHA_MISMATCH")
        return {}
    try:
        return json.loads(resolved.read_text(encoding="utf-8"))
    except Exception:
        failures.append(f"{label}_INVALID_JSON")
        return {}


def base(status: str, failures: list[str], request: dict | None, memory: dict | None) -> dict:
    return {
        "schema": "qingshan.e40.u18.v23.independent_authority_review_result.v1",
        "status": status,
        "scope": "U18_ONLY",
        "blocks_other_lanes": False,
        "failures": sorted(set(failures)),
        "authorization_request": request,
        "formal_memory_update_proposal": memory,
        "direct_admission_permitted": False,
        "formal_memory_write_performed": False,
        "composite_permitted": False,
        "video_authorization_permitted": False,
        "provider_post_allowed": False,
        "maximum_new_submissions": 0,
        "network_capability": False,
    }


def review(subject_path: Path, authority_review_path: Path, project_root: Path = ROOT) -> dict:
    failures: list[str] = []
    if subject_path.is_symlink() or authority_review_path.is_symlink():
        failures.append("SYMLINK_INPUT_REJECTED")
    try:
        subject = json.loads(subject_path.read_text(encoding="utf-8"))
    except Exception:
        subject = {}
        failures.append("V21_SUBJECT_MISSING_OR_INVALID")
    try:
        authority = json.loads(authority_review_path.read_text(encoding="utf-8"))
    except Exception:
        authority = {}
        failures.append("AUTHORITY_REVIEW_MISSING_OR_INVALID")
    subject_sha = sha256(subject_path) if subject_path.is_file() else None
    authority_reviewer = authority.get("authority_reviewer")
    if not isinstance(authority_reviewer, str) or not authority_reviewer.strip():
        failures.append("AUTHORITY_REVIEWER_MISSING")
    if not timestamp_ok(authority.get("authority_reviewed_at")):
        failures.append("AUTHORITY_REVIEWED_AT_MISSING_OR_INVALID")
    if authority.get("v21_subject_sha256") != subject_sha:
        failures.append("STALE_OR_WRONG_V21_SUBJECT_SHA")
    receipt_path = project_root / V21_RECEIPT[0]
    if not receipt_path.is_file() or sha256(receipt_path) != V21_RECEIPT[1] or authority.get("v21_receipt_sha256") != V21_RECEIPT[1]:
        failures.append("V21_RECEIPT_SHA_LOCK_FAILED")

    schema = subject.get("schema")
    if schema == "qingshan.e40.u18.v21.asset_admission_proposal.v1":
        if subject.get("status") != "PROPOSED_PENDING_INDEPENDENT_AUTHORIZATION":
            failures.append("V21_PASS_PROPOSAL_STATUS_MISMATCH")
        if identity(authority_reviewer) == identity(subject.get("reviewer")):
            failures.append("SELF_REVIEW_REJECTED")
        if any(subject.get(key) is not False for key in ("output_admission_permitted", "composite_permitted", "video_authorization_permitted")):
            failures.append("V21_PROPOSAL_PERMISSION_FLAG_NOT_FALSE")
        locks = subject.get("source_locks") or {}
        human = safe_locked_json(locks.get("human_qa_manifest_path"), locks.get("human_qa_manifest_sha256"), project_root, "V19_HUMAN_MANIFEST", failures)
        input_locks = human.get("input_locks") or {}
        promotion = safe_locked_json(input_locks.get("v17_promotion_path"), input_locks.get("v17_promotion_sha256"), project_root, "V17_PROMOTION", failures)
        credit = promotion.get("credit_classification") or {}
        credit_snapshot = (promotion.get("source_snapshot_locks") or {}).get("authoritative_credit") or {}
        if any(credit.get(key) is None for key in ("pay", "refund", "net", "status")) or credit.get("net") != credit.get("pay") - credit.get("refund"):
            failures.append("CREDIT_CLASSIFICATION_INCOMPLETE_OR_INVALID")
        if not isinstance(credit_snapshot.get("sha256"), str):
            failures.append("AUTHORITATIVE_CREDIT_SNAPSHOT_SHA_MISSING")
        expected_review_locks = {
            "v19_human_manifest_sha256": locks.get("human_qa_manifest_sha256"),
            "v17_promotion_sha256": input_locks.get("v17_promotion_sha256"),
            "credit_classification_sha256": json_sha(credit),
            "authoritative_credit_snapshot_sha256": credit_snapshot.get("sha256"),
        }
        if authority.get("binding_locks") != expected_review_locks:
            failures.append("AUTHORITY_REVIEW_BINDING_LOCKS_STALE_OR_INCOMPLETE")
        proposal_assets = {row.get("exact_task_id"): row for row in subject.get("assets") or []}
        human_assets = {row.get("exact_task_id"): row for row in human.get("assets") or []}
        for task_id, fingerprint in EXPECTED.items():
            proposed = proposal_assets.get(task_id) or {}
            source = human_assets.get(task_id) or {}
            if proposed.get("transaction_fingerprint") != fingerprint or source.get("transaction_fingerprint") != fingerprint:
                failures.append(f"TASK_FINGERPRINT_BINDING_MISMATCH:{task_id}")
            if proposed.get("output_sha256") != source.get("output_sha256") or not source.get("output_sha256"):
                failures.append(f"OUTPUT_SHA_BINDING_MISMATCH:{task_id}")
            if not str(source.get("provenance") or "").strip() or not str(source.get("license_or_local_authorship") or "").strip():
                failures.append(f"PROVENANCE_OR_RIGHTS_MISSING:{task_id}")
            layers = proposed.get("review_layers") or []
            if {row.get("name") for row in layers} != SCALES or len(layers) != 2:
                failures.append(f"DUAL_SCALE_REVIEW_MISSING:{task_id}")
            for layer in layers:
                hard_gates = layer.get("hard_gate_results")
                if layer.get("decision") != "PASS" or layer.get("score", 0) < 80 or not isinstance(hard_gates, dict) or set(hard_gates) != HARD_GATES[task_id] or any(value is not True for value in hard_gates.values()):
                    failures.append(f"HUMAN_HARD_GATE_NOT_ALL_PASS:{task_id}:{layer.get('name')}")
        if set(proposal_assets) != set(EXPECTED) or set(human_assets) != set(EXPECTED):
            failures.append("EXACT_TWO_ASSET_SET_MISMATCH")
        if failures:
            return base("TASK_LOCAL_REMOTE_WAIT", failures, None, None)
        request = {
            "schema": "qingshan.e40.u18.v23.authorization_request.v1",
            "status": "AUTHORIZATION_REQUEST_READY_NOT_AUTHORIZED",
            "authority_reviewer": authority_reviewer,
            "authority_reviewed_at": authority.get("authority_reviewed_at"),
            "subject_sha256": subject_sha,
            "binding_locks": expected_review_locks,
            "assets": sorted(subject.get("assets"), key=lambda row: row["exact_task_id"]),
            "authorization_granted": False,
            "direct_admission_permitted": False,
            "composite_permitted": False,
            "video_authorization_permitted": False,
        }
        return base("AUTHORIZATION_REQUEST_READY", [], request, None)

    if schema == "qingshan.e40.u18.v21.failure_memory_draft.v1":
        if subject.get("status") != "DRAFT_ONLY_NOT_WRITTEN_TO_FORMAL_MEMORY" or subject.get("formal_memory_update_permitted") is not False or subject.get("retry_authorized") is not False:
            failures.append("V21_FAILURE_DRAFT_BOUNDARY_INVALID")
        if identity(authority_reviewer) == identity(subject.get("reviewer")):
            failures.append("SELF_REVIEW_REJECTED")
        if not subject.get("failures"):
            failures.append("FAILURE_DRAFT_HAS_NO_FAILURES")
        quarantine = set(authority.get("original_fingerprint_quarantine") or [])
        if quarantine != set(EXPECTED.values()):
            failures.append("ORIGINAL_FINGERPRINT_QUARANTINE_MISMATCH")
        requirements = authority.get("materially_changed_next_attempt_requirements") or {}
        if set(requirements) != REQUIREMENTS or any(requirements.get(key) is not True for key in REQUIREMENTS):
            failures.append("MATERIALLY_CHANGED_NEXT_ATTEMPT_REQUIREMENTS_INCOMPLETE")
        if failures:
            return base("TASK_LOCAL_REMOTE_WAIT", failures, None, None)
        memory = {
            "schema": "qingshan.e40.u18.v23.formal_memory_update_proposal.v1",
            "status": "FORMAL_MEMORY_UPDATE_PROPOSAL_ONLY_NOT_WRITTEN",
            "authority_reviewer": authority_reviewer,
            "authority_reviewed_at": authority.get("authority_reviewed_at"),
            "subject_sha256": subject_sha,
            "failures": subject.get("failures"),
            "original_fingerprint_quarantine": sorted(quarantine),
            "materially_changed_next_attempt_requirements": requirements,
            "formal_memory_write_permitted": False,
            "retry_authorized": False,
        }
        return base("FORMAL_MEMORY_UPDATE_PROPOSAL_ONLY", [], None, memory)

    failures.append("V21_SUBJECT_SCHEMA_NOT_ACCEPTED")
    return base("TASK_LOCAL_REMOTE_WAIT", failures, None, None)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v21-subject", required=True, type=Path)
    parser.add_argument("--authority-review", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = review(args.v21_subject, args.authority_review)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0 if result["status"] in {"AUTHORIZATION_REQUEST_READY", "FORMAL_MEMORY_UPDATE_PROPOSAL_ONLY"} else 3


if __name__ == "__main__":
    raise SystemExit(main())
