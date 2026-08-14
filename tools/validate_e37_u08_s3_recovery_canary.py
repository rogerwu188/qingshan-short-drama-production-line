#!/usr/bin/env python3
"""Fail-closed validator for the E37 U08-S3 provider recovery canary."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PACKET_PATH = ROOT / "workflow/tasks/E37_U08_S3_PROVIDER_RECOVERY_CANARY_PACKET_V1_20260802.json"
PREFLIGHT_PATH = ROOT / "qa/e37_preproduction_20260802/E37_U08_S3_PROVIDER_RECOVERY_CANARY_PREFLIGHT_V1.json"
DISPATCH_PATH = ROOT / "workflow/tasks/E37_AUTONOMOUS_FOCUSED_CONCURRENT_DISPATCH_V1.json"

PACKET_SHA256 = "8823362987c67f33bffd9250f0da3980f1c3e72bde02b5640c2f217f1c3c0f9b"
PREFLIGHT_SHA256 = "b90979621acaa521f928b84e204b59aee6dcb417cfd2ff426c1cf3fa2e9fd955"
ALLOWED_SIGNAL_TYPES = {
    "PROVIDER_FIXED_DEPLOYMENT",
    "INDEPENDENT_KNOWN_GOOD_NEW_OUTPUT",
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve(relative_path: str) -> Path:
    path = (ROOT / relative_path).resolve()
    path.relative_to(ROOT)
    return path


def validate_signal(signal: dict[str, Any] | None) -> tuple[bool, str]:
    if signal is None:
        return False, "RECOVERY_SIGNAL_MISSING"
    if signal.get("schema") != "qingshan.giggle.provider_recovery_signal.v1":
        return False, "RECOVERY_SIGNAL_SCHEMA_MISMATCH"
    if signal.get("provider") != "giggle":
        return False, "RECOVERY_SIGNAL_PROVIDER_MISMATCH"
    if signal.get("status") != "PASS_NEW_OUTPUT_PERSISTENCE_RECOVERED":
        return False, "RECOVERY_SIGNAL_STATUS_NOT_PASS"
    evidence_type = signal.get("evidence_type")
    if evidence_type not in ALLOWED_SIGNAL_TYPES:
        return False, "RECOVERY_SIGNAL_EVIDENCE_TYPE_INVALID"
    if not signal.get("verified_at"):
        return False, "RECOVERY_SIGNAL_VERIFIED_AT_MISSING"
    if evidence_type == "INDEPENDENT_KNOWN_GOOD_NEW_OUTPUT":
        evidence = signal.get("evidence") or {}
        if evidence.get("status") != "completed":
            return False, "KNOWN_GOOD_OUTPUT_NOT_COMPLETED"
        if int(evidence.get("urls_count") or 0) < 1:
            return False, "KNOWN_GOOD_OUTPUT_URL_MISSING"
        if not evidence.get("task_id"):
            return False, "KNOWN_GOOD_OUTPUT_TASK_ID_MISSING"
    return True, "PASS"


def collect_sha_gates(packet: dict[str, Any], preflight: dict[str, Any]) -> list[dict[str, Any]]:
    bindings: list[tuple[str, str, str]] = [
        ("packet", str(PACKET_PATH.relative_to(ROOT)), PACKET_SHA256),
        ("preflight", str(PREFLIGHT_PATH.relative_to(ROOT)), PREFLIGHT_SHA256),
        ("canonical_script", packet["canonical"]["script"], packet["canonical"]["script_sha256"]),
        ("canonical_manifest", packet["canonical"]["manifest"], packet["canonical"]["manifest_sha256"]),
        ("compiled_prompt", packet["compiled_prompt"]["path"], packet["compiled_prompt"]["sha256"]),
        ("agentcut_project", preflight["agentcut"]["project"], preflight["agentcut"]["project_sha256"]),
        ("agentcut_timeline", preflight["agentcut"]["timeline"], preflight["agentcut"]["timeline_sha256"]),
    ]
    for index, reference in enumerate(packet["reference_images"], start=1):
        bindings.append((f"reference_{index}", reference["path"], reference["sha256"]))

    gates = []
    for name, relative_path, expected in bindings:
        path = resolve(relative_path)
        actual = sha256(path) if path.is_file() else None
        gates.append(
            {
                "name": name,
                "path": relative_path,
                "expected_sha256": expected,
                "actual_sha256": actual,
                "status": "PASS" if actual == expected else "FAIL",
            }
        )
    return gates


def validate(signal: dict[str, Any] | None) -> dict[str, Any]:
    packet = load_json(PACKET_PATH)
    preflight = load_json(PREFLIGHT_PATH)
    dispatch = load_json(DISPATCH_PATH)
    sha_gates = collect_sha_gates(packet, preflight)
    sha_pass = all(item["status"] == "PASS" for item in sha_gates)
    signal_pass, signal_reason = validate_signal(signal)

    canary = dispatch.get("provider_recovery_canary") or {}
    credits = dispatch.get("credits") or {}
    headroom = int(credits.get("headroom") or 0)
    max_submissions = int(packet["submission_gates"]["maximum_submission_count_after_recovery"])
    not_submitted = "NOT_SUBMITTED" in str(canary.get("status") or "")
    dialogue_once = packet["compiled_prompt"]["exact_dialogue_occurrences"] == 1
    anchor = packet["reference_images"][0]
    score_pass = int(anchor["accepted_score"]) >= int(anchor["pass_score"])
    policy_pass = max_submissions == 1 and not_submitted and headroom > 0

    ready = all((sha_pass, signal_pass, dialogue_once, score_pass, policy_pass))
    return {
        "schema": "qingshan.e37.u08_s3_recovery_canary_guard.v1",
        "episode": "E37",
        "task_key": packet["task_key"],
        "status": "PASS_READY_FOR_SINGLE_SUBMISSION" if ready else "BLOCKED_CORRECTLY",
        "submission_executed": False,
        "gates": {
            "exact_sha": "PASS" if sha_pass else "FAIL",
            "recovery_signal": "PASS" if signal_pass else f"FAIL_{signal_reason}",
            "dialogue_exact_once": "PASS" if dialogue_once else "FAIL",
            "start_anchor_score": "PASS" if score_pass else "FAIL",
            "maximum_submission_count": "PASS_ONE" if max_submissions == 1 else "FAIL",
            "prior_submission": "PASS_NONE" if not_submitted else "FAIL_ALREADY_SUBMITTED",
            "credit_headroom": f"PASS_{headroom}" if headroom > 0 else "FAIL_ZERO",
        },
        "sha_bindings": sha_gates,
        "credits": {
            "pay": credits.get("pay"),
            "refund": credits.get("refund"),
            "net": credits.get("net"),
            "episode_cap": credits.get("episode_cap"),
            "headroom": headroom,
        },
        "next_action": (
            "Submit exactly one U08-S3 canary through the existing guarded provider path."
            if ready
            else "Keep submission closed until every gate passes; do not infer recovery from historical completed outputs."
        ),
    }


def self_test() -> dict[str, Any]:
    fixed = {
        "schema": "qingshan.giggle.provider_recovery_signal.v1",
        "provider": "giggle",
        "status": "PASS_NEW_OUTPUT_PERSISTENCE_RECOVERED",
        "evidence_type": "PROVIDER_FIXED_DEPLOYMENT",
        "verified_at": "2026-08-02T00:00:00Z",
    }
    known_good = {
        **fixed,
        "evidence_type": "INDEPENDENT_KNOWN_GOOD_NEW_OUTPUT",
        "evidence": {"task_id": "control", "status": "completed", "urls_count": 1},
    }
    cases = [
        ("missing", None, False),
        ("wrong_provider", {**fixed, "provider": "other"}, False),
        ("wrong_status", {**fixed, "status": "PENDING"}, False),
        ("fixed_deployment", fixed, True),
        ("known_good_new_output", known_good, True),
        ("known_good_without_url", {**known_good, "evidence": {"task_id": "control", "status": "completed", "urls_count": 0}}, False),
    ]
    results = []
    for name, signal, expected in cases:
        actual, reason = validate_signal(signal)
        results.append({"name": name, "expected": expected, "actual": actual, "reason": reason, "status": "PASS" if actual == expected else "FAIL"})
    return {
        "schema": "qingshan.e37.u08_s3_recovery_canary_guard_selftest.v1",
        "status": "PASS" if all(item["status"] == "PASS" for item in results) else "FAIL",
        "cases": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recovery-signal", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        result = self_test()
    else:
        signal = load_json(args.recovery_signal) if args.recovery_signal else None
        result = validate(signal)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] in {"PASS", "PASS_READY_FOR_SINGLE_SUBMISSION", "BLOCKED_CORRECTLY"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
