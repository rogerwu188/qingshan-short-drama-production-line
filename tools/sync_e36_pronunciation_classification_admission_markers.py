#!/usr/bin/env python3
import hashlib
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "workflow/work_queue.json"
AUDIT = ROOT / "qa/e36_agentcut_20260730/E36_ACCEPTED_SOURCE_TRANSCRIPT_BINDING_AUDIT_V11.json"
EXPECTED_AUDIT_SHA = "401d8114ab2a80e936cbd395f39cf9310e64b14b94ffd7d35d0b1194361f9e0a"
EXPECTED_COVERED_HISTORICAL = {9, 13, 14, 25, 26}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if sha256(AUDIT) != EXPECTED_AUDIT_SHA:
        raise SystemExit("authoritative transcript audit SHA mismatch")

    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    line_results = {
        int(row["contract_line_number"]): bool(row["covered_by_bound_accepted_transcripts"])
        for row in audit["line_results"]
    }
    unproven = {int(row["contract_line_number"]) for row in audit["unproven_lines"]}
    classifications = queue["lines"]["E36"]["pronunciation_hard_classifications"]

    covered_historical = set()
    for key, row in classifications.items():
        line = int(key.removeprefix("canonical_line_"))
        covered = line_results[line]
        row["covered_by_bound_accepted_transcripts"] = covered
        row["authoritative_transcript_audit"] = str(AUDIT.relative_to(ROOT))
        row["authoritative_transcript_audit_sha256"] = EXPECTED_AUDIT_SHA
        if covered:
            row["classification_status"] = "SUPERSEDED_BY_ADMISSION"
            row["superseded_by_admission"] = True
            row["covered"] = True
            covered_historical.add(line)
        else:
            if line not in unproven:
                raise SystemExit(f"line {line} is neither covered nor unproven")
            row["classification_status"] = "ACTIVE_UNPROVEN"
            row["superseded_by_admission"] = False
            row["covered"] = False

    if covered_historical != EXPECTED_COVERED_HISTORICAL:
        raise SystemExit(
            f"historical covered set mismatch: {sorted(covered_historical)}"
        )

    now = datetime.now(timezone(timedelta(hours=-7))).replace(microsecond=0).isoformat()
    queue["updated_at"] = now
    note = (
        "CL2X-882 residual advisory consumed: pronunciation_hard_classifications "
        "lines9/13/14/25/26 marked covered and SUPERSEDED_BY_ADMISSION; "
        "active unproven pronunciation-hard entries remain lines2/3/16/23/28 per V11."
    )
    queue["updated_note_latest"] = note
    queue["lines"]["E36"]["latest_cl2x882_pronunciation_detail_sync"] = note
    QUEUE.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "status": "PASS",
        "updated_at": now,
        "covered_historical": sorted(covered_historical),
        "active_unproven_pronunciation_hard": [2, 3, 16, 23, 28],
        "queue_sha256": sha256(QUEUE),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
