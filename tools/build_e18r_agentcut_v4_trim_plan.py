#!/usr/bin/env python3
"""Build a speech-safe head-trim plan for the E18R AgentCut V4 project."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--sentence-audit", required=True)
    parser.add_argument("--beat-sheet", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--trim-seconds", type=float, default=0.2)
    parser.add_argument("--speech-guard-seconds", type=float, default=0.1)
    args = parser.parse_args()

    project_path = Path(args.project).expanduser().resolve()
    audit_path = Path(args.sentence_audit).expanduser().resolve()
    beat_sheet_path = Path(args.beat_sheet).expanduser().resolve()
    project = load(project_path)
    audit = load(audit_path)
    beat_sheet = load(beat_sheet_path)
    beat_by_id = {row["dia_id"]: row["beat_id"] for row in beat_sheet["dialogue_draft"]}
    sentence_by_id = {row["id"]: row for row in audit["sentences"]}

    rows = []
    total_trim = 0.0
    for dialogue_id in project["qingshanAudit"]["dialogue_order"]:
        sentence = sentence_by_id[dialogue_id]
        beat_id = beat_by_id[dialogue_id]
        first_start = min(
            (float(segment["start"]) for segment in sentence.get("segments", [])),
            default=0.0,
        )
        eligible = (
            beat_id != "B05"
            and sentence.get("complete") is True
            and not sentence.get("cut_inside_sentence")
            and first_start >= args.trim_seconds + args.speech_guard_seconds
        )
        trim = args.trim_seconds if eligible else 0.0
        total_trim += trim
        rows.append(
            {
                "dialogue_id": dialogue_id,
                "beat_id": beat_id,
                "first_asr_speech_start": round(first_start, 3),
                "source_head_trim_seconds": round(trim, 3),
                "speech_guard_seconds": args.speech_guard_seconds,
                "eligible": eligible,
                "reason": "ASR_PROVEN_SILENT_HEAD" if eligible else "NO_SAFE_TRIM_OR_B05_EXACT_PLAN",
            }
        )

    current_runtime = float(project["qingshanAudit"]["compiled_runtime_seconds"])
    target = float(project["qingshanAudit"]["runtime_target_seconds"])
    tolerance = float(project["qingshanAudit"]["runtime_tolerance_fraction"])
    projected_runtime = current_runtime - total_trim
    lower = target * (1.0 - tolerance)
    upper = target * (1.0 + tolerance)
    status = "PASS" if lower <= projected_runtime <= upper else "FAIL"
    payload = {
        "schema": "qingshan.e18r.agentcut_v4_speech_safe_trim_plan.v1",
        "status": status,
        "project": str(project_path),
        "sentence_audit": str(audit_path),
        "beat_sheet": str(beat_sheet_path),
        "policy": "Only ASR-proven silent source heads are trimmed; no speed change, sentence cut, overlap, or B05 exact-plan mutation.",
        "current_runtime_seconds": current_runtime,
        "total_trim_seconds": round(total_trim, 3),
        "projected_runtime_seconds": round(projected_runtime, 3),
        "allowed_runtime_seconds": [round(lower, 3), round(upper, 3)],
        "trimmed_dialogue_count": sum(1 for row in rows if row["eligible"]),
        "items": rows,
        "final_lock": False,
        "rollback": "Use the untrimmed V3 project and render if V4 ASR or sentence-boundary QA regresses."
    }
    out = Path(args.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "projected_runtime_seconds": round(projected_runtime, 3), "trimmed_dialogue_count": payload["trimmed_dialogue_count"], "out": str(out)}, ensure_ascii=False))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
