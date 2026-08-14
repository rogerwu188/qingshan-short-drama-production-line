#!/usr/bin/env python3
"""Read-only verifier for E40/U12 V38-V40 cross-binding hardening."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v41_cross_binding_hardening_integrity/E40_U12_V41_CROSS_BINDING_HARDENING_INTEGRITY_MANIFEST.json"
MANIFEST_SHA256 = "b1eb6b1edd9fad78cc0de634b7b19ce33b41516101a3b1f3624ac2574ab9e632"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repo_path(raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(raw)
    resolved = (ROOT / path).resolve()
    resolved.relative_to(ROOT.resolve())
    return resolved


def fingerprint(path: Path) -> dict:
    stat = path.stat()
    return {
        "sha256": sha256(path),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "device": stat.st_dev,
        "inode": stat.st_ino,
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

    manifest_actual = sha256(MANIFEST)
    manifest = json.loads(MANIFEST.read_text())
    before = {}
    rows = []
    for binding in manifest.get("bindings") or []:
        path = repo_path(binding["path"])
        actual = fingerprint(path) if path.is_file() else None
        before[binding["role"]] = actual
        rows.append({
            "role": binding["role"],
            "path": binding["path"],
            "expected_sha256": binding["sha256"],
            "actual_sha256": actual["sha256"] if actual else None,
            "status": "PASS" if actual and actual["sha256"] == binding["sha256"] else "FAIL",
        })
    after = {
        binding["role"]: fingerprint(repo_path(binding["path"]))
        if repo_path(binding["path"]).is_file() else None
        for binding in manifest.get("bindings") or []
    }
    checks = {
        "manifest_sha_exact": manifest_actual == MANIFEST_SHA256,
        "manifest_schema_exact": manifest.get("schema") == "qingshan.e40.u12.v41.cross_binding_hardening_integrity_manifest.v1",
        "binding_count_13": len(rows) == manifest.get("binding_count") == 13,
        "binding_roles_unique": len({row["role"] for row in rows}) == len(rows),
        "bindings_13_of_13_exact": all(row["status"] == "PASS" for row in rows),
        "bindings_unchanged_during_verification": before == after,
        "admission_remains_zero": manifest.get("authority_keys_admitted") == 0 and manifest.get("production_assets_admitted") == 0,
        "execution_remains_closed": manifest.get("authorization") is False and manifest.get("maximum_new_submissions") == 0 and manifest.get("execution") is False,
    }
    passed = all(checks.values())
    receipt = {
        "schema": "qingshan.e40.u12.v41.cross_binding_hardening_integrity_gate.v1",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "PASS_13_OF_13_EXACT_SHA_NO_MUTATION" if passed else "FAIL_CLOSED_CROSS_BINDING_HARDENING_INTEGRITY_MISMATCH",
        "manifest": str(MANIFEST.relative_to(ROOT)),
        "manifest_expected_sha256": MANIFEST_SHA256,
        "manifest_actual_sha256": manifest_actual,
        "bindings": rows,
        "semantic_checks": checks,
        "binding_count": len(rows),
        "binding_pass_count": sum(row["status"] == "PASS" for row in rows),
        "failure_count": sum(not value for value in checks.values()),
        "fingerprints_unchanged": before == after,
        "authority_keys_admitted": 0,
        "production_assets_admitted": 0,
        "authorization": False,
        "maximum_new_submissions": 0,
        "side_effects": {"provider_calls":0,"transactions":0,"credits":0,"generation_actions":0,"renders":0,"agentcut_actions":0,"assembly_actions":0,"release_actions":0,"browser_started":False,"platform_state_changed":False,"work_queue_changed":False,"e38_state_changed":False,"e39_state_changed":False},
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status":receipt["status"],"bindings":f"{receipt['binding_pass_count']}/{receipt['binding_count']}","failure_count":receipt["failure_count"]}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
