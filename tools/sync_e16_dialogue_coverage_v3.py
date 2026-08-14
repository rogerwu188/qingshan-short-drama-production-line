#!/usr/bin/env python3
"""Synchronize approved-candidate E16 dialogue text/roles into coverage metadata."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIALOGUE = ROOT / "configs/e16_dialogue_beat_sheet_20260711.json"
COVERAGE = ROOT / "configs/e16_director_coverage_hotfix_20260711.json"

INSERTS = {
    "D46": ("I-D46-PUPIL", "pupil_dilated_not_reactive"),
    "D47": ("I-D47-EYE", "scleral_petechiae"),
    "D48": ("I-D48-NECK", "neck_mark_without_vital_reaction"),
    "D50": ("I-D50-WOUND", "fresh_wound_without_external_bleeding"),
    "D52": ("I-D52-WRIST", "second_coroner_thread_mark"),
}


def main() -> None:
    dialogue = json.loads(DIALOGUE.read_text(encoding="utf-8"))
    coverage = json.loads(COVERAGE.read_text(encoding="utf-8"))
    lines = {line["id"]: line for line in dialogue["lines"]}
    for beat in coverage["beats"]:
        line = lines[beat["dialogue_beat_id"]]
        beat["text"] = line["text"]
        beat["speaker"] = line["speaker"]
        beat["listener"] = line["listener"]
        beat["listener_reaction"] = line["listener_reaction"]
        beat["A"]["status"] = "PENDING_REGEN_AFTER_DIALOGUE_APPROVAL"
        beat["B"]["status"] = "PLANNED_OR_PENDING_SOURCE"
        if beat["dialogue_beat_id"] in INSERTS:
            shot_id, role = INSERTS[beat["dialogue_beat_id"]]
            beat["insert"] = {
                "shot_id": shot_id,
                "role": role,
                "source_required": True,
                "status": "MISSING_OR_PENDING_SOURCE",
            }
    coverage["status"] = "DIALOGUE_V3_SYNCED_PENDING_CLAUDE_APPROVAL"
    coverage["dialogue_revision"] = "autopsy_read_chain_v3_five_signs_plus_knowledge_slip"
    COVERAGE.write_text(json.dumps(coverage, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"synced={len(coverage['beats'])}")


if __name__ == "__main__":
    main()
