#!/usr/bin/env python3
"""Pinned read-only audit of E40/U12 four-evidence cross-binding controls."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / (
    "workflow/claude_writer_agent/production/"
    "e40_claude_writer_v3_140d4b7b_20260808/"
    "u12_v38_four_evidence_cross_binding_audit/"
    "E40_U12_V38_FOUR_EVIDENCE_CROSS_BINDING_REPLAY_AUDIT_SPEC.json"
)
SPEC_SHA256 = "9f6ab9ca1e1ddcd17977c413a7aea4bb11e371af53f4e1ee7837d33ab2bab295"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repo_path(raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"repo-relative path required: {raw}")
    resolved = (ROOT / path).resolve()
    resolved.relative_to(ROOT.resolve())
    return resolved


def string_literals(tree: ast.AST) -> set[str]:
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = repo_path(args.out)
    if out.suffix != ".json":
        raise SystemExit("OUT_MUST_BE_JSON")
    if out.exists():
        raise SystemExit(f"OUT_OVERWRITE_FORBIDDEN:{out}")

    spec = json.loads(SPEC.read_text())
    pinned_rows = []
    payloads: dict[str, str] = {}
    before = {}
    for item in spec["pinned_inputs"]:
        path = repo_path(item["path"])
        actual = sha256(path) if path.is_file() else None
        before[item["role"]] = actual
        payloads[item["role"]] = path.read_text() if path.is_file() else ""
        pinned_rows.append(
            {
                "role": item["role"],
                "path": item["path"],
                "expected_sha256": item["sha256"],
                "actual_sha256": actual,
                "status": "PASS" if actual == item["sha256"] else "FAIL",
            }
        )

    validator_source = payloads["V35_VALIDATOR"]
    validator_tree = ast.parse(validator_source)
    literals = string_literals(validator_tree)
    contract = json.loads(payloads["V35_CONTRACT"])
    contract_text = json.dumps(contract, sort_keys=True)

    request_sha_keys = {
        "authority_request_sha256",
        "request_sha256",
        "authority_request_sha",
    }
    target_keys = {"episode", "unit_id", "target_key"}
    source_keys = {"source_package_sha256", "source_layer_package_sha256"}
    replay_keys = {"nonce", "expires_at", "expiration", "used_at", "consumed_at"}

    request_sha_reference_present = bool(request_sha_keys & literals)
    target_reference_present = target_keys.issubset(literals)
    source_sha_reference_present = bool(source_keys & literals)
    replay_reference_present = bool(replay_keys & literals)

    controls = [
        {
            "control": "ROGER_AUTHORIZATION_BINDS_EXACT_AUTHORITY_REQUEST_SHA",
            "present": request_sha_reference_present,
            "evidence": {
                "required_any_literal": sorted(request_sha_keys),
                "matched_literals": sorted(request_sha_keys & literals),
                "contract_declares_binding": "authority_request_sha" in contract_text,
            },
        },
        {
            "control": "INDEPENDENT_SIGNOFF_BINDS_EXACT_AUTHORITY_REQUEST_SHA",
            "present": request_sha_reference_present,
            "evidence": {
                "required_any_literal": sorted(request_sha_keys),
                "matched_literals": sorted(request_sha_keys & literals),
                "contract_declares_binding": "authority_request_sha" in contract_text,
            },
        },
        {
            "control": "SOURCE_LAYER_GATE_BINDS_EXACT_AUTHORITY_REQUEST_SHA",
            "present": request_sha_reference_present,
            "evidence": {
                "required_any_literal": sorted(request_sha_keys),
                "matched_literals": sorted(request_sha_keys & literals),
                "contract_declares_binding": "authority_request_sha" in contract_text,
            },
        },
        {
            "control": "ALL_FOUR_BIND_SAME_EPISODE_UNIT_TARGET_KEY",
            "present": target_reference_present,
            "evidence": {
                "required_all_literals": sorted(target_keys),
                "matched_literals": sorted(target_keys & literals),
                "contract_declares_target_binding": all(key in contract_text for key in target_keys),
            },
        },
        {
            "control": "ALL_FOUR_BIND_SAME_SOURCE_PACKAGE_SHA",
            "present": source_sha_reference_present,
            "evidence": {
                "required_any_literal": sorted(source_keys),
                "matched_literals": sorted(source_keys & literals),
                "contract_declares_source_binding": any(key in contract_text for key in source_keys),
            },
        },
        {
            "control": "AUTHORIZATIONS_ARE_NON_REPLAYABLE_AND_NOT_EXPIRED",
            "present": replay_reference_present,
            "evidence": {
                "required_replay_or_expiry_literals": sorted(replay_keys),
                "matched_literals": sorted(replay_keys & literals),
                "contract_declares_replay_or_expiry": any(key in contract_text for key in replay_keys),
            },
        },
    ]

    after = {
        item["role"]: sha256(repo_path(item["path"]))
        if repo_path(item["path"]).is_file()
        else None
        for item in spec["pinned_inputs"]
    }
    pins_exact = sha256(SPEC) == SPEC_SHA256 and all(
        row["status"] == "PASS" for row in pinned_rows
    )
    inputs_unchanged = before == after
    present_count = sum(item["present"] for item in controls)
    missing_count = len(controls) - present_count
    audit_pass = pins_exact and inputs_unchanged and len(controls) == 6
    receipt = {
        "schema": "qingshan.e40.u12.v38.four_evidence_cross_binding_replay_audit_gate.v1",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "PASS_AUDIT_6_OF_6_CONTROLS_MISSING_FAIL_CLOSED"
        if audit_pass and missing_count == 6
        else "FAIL_CLOSED_CROSS_BINDING_AUDIT_INDETERMINATE",
        "spec": str(SPEC.relative_to(ROOT)),
        "spec_expected_sha256": SPEC_SHA256,
        "spec_actual_sha256": sha256(SPEC),
        "pinned_inputs": pinned_rows,
        "pinned_inputs_unchanged": inputs_unchanged,
        "controls": controls,
        "control_count": len(controls),
        "controls_present": present_count,
        "controls_missing": missing_count,
        "audit_failure_count": 0 if audit_pass else 1,
        "admission_decision": "FAIL_CLOSED_NO_AUTHORITY_KEY_OR_SOURCE_ADMISSION",
        "authority_keys_admitted": 0,
        "production_assets_admitted": 0,
        "authorization": False,
        "maximum_new_submissions": 0,
        "side_effects": {
            "provider_calls": 0,
            "transactions": 0,
            "credits": 0,
            "generation_actions": 0,
            "renders": 0,
            "agentcut_actions": 0,
            "assembly_actions": 0,
            "release_actions": 0,
            "browser_started": False,
            "platform_state_changed": False,
            "work_queue_changed": False,
            "e38_state_changed": False,
            "e39_state_changed": False,
        },
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "controls_present": present_count,
                "controls_missing": missing_count,
                "audit_failure_count": receipt["audit_failure_count"],
            }
        )
    )
    return 0 if audit_pass and missing_count == 6 else 1


if __name__ == "__main__":
    raise SystemExit(main())
