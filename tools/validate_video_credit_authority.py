#!/usr/bin/env python3
"""Validate the current video-credit authority chain without binding mutable reports."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def evaluate(authority: dict, root: Path = ROOT) -> dict:
    failures: list[str] = []
    chain = authority.get("active_authority_chain", [])
    by_role = {item.get("role"): item for item in chain}

    runtime_ref = by_role.get("runtime_enforcement", {})
    corrected_ref = by_role.get("account_window_correction_and_human_approval_target", {})
    final_ref = by_role.get("final_evidence_boundary_reconciliation", {})

    required_roles = {
        "runtime_enforcement": runtime_ref,
        "account_window_correction_and_human_approval_target": corrected_ref,
        "final_evidence_boundary_reconciliation": final_ref,
    }
    for role, item in required_roles.items():
        if not item:
            failures.append(f"missing_authority_role:{role}")

    if failures:
        return _result(authority, failures, {})

    runtime = load_json(resolve(root, runtime_ref["path"]))
    corrected_path = resolve(root, corrected_ref["path"])
    final_path = resolve(root, final_ref["path"])
    corrected = load_json(corrected_path)
    final = load_json(final_path)
    current = authority.get("current_authoritative_values", {})
    option_a = authority.get("u09", {}).get("option_a", {})

    if "sha256" in runtime_ref:
        failures.append("runtime_report_must_not_bind_fixed_sha256")
    if runtime_ref.get("integrity_policy") != "MUTABLE_RUNTIME_REPORT_NOT_APPROVAL_TARGET":
        failures.append("runtime_integrity_policy_missing")

    expected = runtime_ref.get("expected_facts", {})
    runtime_facts = {
        "status": runtime.get("status"),
        "actual_charged_credits_known_total": runtime.get("actual_charged_credits_known_total"),
        "actual_total_complete": runtime.get("actual_total_complete"),
        "pending_attempt_count": runtime.get("pending_attempt_count"),
        "approval_valid": runtime.get("approval", {}).get("valid"),
        "approval_binding_valid": runtime.get("approval", {}).get("binding_valid"),
    }
    for key, expected_value in expected.items():
        if runtime_facts.get(key) != expected_value:
            failures.append(
                f"runtime_fact_mismatch:{key}:expected={expected_value}:actual={runtime_facts.get(key)}"
            )

    actual = current.get("actual_charged_video_credits")
    if runtime.get("actual_charged_credits_known_total") != actual:
        failures.append("authority_runtime_actual_credit_mismatch")
    if corrected.get("actual_charged_video_credits") != actual:
        failures.append("authority_corrected_actual_credit_mismatch")
    if final.get("episode_exact_video_credits", {}).get("E28") != actual:
        failures.append("authority_final_evidence_actual_credit_mismatch")

    corrected_digest = sha256(corrected_path)
    final_digest = sha256(final_path)
    if corrected_digest != corrected_ref.get("sha256"):
        failures.append("corrected_gate_sha256_mismatch")
    if final_digest != final_ref.get("sha256"):
        failures.append("final_evidence_sha256_mismatch")
    if option_a.get("required_gate_sha256") != corrected_digest:
        failures.append("option_a_gate_sha256_mismatch")
    if option_a.get("minimum_new_limit_credits") != actual + option_a.get(
        "new_generation_credits_if_successful", 0
    ):
        failures.append("option_a_minimum_limit_arithmetic_mismatch")
    if actual != 51024:
        failures.append("e28_authoritative_total_not_51024")
    if option_a.get("minimum_new_limit_credits") != 51284:
        failures.append("e28_option_a_minimum_not_51284")

    observed = {
        "runtime_report_sha256_observed_only": sha256(resolve(root, runtime_ref["path"])),
        "runtime_facts": runtime_facts,
        "corrected_gate_sha256": corrected_digest,
        "final_evidence_sha256": final_digest,
        "actual_charged_video_credits": actual,
        "option_a_minimum_new_limit_credits": option_a.get("minimum_new_limit_credits"),
    }
    return _result(authority, failures, observed)


def _result(authority: dict, failures: list[str], observed: dict) -> dict:
    return {
        "schema": "qingshan.video_credit_authority_validation.v1",
        "episode": authority.get("episode"),
        "status": "PASS" if not failures else "FAIL",
        "authority_status": authority.get("status"),
        "checks_enforced": [
            "mutable_runtime_report_semantic_only",
            "immutable_corrected_gate_sha256_bound",
            "immutable_final_evidence_sha256_bound",
            "cross_document_credit_total_consistent",
            "option_a_minimum_arithmetic_consistent",
        ],
        "observed": observed,
        "failures": failures,
        "remote_call_count": 0,
        "generation_call_count": 0,
        "new_credits": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--authority",
        default="workflow/credit_reports/E28_VIDEO_CREDIT_AUTHORITY_LATEST.json",
    )
    parser.add_argument("--out")
    args = parser.parse_args()
    authority_path = resolve(ROOT, args.authority)
    report = evaluate(load_json(authority_path), ROOT)
    if args.out:
        output = resolve(ROOT, args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
