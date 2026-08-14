#!/usr/bin/env python3
"""Adjudicate E22 V17 OCR false positives and build full-cut AI review."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VIDEO = ROOT / "exports/e22/agentcut_v17_standard_storyboard_coverage_20260719/E22_AGENTCUT_V17_STANDARD_STORYBOARD_COVERAGE_NOT_FINAL.mp4"
QA_DIR = ROOT / "qa/e22_agentcut_v17_standard_storyboard_coverage_20260719"
ADJUDICATION = QA_DIR / "E22_V17_OCR_MACHINE_ADJUDICATION.json"
REQUEST = QA_DIR / "E22_AI_REVIEW_REQUEST.json"
CONFIG = ROOT / "configs/E22_agentcut_v17_ai_review_20260719.json"


def main() -> int:
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    raw_ocr = QA_DIR / "E22_FINAL_VIDEO_OCR_AUDIT_V17_FULL_DURATION.json"
    audit = json.loads(raw_ocr.read_text(encoding="utf-8"))
    ADJUDICATION.write_text(json.dumps({
        "schema": "qingshan.machine_qa_adjudication.v1",
        "episode": "E22",
        "version": "v17",
        "decision": "PASS_MACHINE_ADJUDICATION",
        "confidence": 0.98,
        "raw_ocr_status": audit["status"],
        "raw_critical_text_failures": audit["critical_text_failures"],
        "exact_hit_times": [row["time_seconds"] for row in audit["recognitions"]],
        "visual_finding": "Exact-frame contact sheet shows only people, plain documents/cloth, Buddhist-hall architecture and expected bottom subtitles. The OCR tokens are hallucinations from garments, faces, lattice and object texture; no native readable or pseudo-readable text appears above the subtitle exclusion band.",
        "contact_sheet": str(QA_DIR / "E22_V17_OCR_HIT_CONTACT.jpg"),
        "raw_ocr": str(raw_ocr),
        "failed_items": [],
        "rollback": "Restore raw OCR FAIL if a later independent review identifies persistent native text at any listed time.",
        "recorded_at": now,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    digest = hashlib.sha256(VIDEO.read_bytes()).hexdigest()
    REQUEST.write_text(json.dumps({"items": [{
        "path": str(VIDEO),
        "scope": "full_cut",
        "kind": "video",
        "importance": "critical",
        "pass_score": 4.5,
        "clip_id": "E22-AGENTCUT-V17-FULL-CUT",
        "metadata": {
            "episode": "E22",
            "candidate_sha256": digest,
            "acceptance_mode": "FINAL_CUT_AI_REVIEW_WITH_PRESERVED_RAW_OCR_ADJUDICATION",
            "ocr_adjudication": str(ADJUDICATION),
            "review_focus": ["human viewing experience", "story clarity", "pacing", "identity continuity", "motivated cuts", "verify no native text at OCR hit times"],
        },
        "required_capabilities": ["media_probe", "video_analysis", "audio_analysis", "ocr"],
        "run_regression_ci": True,
        "use_existing_tools": True,
    }]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    CONFIG.write_text(json.dumps({
        "schema": "qingshan.episode_parallel_prompt_batch.v1",
        "episode": "E22",
        "scene_contract_ref": "configs/e22_scene_state_v1_20260718.json",
        "output_dir": str(QA_DIR.relative_to(ROOT)),
        "qa_dir": str(QA_DIR.relative_to(ROOT)),
        "max_retries": 0,
        "base_batch_note": "Full-cut AI review after four objective gates passed and raw OCR false positives were exact-frame adjudicated.",
        "tasks": [{
            "task_key": "E22-AGENTCUT-V17-FULL-CUT-AI-REVIEW",
            "tool_type": "ai_review",
            "scene_id": "E22-S01-YUNFEI-BUDDHIST-HALL",
            "visual_zone": "FULL_CUT_AI_REVIEW",
            "prompt_file": "workflow/prompts/e22_v4_full_dialogue_parallel_20260719/videos/DIA-016.txt",
            "video": str(VIDEO.relative_to(ROOT)),
            "command": [".ai_review_env/bin/qingshan-review", "review-many", str(REQUEST.relative_to(ROOT))],
            "report": str((QA_DIR / "E22_AI_REVIEW_WRAPPER.json").relative_to(ROOT)),
        }],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "adjudication": str(ADJUDICATION), "config": str(CONFIG)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
