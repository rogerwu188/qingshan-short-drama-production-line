#!/usr/bin/env python3
"""Fail scripts that use dialogue without a declared narrative payload."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ALLOWED_PAYLOADS = {
    "new_event",
    "new_info",
    "power_shift",
    "character_reveal",
    "hook",
    "button",
    "ticking_clock",
}


def evaluate(script: dict) -> dict:
    lines = script.get("dialogue_draft")
    failures: list[str] = []
    evidence: list[dict] = []
    if not isinstance(lines, list) or not lines:
        return {
            "status": "FAIL",
            "failures": ["dialogue_draft_missing_or_empty"],
            "evidence": [],
        }

    padding_flags: list[bool] = []
    for index, line in enumerate(lines):
        dia_id = str(line.get("dia_id") or f"INDEX-{index + 1}")
        raw_payload = line.get("payload")
        payload = raw_payload if isinstance(raw_payload, list) else []
        valid = sorted({item for item in payload if item in ALLOWED_PAYLOADS})
        invalid = sorted({str(item) for item in payload if item not in ALLOWED_PAYLOADS})
        padding = not valid
        padding_flags.append(padding)
        if invalid:
            failures.append(f"{dia_id}:invalid_payload={','.join(invalid)}")
        evidence.append(
            {
                "dia_id": dia_id,
                "beat_id": line.get("beat_id"),
                "payload": valid,
                "padding": padding,
                "deletion_impact": line.get("deletion_impact"),
            }
        )

    padding_count = sum(padding_flags)
    padding_ratio = padding_count / len(lines)
    if padding_ratio > 0.10:
        failures.append(f"padding_ratio_exceeds_10_percent:{padding_count}/{len(lines)}")

    for index in range(1, len(padding_flags)):
        if padding_flags[index - 1] and padding_flags[index]:
            failures.append(
                f"consecutive_padding:{evidence[index - 1]['dia_id']}->{evidence[index]['dia_id']}"
            )

    return {
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "metrics": {
            "dialogue_count": len(lines),
            "payload_covered_count": len(lines) - padding_count,
            "padding_count": padding_count,
            "padding_ratio": round(padding_ratio, 6),
            "max_padding_ratio": 0.10,
        },
        "allowed_payloads": sorted(ALLOWED_PAYLOADS),
        "evidence": evidence,
        "semantic_review_note": "Payload proves declared function; deletion-impact semantics remain part of script council review.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the CL2X-306 anti-padding hard gate.")
    parser.add_argument("--script", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    script_path = Path(args.script).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()
    script = json.loads(script_path.read_text(encoding="utf-8"))
    result = {
        "schema": "qingshan.anti_padding_gate.v1",
        "gate_id": "ANTI-PADDING-20",
        "episode": script.get("episode"),
        "source_script": str(script_path),
        **evaluate(script),
        "rollback": "Restore the last approved script; do not generate from a failed script SHA.",
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "out": str(out_path), "failures": result["failures"]}, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
