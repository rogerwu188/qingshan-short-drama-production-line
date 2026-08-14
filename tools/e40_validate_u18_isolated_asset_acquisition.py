#!/usr/bin/env python3
"""Validate U18 isolated-asset acquisition planning without submitting anything."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/keyframe_precompile/u18_isolated_asset_acquisition_v1/E40_U18_ISOLATED_ASSET_ACQUISITION_NO_SUBMIT_MANIFEST_V1.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    failures: list[str] = []
    if data["status"] != "PRECOMPILED_NO_SUBMIT":
        failures.append("STATUS_NOT_NO_SUBMIT")
    if data["execution_gate"] != {
        "authorization": False,
        "provider_post_allowed": False,
        "transaction_creation_allowed": False,
        "paid_submission_allowed": False,
        "maximum_new_submissions": 0,
    }:
        failures.append("EXECUTION_GATE_NOT_FAIL_CLOSED")

    required_phrases = {
        "E40-U18-ISO-TORN-CURTAIN-SOURCE-V1": [
            "one isolated photoreal",
            "irregular arrow-sized tear",
            "no rectangular patches",
            "newly isolated source representation",
        ],
        "E40-U18-ISO-LOW-AXIS-ARROW-V1": [
            "one isolated photoreal",
            "exactly one",
            "arrowhead is on the left",
            "newly isolated source representation",
        ],
    }
    for asset in data["assets"]:
        path = ROOT / asset["prompt_path"]
        if not path.is_file():
            failures.append(f"{asset['asset_id']}:PROMPT_MISSING")
            continue
        if sha(path) != asset["prompt_sha256"]:
            failures.append(f"{asset['asset_id']}:PROMPT_SHA_MISMATCH")
        prompt = path.read_text(encoding="utf-8").lower()
        for phrase in required_phrases[asset["asset_id"]]:
            if phrase not in prompt:
                failures.append(f"{asset['asset_id']}:CLAUSE_MISSING:{phrase}")
        if asset["output_path"] is not None or asset["output_sha256"] is not None:
            failures.append(f"{asset['asset_id']}:UNAUTHORIZED_OUTPUT_BOUND")

    result = {
        "schema": "qingshan.e40.u18.isolated_asset_acquisition_validation.v1",
        "status": "PASS_2_OF_2_PROMPTS_SHA_BOUND_CHANGED_REPRESENTATION_NO_SUBMIT" if not failures else "FAIL_CLOSED",
        "manifest_sha256": sha(MANIFEST),
        "failures": failures,
        "provider_calls": 0,
        "transactions": 0,
        "credits": 0,
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
