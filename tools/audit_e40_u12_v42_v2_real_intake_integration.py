#!/usr/bin/env python3
"""Pinned, read-only audit of V2 cross-binding integration into real intake."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v42_v2_intake_integration_gap_audit/E40_U12_V42_V2_REAL_INTAKE_INTEGRATION_GAP_AUDIT_SPEC.json"
SPEC_SHA256 = "16c18ee168e53c1d1130d51cddb38fed59495fbea668028a1955a00e50acc910"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repo_path(raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(raw)
    resolved = (ROOT / path).resolve()
    resolved.relative_to(ROOT.resolve())
    return resolved


def literals(source: str) -> set[str]:
    tree = ast.parse(source)
    return {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = repo_path(args.out)
    if out.suffix != ".json": raise SystemExit("OUT_MUST_BE_JSON")
    if out.exists(): raise SystemExit(f"OUT_OVERWRITE_FORBIDDEN:{out}")

    spec = json.loads(SPEC.read_text())
    rows=[]; payloads={}; before={}
    for item in spec["pinned_inputs"]:
        path=repo_path(item["path"]); actual=sha256(path) if path.is_file() else None
        before[item["role"]]=actual; payloads[item["role"]]=path.read_text() if path.is_file() else ""
        rows.append({"role":item["role"],"path":item["path"],"expected_sha256":item["sha256"],"actual_sha256":actual,"status":"PASS" if actual==item["sha256"] else "FAIL"})
    real_source=payloads["V35_REAL_INTAKE_VALIDATOR"]
    synthetic_source=payloads["V39_SYNTHETIC_VALIDATOR"]
    invoker_source=payloads["V40_PINNED_INVOKER"]
    real_literals=literals(real_source); synthetic_literals=literals(synthetic_source); invoker_literals=literals(invoker_source)

    common_keys={"authority_request_sha256","episode","unit_id","target_key","source_package_sha256"}
    replay_keys={"authorization_nonce","issued_at","expires_at","consumed_at"}
    v39_validator_name="validate_e40_u12_v39_cross_binding_policy_v2.py"
    checks=[
        {"check":"REAL_INTAKE_CALLS_V2_CROSS_BINDING_VALIDATOR","present":v39_validator_name in real_source,"evidence":{"v39_validator_name_in_real_source":v39_validator_name in real_source}},
        {"check":"REAL_INTAKE_SCHEMA_REQUIRES_COMMON_BINDINGS","present":common_keys.issubset(real_literals),"evidence":{"required":sorted(common_keys),"matched":sorted(common_keys & real_literals),"v2_matched":sorted(common_keys & synthetic_literals)}},
        {"check":"REAL_INTAKE_REJECTS_REPLAY_CONTROLS","present":replay_keys.issubset(real_literals),"evidence":{"required":sorted(replay_keys),"matched":sorted(replay_keys & real_literals),"v2_matched":sorted(replay_keys & synthetic_literals)}},
        {"check":"V40_ACCEPTS_REAL_BUNDLE_INPUT","present":"--bundle" in invoker_literals,"evidence":{"invoker_cli_literals":sorted(x for x in invoker_literals if x.startswith('--'))}},
    ]
    after={item["role"]:sha256(repo_path(item["path"])) if repo_path(item["path"]).is_file() else None for item in spec["pinned_inputs"]}
    pins_exact=sha256(SPEC)==SPEC_SHA256 and all(row["status"]=="PASS" for row in rows)
    unchanged=before==after; present=sum(x["present"] for x in checks); missing=len(checks)-present
    audit_valid=pins_exact and unchanged and len(checks)==4
    receipt={
        "schema":"qingshan.e40.u12.v42.v2_real_intake_integration_gap_gate.v1",
        "recorded_at":datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),
        "status":"PASS_AUDIT_4_OF_4_REAL_INTAKE_INTEGRATION_CHECKS_MISSING_FAIL_CLOSED" if audit_valid and missing==4 else "FAIL_CLOSED_REAL_INTAKE_INTEGRATION_AUDIT_INDETERMINATE",
        "spec":str(SPEC.relative_to(ROOT)),"spec_expected_sha256":SPEC_SHA256,"spec_actual_sha256":sha256(SPEC),
        "pinned_inputs":rows,"pinned_inputs_unchanged":unchanged,"checks":checks,"check_count":len(checks),"checks_present":present,"checks_missing":missing,"audit_failure_count":0 if audit_valid else 1,
        "admission_decision":"FAIL_CLOSED_V2_NOT_INTEGRATED_IN_REAL_INTAKE","authority_keys_admitted":0,"production_assets_admitted":0,"authorization":False,"maximum_new_submissions":0,
        "side_effects":{"provider_calls":0,"transactions":0,"credits":0,"generation_actions":0,"renders":0,"agentcut_actions":0,"assembly_actions":0,"release_actions":0,"browser_started":False,"platform_state_changed":False,"work_queue_changed":False,"e38_state_changed":False,"e39_state_changed":False}
    }
    out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({"status":receipt["status"],"present":present,"missing":missing,"audit_failure_count":receipt["audit_failure_count"]}))
    return 0 if audit_valid and missing==4 else 1


if __name__ == "__main__": raise SystemExit(main())
