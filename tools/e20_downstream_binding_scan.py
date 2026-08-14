#!/usr/bin/env python3
"""Scan E20 downstream JSON contracts for stale or missing script bindings."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


STRUCTURAL_KEYS = {
    "dialogue_count",
    "unit_count",
    "units",
    "beats",
    "beat_coverage",
    "dialogue_coverage",
}


def scan(config_dir: Path, beat_sheet: Path) -> dict:
    current_sha = hashlib.sha256(beat_sheet.read_bytes()).hexdigest()
    rows = []
    failures = []
    for path in sorted(config_dir.glob("e20_*.json")):
        if "dialogue_beat_sheet" in path.name:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not STRUCTURAL_KEYS.intersection(payload):
            continue
        status = str(payload.get("status", ""))
        bound_sha = payload.get("beat_sheet_sha256")
        if bound_sha == current_sha:
            classification = "CURRENT_SHA_BOUND"
        elif status.startswith("STALE_") or payload.get("superseded_by"):
            classification = "STALE_EXPLICIT"
        else:
            classification = "FAIL_UNBOUND_OR_MISMATCHED_ACTIVE_CONTRACT"
            failures.append(str(path.resolve()))
        rows.append(
            {
                "path": str(path.resolve()),
                "status": status,
                "beat_sheet_sha256": bound_sha,
                "classification": classification,
            }
        )
    return {
        "schema": "qingshan.e20_downstream_binding_scan.v1",
        "episode": "E20",
        "current_beat_sheet_sha256": current_sha,
        "status": "PASS" if not failures else "FAIL",
        "scanned_contract_count": len(rows),
        "failures": failures,
        "contracts": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-dir", default="configs")
    parser.add_argument("--beat-sheet", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = scan(Path(args.config_dir).resolve(), Path(args.beat_sheet).resolve())
    out = Path(args.out).resolve()
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "scanned": report["scanned_contract_count"], "failures": len(report["failures"])}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
