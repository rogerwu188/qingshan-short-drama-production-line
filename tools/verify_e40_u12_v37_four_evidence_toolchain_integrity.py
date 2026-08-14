#!/usr/bin/env python3
"""Read-only verifier for the E40/U12 V35/V36 four-evidence toolchain."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / (
    "workflow/claude_writer_agent/production/"
    "e40_claude_writer_v3_140d4b7b_20260808/"
    "u12_v37_four_evidence_toolchain_integrity/"
    "E40_U12_V37_FOUR_EVIDENCE_TOOLCHAIN_INTEGRITY_MANIFEST.json"
)
MANIFEST_SHA256 = "879c24ba1176e50583477e4f5425433b8a750e0c1f418cb560f535b3077f1bb3"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repo_path(raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"repo-relative path required: {raw}")
    resolved = (ROOT / path).resolve()
    resolved.relative_to(ROOT.resolve())
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = repo_path(args.out)
    if out.suffix != ".json":
        raise SystemExit("OUT_MUST_BE_JSON")
    if out.exists():
        raise SystemExit(f"OUT_OVERWRITE_FORBIDDEN:{out}")

    manifest_actual_sha = sha256(MANIFEST)
    manifest = json.loads(MANIFEST.read_text())
    rows = []
    before = {}
    for binding in manifest.get("bindings") or []:
        role = binding.get("role")
        raw_path = binding.get("path") or ""
        try:
            path = repo_path(raw_path)
            actual = sha256(path) if path.is_file() else None
        except (ValueError, OSError):
            actual = None
        before[role] = actual
        rows.append(
            {
                "role": role,
                "path": raw_path,
                "expected_sha256": binding.get("sha256"),
                "actual_sha256": actual,
                "status": "PASS" if actual == binding.get("sha256") else "FAIL",
            }
        )

    after = {}
    for binding in manifest.get("bindings") or []:
        role = binding.get("role")
        try:
            path = repo_path(binding.get("path") or "")
            actual = sha256(path) if path.is_file() else None
        except (ValueError, OSError):
            actual = None
        after[role] = actual

    semantic_checks = {
        "manifest_sha_exact": manifest_actual_sha == MANIFEST_SHA256,
        "manifest_schema_exact": manifest.get("schema")
        == "qingshan.e40.u12.v37.four_evidence_toolchain_integrity_manifest.v1",
        "binding_count_9": len(rows) == manifest.get("binding_count") == 9,
        "binding_roles_unique": len({row["role"] for row in rows}) == len(rows),
        "bindings_9_of_9_exact": all(row["status"] == "PASS" for row in rows),
        "bindings_unchanged_during_verification": before == after,
        "admission_remains_zero": manifest.get("authority_keys_admitted") == 0
        and manifest.get("production_assets_admitted") == 0,
        "execution_remains_closed": manifest.get("authorization") is False
        and manifest.get("maximum_new_submissions") == 0
        and manifest.get("execution") is False,
    }
    passed = all(semantic_checks.values())
    receipt = {
        "schema": "qingshan.e40.u12.v37.four_evidence_toolchain_integrity_gate.v1",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "PASS_9_OF_9_EXACT_SHA_NO_MUTATION"
        if passed
        else "FAIL_CLOSED_FOUR_EVIDENCE_TOOLCHAIN_INTEGRITY_MISMATCH",
        "manifest": str(MANIFEST.relative_to(ROOT)),
        "manifest_expected_sha256": MANIFEST_SHA256,
        "manifest_actual_sha256": manifest_actual_sha,
        "bindings": rows,
        "semantic_checks": semantic_checks,
        "binding_count": len(rows),
        "binding_pass_count": sum(row["status"] == "PASS" for row in rows),
        "failure_count": sum(not value for value in semantic_checks.values()),
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
                "bindings": f"{receipt['binding_pass_count']}/{len(rows)}",
                "failure_count": receipt["failure_count"],
            }
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
