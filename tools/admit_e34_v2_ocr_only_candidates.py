#!/usr/bin/env python3
"""Admit visually reviewed E34 candidates whose only machine failure is OCR."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "workflow/tasks/E34_VIDEO_STREAMING_PERFORMANCE_V2_RECEIPT_20260723.json"
SPLIT = ROOT / "workflow/tasks/E34_U17_SPLIT_REPAIR1_VIDEO_RECEIPT_20260723.json"
OUT = ROOT / "qa/e34_v2_streaming_video_compile_20260723/E34_OCR_ONLY_CONDITIONAL_MACHINE_ADMISSIONS_V2.json"
REVIEWS = {
    "E34-CW-U05-PERFORMANCE-V2": {
        "contact_sheet": "qa/e34_v2_streaming_video_compile_20260723/contact_sheets/U05.png",
        "reason": "The three authored characters, interior morning location, ledger-table action and camera motion are usable. OCR was triggered only by model-invented paper marks; no subtitle, identity, safety or plot-fact error is present.",
        "confidence": 0.86,
        "replacement_condition": "Replace only if the final crop leaves a clearly readable false phrase central enough to alter story meaning.",
    },
    "E34-CW-U15-PERFORMANCE-V2": {
        "contact_sheet": "qa/e34_v2_streaming_video_compile_20260723/contact_sheets/U15.png",
        "reason": "Yanjing remains bound in the chair and Chenji remains the standing young interrogator. OCR was triggered by peripheral paper marks; dialogue staging, identities and scene facts remain usable.",
        "confidence": 0.88,
        "replacement_condition": "Replace only if final framing makes the peripheral paper text legible or contradicts the interrogation facts.",
    },
    "E34-CW-U17A-PERFORMANCE-V2-REPAIR1": {
        "contact_sheet": "qa/e34_v2_streaming_video_compile_20260723/contact_sheets/U17A.png",
        "reason": "The split performance preserves Yanjing, Chenji and Jiaotu, the binding rope, chair and escalating confession. OCR was triggered by a small ledger area; the dialogue performance and plot facts are usable.",
        "confidence": 0.90,
        "replacement_condition": "Replace only if final framing makes the small ledger marks readable as contradictory text or ASR later finds missing dialogue.",
    },
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    tasks = {}
    for receipt in (MAIN, SPLIT):
        for row in json.loads(receipt.read_text(encoding="utf-8"))["tasks"]:
            tasks[row["task_key"]] = row
    selections = []
    for task_key, review in REVIEWS.items():
        task = tasks[task_key]
        path = Path(task["output_path"])
        failures = task.get("failure_evidence") or []
        if task.get("status") != "qa_failed_terminal" or failures != [{"check": "full_motion_ocr", "returncode": 1}]:
            raise SystemExit(f"{task_key}: failure scope drifted")
        if not path.is_file() or sha(path) != task["sha256"]:
            raise SystemExit(f"{task_key}: candidate SHA drifted")
        contact = ROOT / review["contact_sheet"]
        if not contact.is_file():
            raise SystemExit(f"{task_key}: contact sheet missing")
        selections.append({
            "task_key": task_key,
            "unit_id": task["unit_id"],
            "decision": "CONDITIONAL_MACHINE_ADMISSION",
            "original_status": task["status"],
            "original_failures": failures,
            "candidate_path": str(path),
            "candidate_sha256": task["sha256"],
            "contact_sheet": review["contact_sheet"],
            "contact_sheet_sha256": sha(contact),
            "selection_reason": review["reason"],
            "confidence": review["confidence"],
            "rollback_point": str(path),
            "replacement_condition": review["replacement_condition"],
            "final_edit_mitigation": "Prefer crop or visual de-emphasis of paper marks without altering character, dialogue or action continuity.",
        })
    payload = {
        "schema": "qingshan.conditional_machine_admission.v1",
        "episode": "E34",
        "status": "PASS_WITH_CONDITIONAL_MACHINE_ADMISSIONS",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "policy": "Creative, reversible OCR-only artifacts do not stop the line when identity, plot facts, dialogue staging and media integrity remain usable.",
        "original_failures_preserved": True,
        "selections": selections,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "count": len(selections), "out": str(OUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
