#!/usr/bin/env python3
"""Read-only exact-SHA/stat/inode verifier for the V46-V48 authority chain."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v49_authority_boundary_integrity/E40_U12_V49_AUTHORITY_BOUNDARY_SAFETY_INTEGRITY_MANIFEST.json"
MANIFEST_SHA = "4550939a4159e3244787a7acff15d320eb0344535343303524c8e4afae13246b"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve(raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(raw)
    result = (ROOT / path).resolve()
    result.relative_to(ROOT)
    return result


def fingerprint(path: Path) -> dict:
    stat = path.stat()
    return {"sha256": sha(path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "device": stat.st_dev, "inode": stat.st_ino}


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = resolve(args.out)
    if out.exists():
        raise SystemExit("OUT_OVERWRITE_FORBIDDEN")
    manifest = json.loads(MANIFEST.read_text())
    before = {}
    rows = []
    for binding in manifest["bindings"]:
        path = resolve(binding["path"])
        observed = fingerprint(path) if path.is_file() else None
        before[binding["path"]] = observed
        rows.append({"path": binding["path"], "expected_sha256": binding["sha256"], "actual_sha256": observed["sha256"] if observed else None, "status": "PASS" if observed and observed["sha256"] == binding["sha256"] else "FAIL"})
    after = {binding["path"]: fingerprint(resolve(binding["path"])) if resolve(binding["path"]).is_file() else None for binding in manifest["bindings"]}
    checks = {
        "manifest_sha_exact": sha(MANIFEST) == MANIFEST_SHA,
        "binding_count_13": len(rows) == manifest["binding_count"] == 13,
        "paths_unique": len({row["path"] for row in rows}) == 13,
        "bindings_13_of_13_exact": all(row["status"] == "PASS" for row in rows),
        "fingerprints_unchanged": before == after,
        "real_validation_forbidden": manifest.get("real_evidence_validation_authorized") is False,
        "positive_admission_forbidden": manifest.get("positive_admission_test_authorized") is False,
        "authority_admission_zero": manifest.get("authority_keys_admitted") == 0 and manifest.get("production_assets_admitted") == 0 and manifest.get("authorization") is False and manifest.get("maximum_new_submissions") == 0 and manifest.get("execution") is False,
    }
    passed = all(checks.values())
    report = {
        "schema": "qingshan.e40.u12.v49.authority_boundary_safety_integrity_gate.v1",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "PASS_13_OF_13_AUTHORITY_BOUNDARY_BINDINGS_EXACT_NO_MUTATION" if passed else "FAIL_CLOSED_AUTHORITY_BOUNDARY_SAFETY_INTEGRITY_MISMATCH",
        "manifest_sha256": sha(MANIFEST),
        "bindings": rows,
        "semantic_checks": checks,
        "binding_count": len(rows),
        "binding_pass_count": sum(row["status"] == "PASS" for row in rows),
        "failure_count": sum(not value for value in checks.values()),
        "fingerprints_before": before,
        "fingerprints_after": after,
        "fingerprints_unchanged": before == after,
        "real_evidence_validation_authorized": False,
        "positive_admission_test_authorized": False,
        "authority_keys_admitted": 0,
        "production_assets_admitted": 0,
        "authorization": False,
        "maximum_new_submissions": 0,
        "side_effects": {"provider_calls": 0, "transactions": 0, "credits": 0, "generation_actions": 0, "renders": 0, "agentcut_actions": 0, "assembly_actions": 0, "release_actions": 0, "browser_started": False, "platform_state_changed": False, "work_queue_changed": False, "e38_state_changed": False, "e39_state_changed": False},
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "bindings": f"{report['binding_pass_count']}/{report['binding_count']}", "failure_count": report["failure_count"]}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
