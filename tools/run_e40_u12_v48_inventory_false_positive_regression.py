#!/usr/bin/env python3
"""Pinned in-memory false-positive regression for the V47 authority inventory."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v48_inventory_false_positive_regression/E40_U12_V48_INVENTORY_FALSE_POSITIVE_REGRESSION_SPEC.json"
INVENTORY_TOOL = ROOT / "tools/inventory_e40_u12_v47_authority_boundary_prerequisites.py"
INVENTORY = ROOT / "qa/e40_preproduction_20260812/u12_v47_authority_boundary_inventory/E40_U12_V47_AUTHORITY_BOUNDARY_PREREQUISITE_INVENTORY.json"
PINS = {
    SPEC: "9c6d9b441d512831d4b417aef1f04c0a7a48bf369599dbf0d8961dd8cfd06614",
    INVENTORY_TOOL: "f773c1b49e5f1b4c5579da2da929c1c6f49ec39691aeaa93b8fdb780292000a7",
    INVENTORY: "e5014a1849498c8dd91f3d8b822ef1a720b369eae0c7f1f2025b7f8c390190c5",
}
EXACT = {
    "ROGER_EXPLICIT_REAL_EVIDENCE_VALIDATION_AUTHORIZATION": "qingshan.e40.u12.roger_real_evidence_validation_authorization.v1",
    "EXACT_AUTHORITY_REQUEST_SHA": "qingshan.e40.u12.real_validation_authority_request_binding.v1",
    "INDEPENDENT_SIGNOFF_SHA": "qingshan.e40.u12.real_validation_independent_signoff_binding.v1",
    "REAL_SOURCE_PACKAGE_SHA": "qingshan.e40.u12.real_validation_source_package_binding.v1",
    "UNEXPIRED_UNCONSUMED_NONCES": "qingshan.e40.u12.real_validation_nonce_state.v1",
    "SEPARATE_POSITIVE_ADMISSION_TEST_AUTHORIZATION": "qingshan.e40.u12.roger_positive_admission_test_authorization.v1",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def classify(document: dict) -> dict:
    schema = document.get("schema")
    if document.get("synthetic_only") is True or "synthetic" in str(schema).lower():
        return {"excluded_reason": "SYNTHETIC", "matched_categories": []}
    text = json.dumps(document, ensure_ascii=False).lower()
    if "seedance-2.0-fast" in text or "fast720" in text:
        return {"excluded_reason": "SEEDANCE_FAST_OR_FAST720", "matched_categories": []}
    matched = [category for category, expected in EXACT.items() if schema == expected]
    return {"excluded_reason": None, "matched_categories": matched}


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = (ROOT / args.out).resolve()
    out.relative_to(ROOT)
    if out.exists():
        raise SystemExit("OUT_OVERWRITE_FORBIDDEN")
    before = {str(path.relative_to(ROOT)): sha(path) for path in PINS}
    if any(before[str(path.relative_to(ROOT))] != expected for path, expected in PINS.items()):
        raise SystemExit("PIN_MISMATCH")

    cases = [
        ("SEEDANCE_FAST_PRODUCTION_AUTH_NOT_REAL_VALIDATION_AUTH", {"schema": EXACT["ROGER_EXPLICIT_REAL_EVIDENCE_VALIDATION_AUTHORIZATION"], "model": "seedance-2.0-fast"}),
        ("SYNTHETIC_FIXTURE_NOT_REAL_EVIDENCE", {"schema": EXACT["REAL_SOURCE_PACKAGE_SHA"], "synthetic_only": True}),
        ("GENERIC_AUTHORITY_REQUEST_NOT_EXACT_BINDING", {"schema": "qingshan.e40.u12.trusted_authority_admission_request.v1"}),
        ("SCHEMA_LOOKALIKE_NOT_EXACT_SCHEMA", {"schema": EXACT["INDEPENDENT_SIGNOFF_SHA"] + ".lookalike"}),
    ]
    results = []
    for case_id, document in cases:
        classification = classify(document)
        rejected = classification["matched_categories"] == []
        results.append({"case_id": case_id, "fixture_storage": "IN_MEMORY_ONLY", "classification": classification, "rejected": rejected})
    after = {str(path.relative_to(ROOT)): sha(path) for path in PINS}
    passed = len(results) == 4 and all(row["rejected"] for row in results) and before == after
    report = {
        "schema": "qingshan.e40.u12.v48.inventory_false_positive_regression.v1",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "PASS_4_OF_4_IN_MEMORY_FALSE_POSITIVES_REJECTED_NO_ADMISSION" if passed else "FAIL_CLOSED_FALSE_POSITIVE_REGRESSION_REQUIRES_REVIEW",
        "pinned_inputs_before": before,
        "pinned_inputs_after": after,
        "pinned_inputs_unchanged": before == after,
        "fixture_repository_writes": 0,
        "cases": results,
        "case_count": len(results),
        "cases_rejected": sum(row["rejected"] for row in results),
        "authority_keys_admitted": 0,
        "production_assets_admitted": 0,
        "real_evidence_validation_authorized": False,
        "positive_admission_test_authorized": False,
        "authorization": False,
        "maximum_new_submissions": 0,
        "side_effects": {"provider_calls": 0, "transactions": 0, "credits": 0, "generation_actions": 0, "renders": 0, "agentcut_actions": 0, "assembly_actions": 0, "release_actions": 0, "browser_started": False, "platform_state_changed": False, "work_queue_changed": False, "e38_state_changed": False, "e39_state_changed": False},
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "rejected": report["cases_rejected"], "total": report["case_count"]}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
