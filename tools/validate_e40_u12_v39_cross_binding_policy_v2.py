#!/usr/bin/env python3
"""Synthetic-only negative validator for E40/U12 cross-binding policy V2."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / (
    "workflow/claude_writer_agent/production/"
    "e40_claude_writer_v3_140d4b7b_20260808/"
    "u12_v39_cross_binding_policy_v2/"
    "E40_U12_V39_FOUR_EVIDENCE_CROSS_BINDING_POLICY_V2.json"
)
POLICY_SHA256 = "1c5d8c15596e19ed66ed3417d4d21ad5068caed769df106cb42c91c81f83a536"
FIXTURES = ROOT / (
    "workflow/claude_writer_agent/production/"
    "e40_claude_writer_v3_140d4b7b_20260808/"
    "u12_v39_cross_binding_policy_v2/"
    "E40_U12_V39_SYNTHETIC_NEGATIVE_FIXTURE_MATRIX_V2.json"
)
FIXTURES_SHA256 = "475e62a170b2a142beaedb50ab7ba7c9eef9c0a2e13474ff5c65dbb4b891e3ec"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repo_path(raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"repo-relative path required: {raw}")
    resolved = (ROOT / path).resolve()
    resolved.relative_to(ROOT.resolve())
    return resolved


def parse_time(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def apply_overrides(bundle: dict, overrides: dict) -> dict:
    result = copy.deepcopy(bundle)
    for role, fields in overrides.items():
        result[role].update(fields)
    return result


def evaluate(bundle: dict, evaluation_time: datetime) -> list[dict]:
    roles = [
        "authority_request",
        "roger_authorization",
        "independent_signoff",
        "source_layer_gate",
    ]
    values = [bundle[role] for role in roles]
    request_shas = [value.get("authority_request_sha256") for value in values]
    targets = [
        (value.get("episode"), value.get("unit_id"), value.get("target_key"))
        for value in values
    ]
    source_shas = [value.get("source_package_sha256") for value in values]
    auths = [bundle["roger_authorization"], bundle["independent_signoff"]]
    nonces = [value.get("authorization_nonce") for value in auths]

    try:
        unexpired = all(
            parse_time(value["issued_at"])
            <= evaluation_time
            < parse_time(value["expires_at"])
            for value in auths
        )
    except (KeyError, TypeError, ValueError):
        unexpired = False

    checks = [
        (
            "ALL_FOUR_BIND_EXACT_SAME_AUTHORITY_REQUEST_SHA256",
            len(set(request_shas)) == 1
            and isinstance(request_shas[0], str)
            and bool(SHA256_RE.fullmatch(request_shas[0])),
            request_shas,
        ),
        (
            "ALL_FOUR_BIND_EXACT_SAME_EPISODE_UNIT_TARGET_KEY",
            len(set(targets)) == 1 and all(targets[0]),
            targets,
        ),
        (
            "ALL_FOUR_BIND_EXACT_SAME_SOURCE_PACKAGE_SHA256",
            len(set(source_shas)) == 1
            and isinstance(source_shas[0], str)
            and bool(SHA256_RE.fullmatch(source_shas[0])),
            source_shas,
        ),
        (
            "ROGER_AND_SIGNOFF_NONCES_ARE_DISTINCT_AND_NONEMPTY",
            all(isinstance(nonce, str) and nonce for nonce in nonces)
            and len(set(nonces)) == 2,
            nonces,
        ),
        (
            "ROGER_AND_SIGNOFF_AUTHORIZATIONS_ARE_UNEXPIRED",
            unexpired,
            {
                "evaluation_time": evaluation_time.isoformat(),
                "windows": [
                    {
                        "issued_at": value.get("issued_at"),
                        "expires_at": value.get("expires_at"),
                    }
                    for value in auths
                ],
            },
        ),
        (
            "ROGER_AND_SIGNOFF_AUTHORIZATIONS_ARE_UNCONSUMED",
            all(value.get("consumed_at") is None for value in auths),
            [value.get("consumed_at") for value in auths],
        ),
    ]
    return [
        {"check": name, "status": "PASS" if passed else "FAIL", "detail": detail}
        for name, passed, detail in checks
    ]


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = repo_path(args.out)
    if out.suffix != ".json":
        raise SystemExit("OUT_MUST_BE_JSON")
    if out.exists():
        raise SystemExit(f"OUT_OVERWRITE_FORBIDDEN:{out}")

    policy_before = sha256(POLICY)
    fixtures_before = sha256(FIXTURES)
    policy = json.loads(POLICY.read_text())
    fixtures = json.loads(FIXTURES.read_text())
    evaluation_time = parse_time(fixtures["evaluation_time"])
    case_rows = []
    for case in fixtures["cases"]:
        bundle = apply_overrides(fixtures["base_bundle"], case["overrides"])
        checks = evaluate(bundle, evaluation_time)
        failures = [check["check"] for check in checks if check["status"] == "FAIL"]
        expected = case["expected_failure"]
        case_rows.append(
            {
                "name": case["name"],
                "expected_failure": expected,
                "actual_failures": failures,
                "status": "PASS" if failures == [expected] else "FAIL",
                "checks": checks,
                "admission": False,
            }
        )

    policy_after = sha256(POLICY)
    fixtures_after = sha256(FIXTURES)
    pins_exact = (
        policy_before == policy_after == POLICY_SHA256
        and fixtures_before == fixtures_after == FIXTURES_SHA256
    )
    names = [case["name"] for case in fixtures["cases"]]
    expected_names = policy["required_negative_cases"]
    matrix_exact = (
        fixtures.get("synthetic_only") is True
        and fixtures.get("case_count") == len(case_rows) == 6
        and names == expected_names
        and all(row["status"] == "PASS" for row in case_rows)
    )
    passed = pins_exact and matrix_exact
    receipt = {
        "schema": "qingshan.e40.u12.v39.cross_binding_policy_v2_negative_gate.v1",
        "status": "PASS_6_OF_6_SYNTHETIC_NEGATIVES_REJECTED_NO_ADMISSION"
        if passed
        else "FAIL_CLOSED_V2_NEGATIVE_MATRIX_MISMATCH",
        "policy": str(POLICY.relative_to(ROOT)),
        "policy_expected_sha256": POLICY_SHA256,
        "policy_actual_sha256": policy_after,
        "fixtures": str(FIXTURES.relative_to(ROOT)),
        "fixtures_expected_sha256": FIXTURES_SHA256,
        "fixtures_actual_sha256": fixtures_after,
        "pinned_inputs_unchanged": policy_before == policy_after
        and fixtures_before == fixtures_after,
        "cases": case_rows,
        "case_count": len(case_rows),
        "pass_count": sum(row["status"] == "PASS" for row in case_rows),
        "failure_count": sum(row["status"] != "PASS" for row in case_rows)
        + (0 if pins_exact else 1),
        "synthetic_only": True,
        "authority_keys_admitted": 0,
        "production_assets_admitted": 0,
        "authorization": False,
        "maximum_new_submissions": 0,
        "execution": False,
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
                "cases": f"{receipt['pass_count']}/{receipt['case_count']}",
                "failure_count": receipt["failure_count"],
            }
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
