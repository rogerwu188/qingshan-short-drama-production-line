#!/usr/bin/env python3
"""Fail-closed static and mutation QA for the E40 U02 V2 image package."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = Path(
    "workflow/claude_writer_agent/production/"
    "e40_claude_writer_v3_140d4b7b_20260808/"
    "u02_v2_state_isolated_exact_start_frame_remediation_v1"
)
MANIFEST = ROOT / BASE / "E40_U02_V2_STATE_ISOLATED_IMAGE_MANIFEST_V1.json"
REPORT = ROOT / "qa/e40_preproduction_20260814/u02_v2_state_isolated_package_qa_v1/E40_U02_V2_STATE_ISOLATED_STATIC_AND_NEGATIVE_GATE_V1.json"

CANONICAL_SCRIPT_SHA = "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b"
CANONICAL_MANIFEST_SHA = "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1"
FAILED_V1_SHA = "6d05770f9f0324e540c1eb53f109072eae0b6510d1be99c748f0c8ee8c8e9fd6"
UNCROPPED_SCENE_SHA = "affcdf75edd4719b69b3fefad3cffb271c87794fdfc0cba029d8d26af6654b88"
UNCROPPED_CHARACTER_SHA = "6de74d90b959178ac773a63e0fe77875ba4cd9f5dd6553da9a3ca7c7276d416e"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(data: dict) -> list[str]:
    errors: list[str] = []
    task = (data.get("tasks") or [{}])[0]
    policy = data.get("submission_policy") or {}
    bindings = task.get("reference_bindings") or []
    prompt_path = ROOT / str(task.get("prompt_file", ""))
    prompt = prompt_path.read_text(encoding="utf-8") if prompt_path.is_file() else ""

    if data.get("canonical_script_sha256") != CANONICAL_SCRIPT_SHA:
        errors.append("CANONICAL_SCRIPT_SHA")
    if data.get("canonical_manifest_sha256") != CANONICAL_MANIFEST_SHA:
        errors.append("CANONICAL_MANIFEST_SHA")
    if task.get("task_key") != "E40-U02-EXACT-START-FRAME-V2-STATE-ISOLATED":
        errors.append("UNIQUE_V2_TASK_KEY")
    if task.get("prompt_sha256") != sha(prompt_path) if prompt_path.is_file() else True:
        errors.append("PROMPT_SHA")
    if task.get("paid_submission_allowed") is not False:
        errors.append("PAID_SUBMISSION_FAIL_CLOSED")
    if policy.get("provider_post_allowed") is not False or policy.get("maximum_new_submissions") != 0:
        errors.append("PROVIDER_POST_FAIL_CLOSED")
    if task.get("reference_images") != [row.get("path") for row in bindings]:
        errors.append("REFERENCE_ORDER")
    if len(bindings) != 2 or [row.get("role") for row in bindings] != ["scene", "character"]:
        errors.append("REFERENCE_ROLES")

    reference_shas: list[str] = []
    for row in bindings:
        path = ROOT / str(row.get("path", ""))
        if not path.is_file():
            errors.append("REFERENCE_MISSING")
            continue
        actual = sha(path)
        reference_shas.append(actual)
        if actual != row.get("sha256"):
            errors.append("REFERENCE_SHA")
        if row.get("qa_status") != "PASS":
            errors.append("REFERENCE_QA")
        provenance = row.get("crop_provenance") or {}
        source = ROOT / str(provenance.get("source_path", ""))
        if not source.is_file() or sha(source) != provenance.get("source_sha256"):
            errors.append("CROP_SOURCE_AUTHORITY")
        if not provenance.get("conflicting_state_excluded"):
            errors.append("CONFLICTING_STATE_EXCLUSION")

    if FAILED_V1_SHA in reference_shas:
        errors.append("FAILED_V1_REUSED")
    if UNCROPPED_SCENE_SHA in reference_shas or UNCROPPED_CHARACTER_SHA in reference_shas:
        errors.append("UNCROPPED_CONFLICTING_REFERENCE")

    required_prompt_terms = [
        "人物头部、脸、颈部、躯干和全身必须完全在画外",
        "扇面横向宽度不超过画面宽度28%",
        "帘下窄缝不超过画面高度2%",
        "手腕、扇柄、半合扇骨三者必须同帧可读",
    ]
    if any(term not in prompt for term in required_prompt_terms):
        errors.append("MEASURABLE_PROMPT_LOCK")
    if "PF-021" not in prompt:
        errors.append("FAILURE_MEMORY_BINDING")
    if task.get("failed_asset_exclusions") != [{"sha256": FAILED_V1_SHA}]:
        errors.append("FAILED_ASSET_EXCLUSION")
    return sorted(set(errors))


def main() -> int:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    canonical_errors = validate(data)
    mutations: list[tuple[str, dict]] = []

    def mutated(name: str, change) -> None:
        candidate = copy.deepcopy(data)
        change(candidate)
        mutations.append((name, candidate))

    mutated("FAILED_V1_REUSE", lambda d: d["tasks"][0]["reference_bindings"][1].update({"sha256": FAILED_V1_SHA}))
    mutated("UNCROPPED_CHARACTER_REFERENCE", lambda d: d["tasks"][0]["reference_bindings"][1].update({"path": "assets/reference/e40_wardrobe_variants_20260808/characters/CHAR-yunfei-E40-curtain-fan-silhouette-v1-20260809.png", "sha256": UNCROPPED_CHARACTER_SHA}))
    mutated("PAID_OPEN", lambda d: d["tasks"][0].update({"paid_submission_allowed": True}))
    mutated("PROVIDER_POST_OPEN", lambda d: d["submission_policy"].update({"provider_post_allowed": True, "maximum_new_submissions": 1}))
    mutated("V1_TASK_KEY_REPLAY", lambda d: d["tasks"][0].update({"task_key": "E40-U02-EXACT-START-FRAME-V1"}))
    mutated("CROP_PROVENANCE_REMOVED", lambda d: d["tasks"][0]["reference_bindings"][1].pop("crop_provenance", None))

    matrix = []
    for name, candidate in mutations:
        errors = validate(candidate)
        matrix.append({"case": name, "expected": "REJECT", "actual": "REJECT" if errors else "PASS", "reasons": errors})

    status = "PASS" if not canonical_errors and all(row["actual"] == "REJECT" for row in matrix) else "FAIL"
    report = {
        "schema": "qingshan.e40.u02.v2.state_isolated_static_and_negative_gate.v1",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": status,
        "manifest": str(MANIFEST.relative_to(ROOT)),
        "manifest_sha256": sha(MANIFEST),
        "canonical_errors": canonical_errors,
        "canonical_cases_passed": 1 if not canonical_errors else 0,
        "negative_cases_rejected": sum(row["actual"] == "REJECT" for row in matrix),
        "negative_case_count": len(matrix),
        "negative_matrix": matrix,
        "provider_calls": 0,
        "transactions": 0,
        "credits": 0,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "canonical_errors": canonical_errors, "negative_cases_rejected": report["negative_cases_rejected"]}, ensure_ascii=False))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
