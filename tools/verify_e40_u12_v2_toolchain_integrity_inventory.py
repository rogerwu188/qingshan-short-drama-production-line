#!/usr/bin/env python3
"""Read-only exact-SHA verifier for the E40/U12 V2 hardening toolchain."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v32_v2_toolchain_integrity_v1/E40_U12_V32_V2_TOOLCHAIN_INTEGRITY_INVENTORY_V1.json"
INVENTORY_SHA256 = "be91c2389aa739bcc6c4160fd0490fed5ec6e6be93059924598072a3a501c506"


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
    inventory_actual_sha = sha256(INVENTORY)
    inventory = json.loads(INVENTORY.read_text())
    items = inventory.get("files") or []
    paths = [item.get("path") for item in items]
    rows = []
    before = {}
    for item in items:
        path = repo_path(item["path"])
        actual = sha256(path) if path.is_file() else None
        before[item["path"]] = actual
        rows.append(
            {
                "path": item["path"],
                "expected_sha256": item["sha256"],
                "actual_sha256": actual,
                "status": "PASS" if actual == item["sha256"] else "FAIL",
            }
        )
    after = {
        item["path"]: sha256(repo_path(item["path"])) if repo_path(item["path"]).is_file() else None
        for item in items
    }
    failures = [row for row in rows if row["status"] == "FAIL"]
    expected_count = inventory.get("expected_file_count")
    passed = all(
        [
            inventory_actual_sha == INVENTORY_SHA256,
            len(items) == expected_count == 18,
            len(set(paths)) == len(paths),
            not failures,
            before == after,
        ]
    )
    receipt = {
        "schema": "qingshan.e40.u12.v32.v2_toolchain_integrity_gate.v1",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "PASS_18_OF_18_EXACT_SHA_NO_MUTATION" if passed else "FAIL_CLOSED_V2_TOOLCHAIN_INTEGRITY_MISMATCH",
        "inventory": str(INVENTORY.relative_to(ROOT)),
        "inventory_expected_sha256": INVENTORY_SHA256,
        "inventory_actual_sha256": inventory_actual_sha,
        "expected_file_count": expected_count,
        "actual_file_count": len(items),
        "unique_path_count": len(set(paths)),
        "pass_count": len(rows) - len(failures),
        "failure_count": len(failures),
        "files": rows,
        "files_unchanged_during_verification": before == after,
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
    print(json.dumps({"status": receipt["status"], "passed": f"{receipt['pass_count']}/{len(rows)}", "unchanged": before == after}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
