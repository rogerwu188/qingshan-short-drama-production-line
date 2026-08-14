#!/usr/bin/env python3
"""Apply explicit, evidence-bound homophone adjudications to an ASR audit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", required=True)
    parser.add_argument("--adjudication", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    audit_path = Path(args.audit).expanduser().resolve()
    adjudication_path = Path(args.adjudication).expanduser().resolve()
    audit = load(audit_path)
    adjudication = load(adjudication_path)
    rows = {row["id"]: row for row in audit["sentences"]}
    applied = []
    for decision in adjudication["items"]:
        row = rows.get(decision["id"])
        if row is None:
            raise SystemExit(f"Adjudication ID is absent from audit: {decision['id']}")
        if row["expected"] != decision["expected"]:
            raise SystemExit(f"Expected text changed for {decision['id']}")
        if row["transcript"] != decision["observed"]:
            raise SystemExit(f"Observed ASR changed for {decision['id']}")
        if row.get("cut_inside_sentence"):
            raise SystemExit(f"Cannot waive a sentence cut: {decision['id']}")
        row["complete"] = True
        row["failures"] = []
        row["machine_adjudication"] = {
            "type": "HOMOPHONE_OR_SCRIPT_VARIANT",
            "reason": decision["reason"],
            "confidence": adjudication["confidence"],
            "rollback": adjudication["rollback"],
        }
        applied.append(decision["id"])

    failures = [row["id"] for row in audit["sentences"] if not row["complete"]]
    audit.update(
        {
            "schema": "qingshan.e18r.agentcut_sentence_completeness.machine_adjudicated.v1",
            "status": "PASS" if not failures else "FAIL",
            "raw_audit": str(audit_path),
            "adjudication": str(adjudication_path),
            "complete_count": len(audit["sentences"]) - len(failures),
            "failure_count": len(failures),
            "failures": failures,
            "adjudicated_ids": applied,
        }
    )
    out = Path(args.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": audit["status"], "adjudicated": applied, "out": str(out)}, ensure_ascii=False))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
