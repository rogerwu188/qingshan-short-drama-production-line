#!/usr/bin/env python3
"""Read-only verifier for the combined E40/U12 source-authority manifest V3."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v33_integrity_manifest_v3/E40_U12_V33_SOURCE_AUTHORITY_INTEGRITY_MANIFEST_V3_CONTRACT.json"
CONTRACT_SHA256 = "127485306e9556c58d6acb80b17cc77997e84798b03403eb9876b3db72cd0708"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repo_path(raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"repo-relative path required: {raw}")
    resolved = (ROOT / path).resolve()
    resolved.relative_to(ROOT)
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = repo_path(args.out)
    contract_actual_sha = sha256(CONTRACT)
    contract = json.loads(CONTRACT.read_text())
    rows = []
    before = {}
    payloads = {}
    for binding in contract["bindings"]:
        path = repo_path(binding["path"])
        actual = sha256(path) if path.is_file() else None
        before[binding["role"]] = actual
        payloads[binding["role"]] = json.loads(path.read_text()) if path.is_file() else None
        rows.append({
            "role": binding["role"],
            "path": binding["path"],
            "expected_sha256": binding["sha256"],
            "actual_sha256": actual,
            "status": "PASS" if actual == binding["sha256"] else "FAIL",
        })
    after = {
        binding["role"]: sha256(repo_path(binding["path"]))
        if repo_path(binding["path"]).is_file() else None
        for binding in contract["bindings"]
    }
    v21_gate = payloads["V21_INTEGRITY_GATE"]
    v32_inventory = payloads["V32_V2_TOOLCHAIN_INVENTORY"]
    v32_gate = payloads["V32_V2_TOOLCHAIN_GATE"]
    semantic_checks = {
        "binding_count": len(rows) == contract["expected_binding_count"] == 6,
        "binding_roles_unique": len({row["role"] for row in rows}) == len(rows),
        "binding_shas_exact": all(row["status"] == "PASS" for row in rows),
        "v21_status_pass": v21_gate.get("status") == "PASS_CURRENT_AND_HISTORICAL_INTEGRITY_NO_UNARCHIVED_DRIFT",
        "v21_current_25_of_25": v21_gate.get("current_file_count") == v21_gate.get("current_pass_count") == contract["expected_v21_current_files"] == 25,
        "v21_additional_3_of_3": v21_gate.get("additional_file_count") == v21_gate.get("additional_pass_count") == contract["expected_v21_additional_files"] == 3,
        "v21_unarchived_drift_zero": v21_gate.get("unarchived_historical_drift_count") == contract["expected_unarchived_historical_drift"] == 0,
        "v21_failure_count_zero": v21_gate.get("failure_count") == 0,
        "v32_inventory_18": v32_inventory.get("expected_file_count") == len(v32_inventory.get("files") or []) == contract["expected_v32_files"] == 18,
        "v32_gate_status_pass": v32_gate.get("status") == "PASS_18_OF_18_EXACT_SHA_NO_MUTATION",
        "v32_gate_18_of_18": v32_gate.get("actual_file_count") == v32_gate.get("pass_count") == contract["expected_v32_files"] == 18,
        "v32_failure_count_zero": v32_gate.get("failure_count") == 0,
        "bindings_unchanged_during_verification": before == after,
    }
    passed = contract_actual_sha == CONTRACT_SHA256 and all(semantic_checks.values())
    receipt = {
        "schema": "qingshan.e40.u12.v33.source_authority_integrity_gate.v3",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "PASS_V21_25_PLUS_3_V32_18_DRIFT0_NO_MUTATION" if passed else "FAIL_CLOSED_INTEGRITY_V3_MISMATCH",
        "contract": str(CONTRACT.relative_to(ROOT)),
        "contract_expected_sha256": CONTRACT_SHA256,
        "contract_actual_sha256": contract_actual_sha,
        "bindings": rows,
        "semantic_checks": semantic_checks,
        "binding_count": len(rows),
        "binding_pass_count": sum(row["status"] == "PASS" for row in rows),
        "failure_count": sum(not value for value in semantic_checks.values()) + (contract_actual_sha != CONTRACT_SHA256),
        "authorization": False,
        "maximum_new_submissions": 0,
        "side_effects": {
            "provider_calls": 0, "transactions": 0, "credits": 0,
            "generation_actions": 0, "renders": 0, "agentcut_actions": 0,
            "assembly_actions": 0, "release_actions": 0,
            "browser_started": False, "platform_state_changed": False,
            "work_queue_changed": False, "e38_state_changed": False,
            "e39_state_changed": False
        }
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": receipt["status"], "bindings": f"{receipt['binding_pass_count']}/{len(rows)}", "failure_count": receipt["failure_count"]}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
