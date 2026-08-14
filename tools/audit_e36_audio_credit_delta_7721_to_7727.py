#!/usr/bin/env python3
"""Reconcile the exact E36 audio delta called out by CL2X-843."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "qa/e36_agentcut_20260730/E36_AUDIO_CREDIT_DELTA_7721_TO_7727_RECONCILIATION_V1.json"
RECEIPTS = [
    ROOT / "workflow/tasks/E36_U11_R1_D01_YUNYANG_PROSODY_R2_EXACT_DIALOGUE_AUDIO_GENERATION_V1.json",
    ROOT / "workflow/tasks/E36_U14_R5_D01_CHENJI_EXACT_DIALOGUE_AUDIO_GENERATION_V1.json",
    ROOT / "workflow/tasks/E36_U14_R6_D01_CHENJI_EXACT_DIALOGUE_AUDIO_GENERATION_V1.json",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    rows = []
    for path in RECEIPTS:
        receipt = json.loads(path.read_text())
        credit = receipt["credit"]
        task_id = receipt["task_id"]
        statement_rows = credit["statement_rows"]
        exact_rows = [
            row
            for row in statement_rows
            if row.get("project_id") == task_id and row.get("event_type") == "Pay"
        ]
        rows.append({
            "receipt_path": str(path.relative_to(ROOT)),
            "receipt_sha256": sha256(path),
            "unit_id": receipt["unit_id"],
            "task_id": task_id,
            "spoken_text": receipt["spoken_text"],
            "charged_credits": credit["charged_credits"],
            "credit_status": credit["status"],
            "exact_statement_row_count": len(exact_rows),
            "statement_project_ids": sorted({row.get("project_id") for row in exact_rows}),
        })

    task_ids = [row["task_id"] for row in rows]
    delta = sum(row["charged_credits"] for row in rows)
    report = {
        "schema": "qingshan.e36.audio_credit_delta_reconciliation.v1",
        "episode": "E36",
        "source_cl2x": "CL2X-843",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS_EXACT_AUDIO_DELTA_RECONCILED",
        "scope": {
            "starting_exact_episode_net": 7721,
            "ending_exact_episode_net": 7727,
            "expected_audio_delta": 6,
            "observed_audio_delta": delta,
            "shared_api_non_source_rows": "EXCLUDED",
        },
        "rows": rows,
        "gate_results": {
            "receipt_count": len(rows),
            "unique_task_ids": len(set(task_ids)) == len(task_ids),
            "all_exact_project_id_rows": all(row["exact_statement_row_count"] == 1 for row in rows),
            "all_known_exact_credit": all(row["credit_status"] == "KNOWN_EXACT_TASK_STATEMENT" for row in rows),
            "all_pay2": all(row["charged_credits"] == 2 for row in rows),
            "delta_matches": delta == 6,
            "new_generation": "PASS_NONE",
            "new_qa_credits": 0,
        },
        "blocked_by": "NONE_FOR_RECONCILIATION",
        "next_action": (
            "Use 7727/10000 as the exact source-attributable E36 net. Continue production on an "
            "independent unproven line; keep unrelated shared-API rows excluded."
        ),
    }
    if not all(value is True for key, value in report["gate_results"].items() if isinstance(value, bool)):
        report["status"] = "FAIL_RECONCILIATION_MISMATCH"
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "delta": delta, "out": str(OUT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
