#!/usr/bin/env python3
"""Apply evidence-bound homophone decisions to E19R multimodal batch QA."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", required=True, type=Path)
    parser.add_argument("--decisions", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    audit = json.loads(args.audit.read_text(encoding="utf-8"))
    decisions = json.loads(args.decisions.read_text(encoding="utf-8"))
    rows = {row["dialogue_id"]: row for row in audit["results"]}
    applied: list[str] = []
    for decision in decisions["items"]:
        row = rows.get(decision["dialogue_id"])
        if row is None:
            raise SystemExit(f"missing dialogue: {decision['dialogue_id']}")
        if row.get("expected") != decision["expected"] or row.get("transcript") != decision["observed"]:
            raise SystemExit(f"stale decision evidence: {decision['dialogue_id']}")
        if not row.get("audio_stream") or not row.get("segments"):
            raise SystemExit(f"cannot waive missing audio or ASR: {decision['dialogue_id']}")
        row["raw_status"] = row["status"]
        row["raw_failures"] = list(row["failures"])
        row["status"] = "PASS"
        row["failures"] = []
        row["machine_adjudication"] = {
            "decision": decision["decision"],
            "reason": decision["reason"],
            "phonetic_alignment": decision["phonetic_alignment"],
            "confidence": decisions["confidence"],
            "rollback": decisions["rollback"],
        }
        applied.append(decision["dialogue_id"])
    remaining = [row["dialogue_id"] for row in audit["results"] if row["status"] == "FAIL"]
    audit.update(
        {
            "schema": "qingshan.e19r.multimodal_binding_batch_qa.machine_adjudicated.v1",
            "raw_audit": str(args.audit),
            "adjudication": str(args.decisions),
            "status": "PASS" if not remaining else "FAIL",
            "pass_count": len(audit["results"]) - len(remaining),
            "fail_count": len(remaining),
            "adjudicated_ids": applied,
            "remaining_failures": remaining,
        }
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": audit["status"], "adjudicated": applied, "remaining": remaining}, ensure_ascii=False))
    return 0 if not remaining else 2


if __name__ == "__main__":
    raise SystemExit(main())
