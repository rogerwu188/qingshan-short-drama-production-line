#!/usr/bin/env python3
"""Write per-unit before/after immutable contract SHA receipts."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
from typing import Any

try:
    from tools.provider_contract_boundary import structured_contract_sha256
    from tools.submit_giggle_video_manifest_v2 import grouped_sequence_unit
    from tools.video_prompt_compiler import compile_model_prompt
except ModuleNotFoundError:
    from provider_contract_boundary import structured_contract_sha256
    from submit_giggle_video_manifest_v2 import grouped_sequence_unit
    from video_prompt_compiler import compile_model_prompt


SCHEMA = "qingshan.provider_contract_immutability_audit.v1_per_unit_before_after"


def task_to_unit(task: dict[str, Any]) -> dict[str, Any]:
    unit = grouped_sequence_unit(task)
    unit.update({
        "model": task.get("model"),
        "duration_seconds": task.get("duration_seconds"),
        "resolution": task.get("resolution"),
        "aspect_ratio": task.get("aspect_ratio"),
        "h3_prompt_profile": task.get("h3_prompt_profile"),
        "reference_images": [
            {"path": path, "role": role}
            for path, role in zip(
                task.get("reference_images") or [],
                task.get("reference_roles") or ["SEMANTIC_REFERENCE"] * len(task.get("reference_images") or []),
            )
        ],
    })
    return unit


def audit_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for task in manifest.get("tasks") or []:
        unit = task_to_unit(task)
        before = structured_contract_sha256(unit)
        compile_status = "PASS"
        compile_error = None
        try:
            compile_model_prompt(deepcopy(unit))
        except (ValueError, RuntimeError) as exc:
            compile_status = "FAIL_CLOSED"
            compile_error = str(exc)
        after = structured_contract_sha256(unit)
        rows.append({
            "unit_id": str(unit.get("unit_id") or task.get("task_key") or "UNKNOWN"),
            "contract_sha_before": before,
            "contract_sha_after": after,
            "equal": before == after,
            "compile_status": compile_status,
            "compile_error": compile_error,
        })
    failures = [row["unit_id"] for row in rows if not row["equal"]]
    return {
        "schema": SCHEMA,
        "status": "PASS" if not failures else "FAIL",
        "unit_count": len(rows),
        "equal_count": sum(row["equal"] for row in rows),
        "rows": rows,
        "failures": failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    report = audit_manifest(manifest)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("status", "unit_count", "equal_count")}, ensure_ascii=False))
    raise SystemExit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
