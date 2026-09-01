#!/usr/bin/env python3
"""Audit whether every required SD2 field survives model-prompt compilation.

The audit deliberately raises the local length ceiling only while constructing
the evidence string.  Provider admission still uses the real 9,900-character
ceiling; overlong units are BLOCKED_AND_MUST_REGROUP, never truncated.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

try:
    import tools.compile_grouped_seedance_manifest as compiler
    from tools.sd2_required_prompt_field_gate import validate_required_sd2_field_coverage
except ModuleNotFoundError:
    import compile_grouped_seedance_manifest as compiler
    from sd2_required_prompt_field_gate import validate_required_sd2_field_coverage


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    manifest_path = args.manifest if args.manifest.is_absolute() else ROOT / args.manifest
    out = args.out if args.out.is_absolute() else ROOT / args.out
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    original_ceiling = compiler.MAX_MODEL_PROMPT_CHARS
    rows = []
    try:
        compiler.MAX_MODEL_PROMPT_CHARS = 1_000_000
        for unit in payload.get("units") or []:
            failures: list[str] = []
            text = ""
            try:
                text = compiler.prompt_text(unit)
                coverage = validate_required_sd2_field_coverage(unit, text)
                failures.extend(coverage["failures"])
            except Exception as exc:  # evidence report must name every rejected unit
                failures.append(str(exc))
            length = len(text)
            length_pass = 0 < length <= original_ceiling
            rows.append({
                "unit_id": unit.get("unit_id"),
                "beat_count": len(unit.get("ordered_prompt_specs") or []),
                "compiled_prompt_characters": length,
                "provider_prompt_ceiling": original_ceiling,
                "required_field_coverage": "PASS" if not failures else "FAIL",
                "provider_length_gate": "PASS" if length_pass else "FAIL",
                "admission": (
                    "PASS"
                    if not failures and length_pass
                    else "BLOCKED_AND_MUST_REGROUP_NO_FIELD_TRUNCATION"
                ),
                "failures": failures + ([] if length_pass else ["MODEL_PROMPT_TOO_LONG"]),
            })
    finally:
        compiler.MAX_MODEL_PROMPT_CHARS = original_ceiling
    passed = sum(row["admission"] == "PASS" for row in rows)
    result = {
        "schema": "qingshan.sd2_required_prompt_non_bypass_audit.v1",
        "episode": payload.get("episode"),
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_manifest": str(manifest_path.relative_to(ROOT)),
        "policy": {
            "all_required_fields_must_compile": True,
            "field_truncation_to_fit_provider_limit": "FORBIDDEN",
            "overlength_resolution": "REGROUP_VIDEO_UNIT_AND_RECOMPILE",
            "paid_provider_post_allowed_on_failure": False,
        },
        "unit_count": len(rows),
        "admitted_unit_count": passed,
        "blocked_unit_count": len(rows) - passed,
        "rows": rows,
        "provider_posts": 0,
        "status": "PASS" if passed == len(rows) else "BLOCKED_FAIL_CLOSED",
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"], "admitted": passed,
        "blocked": len(rows) - passed, "out": str(out.relative_to(ROOT)),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
