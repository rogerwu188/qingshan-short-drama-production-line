#!/usr/bin/env python3
"""Fail-closed validator for E40 U12 trusted-authority admission requests."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_SCHEMA = "qingshan.e40.u12.v10.trusted_authority_admission_key_custody_contract.v1"
REQUEST_SCHEMA = "qingshan.e40.u12.trusted_authority_admission_request.v1"
ALLOWED_PURPOSES = {"PRODUCTION_SOURCE_AUTHORITY", "PRODUCTION_QA_AUTHORITY"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def fail(failures: list[dict[str, Any]], code: str, actual: Any, expected: Any) -> None:
    if actual != expected:
        failures.append({"code": code, "actual": actual, "expected": expected})


def parse_time(raw: Any) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def resolve_evidence(ref: Any, label: str, failures: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not isinstance(ref, dict):
        failures.append({"code": f"{label}_REFERENCE", "actual": ref, "expected": "path+sha256 object"})
        return None
    raw = ref.get("path")
    if not isinstance(raw, str) or not raw:
        failures.append({"code": f"{label}_PATH", "actual": raw, "expected": "repo-relative JSON path"})
        return None
    rel = Path(raw)
    if rel.is_absolute() or ".." in rel.parts:
        failures.append({"code": f"{label}_PATH", "actual": raw, "expected": "safe repo-relative path"})
        return None
    path = (ROOT / rel).resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError:
        failures.append({"code": f"{label}_PATH", "actual": raw, "expected": "inside repository"})
        return None
    if not path.is_file():
        failures.append({"code": f"{label}_MISSING", "actual": raw, "expected": "existing JSON"})
        return None
    actual_sha = sha256_file(path)
    fail(failures, f"{label}_SHA256", ref.get("sha256"), actual_sha)
    try:
        return load_json(path)
    except Exception as exc:
        failures.append({"code": f"{label}_JSON", "actual": str(exc), "expected": "valid JSON object"})
        return None


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--request", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--expect-reject", action="store_true")
    args = parser.parse_args()

    contract_path = (ROOT / args.contract).resolve()
    request_path = (ROOT / args.request).resolve()
    out_path = (ROOT / args.out).resolve()
    contract = load_json(contract_path)
    request = load_json(request_path)
    failures: list[dict[str, Any]] = []

    fail(failures, "CONTRACT_SCHEMA", contract.get("schema"), CONTRACT_SCHEMA)
    fail(failures, "CONTRACT_STATUS", contract.get("status"), "READY_CONTRACT_NO_AUTHORITIES_ADMITTED_NO_SUBMIT")
    fail(failures, "REQUEST_SCHEMA", request.get("schema"), REQUEST_SCHEMA)
    fail(failures, "REQUEST_CONTRACT_SHA256", request.get("contract_sha256"), sha256_file(contract_path))
    fail(failures, "REQUEST_AUTHORIZATION_FALSE", request.get("authorization"), False)
    fail(failures, "REQUEST_MAXIMUM_SUBMISSIONS_ZERO", request.get("maximum_new_submissions"), 0)

    purpose = request.get("purpose")
    fail(failures, "PURPOSE_ALLOWED", purpose in ALLOWED_PURPOSES, True)
    authority_id = request.get("authority_id")
    fail(failures, "AUTHORITY_ID_PRESENT", isinstance(authority_id, str) and len(authority_id) >= 8, True)
    applicant = request.get("applicant_actor_id")
    owner = request.get("authority_owner_actor_id")
    fail(failures, "APPLICANT_PRESENT", isinstance(applicant, str) and bool(applicant), True)
    fail(failures, "OWNER_PRESENT", isinstance(owner, str) and bool(owner), True)
    fail(failures, "CANDIDATE_AUTHOR_MAY_NOT_SELF_ADMIT", applicant != owner, True)

    key_b64 = request.get("public_key_raw_base64")
    key_bytes: bytes | None = None
    try:
        key_bytes = base64.b64decode(key_b64, validate=True)
        fail(failures, "PUBLIC_KEY_LENGTH", len(key_bytes), 32)
        fail(failures, "PUBLIC_KEY_SHA256", request.get("public_key_sha256"), hashlib.sha256(key_bytes).hexdigest())
    except Exception as exc:
        failures.append({"code": "PUBLIC_KEY_ENCODING", "actual": str(exc), "expected": "32-byte base64 Ed25519 public key"})

    nonce = request.get("nonce")
    signature_b64 = request.get("nonce_signature_base64")
    fail(failures, "NONCE_MINIMUM_LENGTH", isinstance(nonce, str) and len(nonce) >= 32, True)
    if key_bytes is not None and len(key_bytes) == 32 and isinstance(nonce, str):
        try:
            signature = base64.b64decode(signature_b64, validate=True)
            Ed25519PublicKey.from_public_bytes(key_bytes).verify(signature, nonce.encode("utf-8"))
        except (ValueError, TypeError, InvalidSignature) as exc:
            failures.append({"code": "NONCE_SIGNATURE_INVALID", "actual": type(exc).__name__, "expected": "valid Ed25519 signature over exact nonce UTF-8"})

    now = datetime.now(timezone.utc)
    not_before = parse_time(request.get("valid_not_before"))
    not_after = parse_time(request.get("valid_not_after"))
    fail(failures, "VALID_NOT_BEFORE", not_before is not None and not_before <= now, True)
    fail(failures, "VALID_NOT_AFTER", not_after is not None and not_after > now, True)
    fail(failures, "VALIDITY_ORDER", not_before is not None and not_after is not None and not_before < not_after, True)
    fail(failures, "REVOCATION_CONTACT_PRESENT", isinstance(request.get("revocation_contact"), str) and bool(request.get("revocation_contact")), True)

    owner_doc = resolve_evidence(request.get("owner_attestation"), "OWNER_ATTESTATION", failures)
    custody_doc = resolve_evidence(request.get("custody_attestation"), "CUSTODY_ATTESTATION", failures)
    roger_doc = resolve_evidence(request.get("roger_authorization"), "ROGER_AUTHORIZATION", failures)
    signoff_doc = resolve_evidence(request.get("independent_signoff"), "INDEPENDENT_SIGNOFF", failures)

    if owner_doc is not None:
        fail(failures, "OWNER_ATTESTATION_SCHEMA", owner_doc.get("schema"), "qingshan.e40.u12.authority_owner_attestation.v1")
        fail(failures, "OWNER_ATTESTATION_ACTOR", owner_doc.get("actor_id"), owner)
        fail(failures, "OWNER_ATTESTATION_KEY", owner_doc.get("public_key_sha256"), request.get("public_key_sha256"))
        fail(failures, "OWNER_ATTESTATION_PURPOSE", owner_doc.get("purpose"), purpose)
    if custody_doc is not None:
        fail(failures, "CUSTODY_ATTESTATION_SCHEMA", custody_doc.get("schema"), "qingshan.e40.u12.offline_key_custody_attestation.v1")
        fail(failures, "CUSTODY_PRIVATE_KEY_NOT_REPO", custody_doc.get("private_key_in_repository"), False)
        fail(failures, "CUSTODY_PRIVATE_KEY_NOT_LOG_ENV_PROMPT", custody_doc.get("private_key_in_log_env_or_prompt"), False)
        fail(failures, "CUSTODY_KEY_FINGERPRINT", custody_doc.get("public_key_sha256"), request.get("public_key_sha256"))
    if roger_doc is not None:
        fail(failures, "ROGER_AUTHORIZATION_SCHEMA", roger_doc.get("schema"), "qingshan.e40.u12.roger_authority_admission_authorization.v1")
        fail(failures, "ROGER_AUTHORIZATION_EXPLICIT", roger_doc.get("authorization"), True)
        fail(failures, "ROGER_AUTHORIZATION_SCOPE", roger_doc.get("scope"), "E40_U12_TRUSTED_AUTHORITY_ADMISSION")
        fail(failures, "ROGER_AUTHORIZATION_KEY", roger_doc.get("public_key_sha256"), request.get("public_key_sha256"))
        fail(failures, "ROGER_AUTHORIZATION_PURPOSE", roger_doc.get("purpose"), purpose)
    if signoff_doc is not None:
        signoff_actor = signoff_doc.get("actor_id")
        fail(failures, "INDEPENDENT_SIGNOFF_SCHEMA", signoff_doc.get("schema"), "qingshan.e40.u12.independent_authority_admission_signoff.v1")
        fail(failures, "INDEPENDENT_SIGNOFF_APPROVED", signoff_doc.get("approved"), True)
        fail(failures, "INDEPENDENT_SIGNOFF_KEY", signoff_doc.get("public_key_sha256"), request.get("public_key_sha256"))
        fail(failures, "INDEPENDENT_SIGNOFF_ACTOR_PRESENT", isinstance(signoff_actor, str) and bool(signoff_actor), True)
        fail(failures, "INDEPENDENT_SIGNOFF_NOT_APPLICANT", signoff_actor != applicant, True)
        fail(failures, "INDEPENDENT_SIGNOFF_NOT_OWNER", signoff_actor != owner, True)

    status = "PASS_REQUEST_ELIGIBLE_FOR_SEPARATE_POLICY_ADMISSION_REVIEW" if not failures else "FAIL_CLOSED_AUTHORITY_ADMISSION_REQUEST_REJECTED"
    receipt = {
        "schema": "qingshan.e40.u12.v11.authority_admission_request_gate.v1",
        "recorded_at": now.isoformat(),
        "status": status,
        "contract": args.contract,
        "contract_sha256": sha256_file(contract_path),
        "request": args.request,
        "request_sha256": sha256_file(request_path),
        "failure_count": len(failures),
        "failures": failures,
        "authority_admitted": False,
        "policy_changed": False,
        "failure_behavior": "NO_KEY_ADMISSION_NO_SOURCE_ADMISSION_NO_RENDER_NO_SUBMIT_NO_TRANSACTION_NO_CREDITS_NO_AGENTCUT_NO_ASSEMBLY",
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "failure_count": len(failures), "out": args.out}, ensure_ascii=False))
    if args.expect_reject:
        return 0 if failures else 3
    return 0 if not failures else 2


if __name__ == "__main__":
    sys.exit(main())
