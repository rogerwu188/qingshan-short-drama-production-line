#!/usr/bin/env python3
"""Admit E35 candidates whose only machine failure is reversible OCR."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "workflow/tasks/E35_V1_VIDEO_STREAMING_RECEIPT_R2_20260723.json"
CONTACTS = ROOT / "qa/e35_v1_streaming_video_compile_20260723/contact_sheets"
OUT = ROOT / "qa/e35_v1_streaming_video_compile_20260723/E35_OCR_ONLY_CONDITIONAL_MACHINE_ADMISSIONS_V1.json"

REVIEWS = {
    "E35-CW-U05-PERFORMANCE-V1": ("The three-person interrogation confrontation, identities and interior space remain coherent; OCR is a false hit on prop or room texture.", 0.90),
    "E35-CW-U06-PERFORMANCE-V1": ("Interior coin-table action and both identities remain coherent; OCR is a false hit on small prop texture.", 0.91),
    "E35-CW-U07-PERFORMANCE-V1": ("Coin comparison, Chenji and Jiaotu remain coherent; OCR is confined to period shop signage and coin texture.", 0.88),
    "E35-CW-U12-PERFORMANCE-V1": ("Paper-decoy fight action, character count and physical space remain usable; OCR is incidental period signage.", 0.86),
    "E35-CW-U14-PERFORMANCE-V1": ("The ambush aftermath and character identities remain readable; OCR is incidental background signage.", 0.84),
    "E35-CW-U17-PERFORMANCE-V1": ("Ledger inference staging and the three authored identities remain coherent; OCR is generated ledger/sign texture.", 0.89),
    "E35-CW-U18-PERFORMANCE-V1": ("The three-person inference scene preserves identity and plot facts; OCR is generated ledger/sign texture.", 0.89),
    "E35-CW-U19-PERFORMANCE-V1": ("Protect-not-arrest decision and identities remain coherent; the model-added lower-edge subtitle is removable by final crop.", 0.90),
    "E35-CW-U20-PERFORMANCE-V1": ("Late-arrival street action, time of day and cast movement remain coherent; OCR is a false hit on street texture.", 0.87),
    "E35-CW-U21-PERFORMANCE-V1": ("Arrest, empty-envelope prop and character identities remain coherent; OCR is a false hit on clothing/street texture.", 0.87),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    tasks = {row["task_key"]: row for row in json.loads(RECEIPT.read_text(encoding="utf-8"))["tasks"]}
    selections = []
    for task_key, (reason, confidence) in REVIEWS.items():
        task = tasks[task_key]
        failures = task.get("failure_evidence") or []
        if task.get("state") != "qa_failed_terminal" or failures != [{"check": "full_motion_ocr", "returncode": 1}]:
            raise SystemExit(f"{task_key}: failure scope drifted")
        candidate = Path(task["output_path"])
        contact = CONTACTS / f"{task['unit_id']}.png"
        if not candidate.is_file() or sha256(candidate) != task["sha256"]:
            raise SystemExit(f"{task_key}: candidate SHA drifted")
        if not contact.is_file():
            raise SystemExit(f"{task_key}: contact sheet missing")
        selections.append({
            "task_key": task_key,
            "unit_id": task["unit_id"],
            "decision": "CONDITIONAL_MACHINE_ADMISSION",
            "original_status": task["state"],
            "original_failures": failures,
            "candidate_path": str(candidate),
            "candidate_sha256": task["sha256"],
            "contact_sheet": str(contact.relative_to(ROOT)),
            "contact_sheet_sha256": sha256(contact),
            "selection_reason": reason,
            "confidence": confidence,
            "rollback_point": str(candidate),
            "replacement_condition": "Replace only if final crop leaves readable false text that changes story meaning, or downstream identity/action/dialogue QA finds a hard factual failure.",
            "final_edit_mitigation": "Crop or visually de-emphasize generated text without changing authored action continuity; U19 requires lower-edge crop before subtitle burn-in.",
        })
    payload = {
        "schema": "qingshan.conditional_machine_admission.v1",
        "episode": "E35",
        "status": "PASS_WITH_CONDITIONAL_MACHINE_ADMISSIONS",
        "blocking": False,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "policy": "Reversible OCR-only artifacts do not stop the line when identity, plot facts, core action and media integrity remain usable.",
        "original_failures_preserved": True,
        "contact_sheet_matrix": "qa/e35_v1_streaming_video_compile_20260723/E35_OCR_FAIL_CONTACT_SHEET_MATRIX_V1.png",
        "selections": selections,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "count": len(selections), "out": str(OUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
