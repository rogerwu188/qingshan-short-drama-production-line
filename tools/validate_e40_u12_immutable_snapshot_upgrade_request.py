#!/usr/bin/env python3
"""Fail-closed validator for E40/U12 validator snapshot-before-upgrade requests.

This tool is read-only with respect to the target validator. It proves that exact
prior bytes already exist in the content-addressed archive before an upgrade may
be considered; it never grants production or provider authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
POLICY_SCHEMA = "qingshan.e40.u12.v22.immutable_pre_upgrade_snapshot_policy.v1"
REQUEST_SCHEMA = "qingshan.e40.u12.v22.validator_upgrade_snapshot_request.v1"
GATE_SCHEMA = "qingshan.e40.u12.v22.immutable_snapshot_upgrade_gate.v1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repo_path(value: str) -> Path:
    candidate = (ROOT / value).resolve()
    candidate.relative_to(ROOT)
    return candidate


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def check(checks: list[dict[str, Any]], name: str, passed: bool, detail: Any) -> None:
    checks.append({"check": name, "status": "PASS" if passed else "FAIL", "detail": detail})


def validate(policy: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    check(checks, "POLICY_SCHEMA", policy.get("schema") == POLICY_SCHEMA, policy.get("schema"))
    check(checks, "REQUEST_SCHEMA", request.get("schema") == REQUEST_SCHEMA, request.get("schema"))

    mode = request.get("mode")
    allowed_modes = policy.get("allowed_request_modes") or []
    check(checks, "REQUEST_MODE_ALLOWED", mode in allowed_modes, mode)

    target_rel = request.get("target_validator_path") or ""
    check(
        checks,
        "TARGET_PATH_POLICY_PINNED",
        target_rel == policy.get("target_validator_path"),
        target_rel,
    )
    try:
        target = repo_path(target_rel)
        target_exists = target.is_file()
        target_sha = sha256(target) if target_exists else None
    except (ValueError, OSError):
        target = ROOT
        target_exists = False
        target_sha = None
    check(checks, "TARGET_EXISTS", target_exists, target_rel)

    prior = request.get("prior_version") or {}
    prior_sha = prior.get("sha256") or ""
    archive_rel = prior.get("archive_path") or ""
    prefix = (policy.get("requirements") or {}).get("prior_archive_path_prefix") or ""
    prefix_len = int((policy.get("requirements") or {}).get("prior_archive_path_must_contain_prior_sha_prefix_length") or 64)
    check(checks, "PRIOR_SHA_FORMAT", len(prior_sha) == 64 and all(c in "0123456789abcdef" for c in prior_sha), prior_sha)
    check(checks, "ARCHIVE_PATH_PREFIX", archive_rel.startswith(prefix), archive_rel)
    check(checks, "ARCHIVE_PATH_CONTAINS_PRIOR_SHA_PREFIX", prior_sha[:prefix_len] in archive_rel, prior_sha[:prefix_len])
    check(checks, "ARCHIVE_PATH_DISTINCT_FROM_TARGET", archive_rel != target_rel, archive_rel)
    try:
        archive_lexical = ROOT / archive_rel
        archive = repo_path(archive_rel)
        archive_exists = archive.is_file()
        archive_symlink = archive_lexical.is_symlink()
        archive_sha = sha256(archive) if archive_exists and not archive_symlink else None
    except (ValueError, OSError):
        archive_exists = False
        archive_symlink = False
        archive_sha = None
    check(checks, "PRIOR_ARCHIVE_EXISTS", archive_exists, archive_rel)
    check(checks, "PRIOR_ARCHIVE_NOT_SYMLINK", archive_exists and not archive_symlink, archive_rel)
    check(checks, "PRIOR_ARCHIVE_SHA_EXACT", archive_sha == prior_sha, {"expected": prior_sha, "actual": archive_sha})

    proposed = request.get("proposed_version") or {}
    proposed_rel = proposed.get("source_path") or ""
    proposed_sha = proposed.get("sha256") or ""
    try:
        proposed_path = repo_path(proposed_rel)
        proposed_exists = proposed_path.is_file()
        proposed_actual_sha = sha256(proposed_path) if proposed_exists else None
    except (ValueError, OSError):
        proposed_exists = False
        proposed_actual_sha = None
    check(checks, "PROPOSED_SOURCE_EXISTS", proposed_exists, proposed_rel)
    check(checks, "PROPOSED_SOURCE_SHA_EXACT", proposed_actual_sha == proposed_sha, {"expected": proposed_sha, "actual": proposed_actual_sha})
    check(checks, "PROPOSED_SHA_DIFFERS_FROM_PRIOR", bool(proposed_sha) and proposed_sha != prior_sha, {"prior": prior_sha, "proposed": proposed_sha})

    try:
        archive_time = parse_time(prior.get("archive_persisted_at") or "")
        request_time = parse_time(request.get("upgrade_requested_at") or "")
        time_order_ok = archive_time <= request_time
    except (TypeError, ValueError):
        time_order_ok = False
    check(checks, "ARCHIVE_PERSISTED_BEFORE_REQUEST", time_order_ok, {"archive": prior.get("archive_persisted_at"), "request": request.get("upgrade_requested_at")})

    if mode == "PRE_UPGRADE":
        check(checks, "PRE_UPGRADE_TARGET_IS_PRIOR", target_sha == prior_sha, {"target": target_sha, "prior": prior_sha})
        check(checks, "PRE_UPGRADE_MUTATION_DECLARED", request.get("mutation_requested") is True, request.get("mutation_requested"))
    elif mode == "HISTORICAL_TRANSITION_ATTESTATION":
        check(checks, "HISTORICAL_TARGET_IS_PROPOSED", target_sha == proposed_sha, {"target": target_sha, "proposed": proposed_sha})
        check(checks, "HISTORICAL_ATTESTATION_ONLY", request.get("historical_attestation_only") is True and request.get("mutation_requested") is False, {"historical": request.get("historical_attestation_only"), "mutation": request.get("mutation_requested")})

    failures = [item for item in checks if item["status"] == "FAIL"]
    status = "PASS_ARCHIVE_PRECONDITION_PROVEN_NO_MUTATION" if not failures else "FAIL_CLOSED_PRIOR_SNAPSHOT_NOT_PROVEN_NO_MUTATION"
    return {
        "schema": GATE_SCHEMA,
        "status": status,
        "request_id": request.get("request_id"),
        "mode": mode,
        "checks": checks,
        "failure_count": len(failures),
        "failures": [item["check"] for item in failures],
        "target_validator_mutated": False,
        "authority_keys_admitted": 0,
        "production_assets_admitted": 0,
        "authorization": False,
        "maximum_new_submissions": 0,
        "failure_behavior": policy.get("failure_behavior"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", required=True)
    parser.add_argument("--request", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--expect-status")
    args = parser.parse_args()
    policy = json.loads(repo_path(args.policy).read_text())
    request = json.loads(repo_path(args.request).read_text())
    before_sha = sha256(repo_path(policy["target_validator_path"]))
    result = validate(policy, request)
    after_sha = sha256(repo_path(policy["target_validator_path"]))
    result["target_sha256_before"] = before_sha
    result["target_sha256_after"] = after_sha
    result["target_validator_mutated"] = before_sha != after_sha
    if result["target_validator_mutated"]:
        result["status"] = "FAIL_CLOSED_TARGET_MUTATION_DETECTED"
        result["failure_count"] += 1
        result["failures"].append("TARGET_VALIDATOR_UNCHANGED_DURING_GATE")
    out = repo_path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "failures": result["failures"], "target_mutated": result["target_validator_mutated"]}))
    if args.expect_status and result["status"] != args.expect_status:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
