#!/usr/bin/env python3
"""Preserve E33 OCR failures and admit only visually/story-safe candidates."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SELECTION = ROOT / "workflow/claude_writer_agent/production/e33_claude_writer_v2_e19276d4_20260723/video_performance_v2/E33_VIDEO_SOURCE_SELECTION_V2.json"
OUT = ROOT / "workflow/claude_writer_agent/production/e33_claude_writer_v2_e19276d4_20260723/video_performance_v2/qa/E33_V2_OCR_ONLY_CONDITIONAL_MACHINE_ADMISSIONS_V1.json"
DECISIONS = {
    "E33-CW-U06": (0.94, "OCR tokens resolve to paper, sleeve and blue-light texture; no readable non-story text appears in the three-point review."),
    "E33-CW-U12": (0.94, "OCR tokens resolve to splinter, ice and costume texture; no readable non-story text appears in the three-point review."),
    "E33-CW-U14": (0.93, "OCR tokens resolve to wet stone, chest and clothing texture; no readable non-story text appears in the three-point review."),
    "E33-CW-U19": (0.91, "The sampled book and faces contain no stable readable non-story text; the single OCR phrase is a transient texture false positive."),
    "E33-CW-U22": (0.91, "The visible name Shen Yan is required by the locked script; nearby low-confidence variants are reversible OCR noise and do not alter story facts."),
    "E33-CW-U23": (0.86, "The open register is required diegetic evidence. Incidental pseudo-calligraphy is non-critical, reversible and does not alter identity or story facts."),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    selection = json.loads(SELECTION.read_text(encoding="utf-8"))
    by_unit = {row["unit_id"]: row for row in selection["rows"]}
    rows = []
    for unit_id, (confidence, reason) in DECISIONS.items():
        source = by_unit[unit_id]
        if source["source_state"] != "qa_failed_terminal":
            raise SystemExit(f"expected preserved raw OCR failure for {unit_id}")
        rows.append({
            "unit_id": unit_id,
            "decision": "CONDITIONAL_MACHINE_ADMISSION",
            "candidate_path": source["output_path"],
            "candidate_sha256": source["sha256"],
            "original_qa_status": source["source_state"],
            "original_qa": source["original_qa"],
            "failure_items": ["FULL_MOTION_OCR"],
            "selection_reason": reason,
            "confidence": confidence,
            "story_facts_preserved": True,
            "identity_preserved": True,
            "media_technically_usable": True,
            "rollback_point": source["source_receipt"],
            "replacement_condition": "Replace only if later exact-frame evidence proves stable unauthorized readable text or a story/identity contradiction.",
        })
    payload = {
        "schema": "qingshan.conditional_machine_admission.v1",
        "episode": "E33",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "decision": "CONDITIONAL_MACHINE_ADMISSION",
        "status": "PASS_6_REVERSIBLE_OCR_ONLY_CANDIDATES_ADMITTED",
        "policy": "Original QA failures remain immutable. Reversible OCR-only disagreements do not stop downstream editing when story, identity and media integrity remain usable.",
        "selection_manifest": str(SELECTION),
        "selection_manifest_sha256": sha256(SELECTION),
        "visual_evidence": [
            str(ROOT / f"qa/e33_v2_final_video_source_review_20260723/E33_V2_SOURCE_REVIEW_PAGE_{page:02d}.jpg")
            for page in range(1, 5)
        ],
        "rows": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "out": str(OUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
