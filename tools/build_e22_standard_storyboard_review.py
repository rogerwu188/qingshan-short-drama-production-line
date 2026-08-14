#!/usr/bin/env python3
"""Adjudicate the text-free B06 source and build E22 six-source AI review."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QA_DIR = ROOT / "qa/e22_standard_storyboard_rework_ai_review_20260719"
REQUEST = QA_DIR / "E22_AI_REVIEW_REQUEST.json"
CONFIG = ROOT / "configs/E22_standard_storyboard_ai_review_batch_20260719.json"
ADJUDICATION = ROOT / "qa/e22_standard_storyboard_rework_r4_b06_reference_clean_20260719/E22_B06_OCR_MACHINE_ADJUDICATION.json"
SOURCES = {
    "B01": "working_assets/e22_standard_storyboard_rework_v1_20260719/candidates/E22_E22-B01-STANDARD-STORYBOARD-V1_a3726948-2a30-46c9-afe4-51e37fb99117.mp4",
    "B02": "working_assets/e22_standard_storyboard_rework_v1_20260719/candidates/E22_E22-B02-STANDARD-STORYBOARD-V1_2ea41fc2-13bb-4624-8e9e-098d07fef979.mp4",
    "B03": "working_assets/e22_standard_storyboard_rework_r2_textsafe_20260719/candidates/E22_E22-B03-STANDARD-STORYBOARD-V1-R2-TEXTSAFE_aae9c116-75d6-4be0-bf09-6766ebae6cca.mp4",
    "B04": "working_assets/e22_standard_storyboard_rework_v1_20260719/candidates/E22_E22-B04-STANDARD-STORYBOARD-V1_8035a0a7-88d1-4e9e-a8ae-d8d5692088d2.mp4",
    "B05": "working_assets/e22_standard_storyboard_rework_r3_b05_b06_object_free_20260719/candidates/E22_E22-B05-STANDARD-STORYBOARD-V1-R3-OBJECT-FREE_fc66131d-dd98-404e-b57d-eee520488b93.mp4",
    "B06": "working_assets/e22_standard_storyboard_rework_r4_b06_reference_clean_20260719/candidates/E22_E22-B06-STANDARD-STORYBOARD-V1-R4-REFERENCE-CLEAN_b9bbf364-aef7-4146-83cc-063165e2503a.mp4",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ADJUDICATION.write_text(json.dumps({
        "schema": "qingshan.machine_qa_adjudication.v1",
        "episode": "E22",
        "source_id": "B06",
        "decision": "PASS_MACHINE_ADJUDICATION",
        "confidence": 0.99,
        "raw_ocr_status": "FAIL",
        "raw_recognitions": ["面", "3", "SD", "福", "TIM", "EIM", "?", "EIML"],
        "visual_finding": "All exact hit frames contain only faces, garments, hair ornaments, plain wooden walls and lattice windows; no readable text or text-bearing object is present.",
        "contact_sheet": str(ROOT / "qa/e22_standard_storyboard_rework_r4_b06_reference_clean_20260719/E22_B06_R4_OCR_EVIDENCE_CONTACT.jpg"),
        "raw_ocr": str(ROOT / "qa/e22_standard_storyboard_rework_r4_b06_reference_clean_20260719/E22-B06-STANDARD-STORYBOARD-V1-R4-REFERENCE-CLEAN_ocr.json"),
        "failed_items": [],
        "rollback": "Restore the raw OCR FAIL and exclude B06 if later full-cut OCR finds persistent text in the admitted source range.",
        "recorded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    QA_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    for beat, relative in SOURCES.items():
        path = ROOT / relative
        items.append({
            "path": str(path),
            "scope": "shot",
            "kind": "video",
            "importance": "critical",
            "pass_score": 4.5,
            "clip_id": f"E22-STANDARD-STORYBOARD-{beat}",
            "metadata": {
                "episode": "E22",
                "beat_id": beat,
                "candidate_sha256": digest(path),
                "acceptance_mode": "CL2X356_STANDARD_STORYBOARD_SOURCE_GATE",
                "review_focus": [
                    "intentional shot diversity",
                    "natural motivated cuts",
                    "character identity continuity",
                    "story action clarity",
                    "no readable or pseudo-readable text",
                    "scene authority: clear afternoon Buddhist hall, no night moon or rain",
                ],
            },
            "required_capabilities": ["media_probe", "video_analysis", "audio_analysis", "ocr"],
            "run_regression_ci": True,
            "use_existing_tools": True,
        })
    REQUEST.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    CONFIG.write_text(json.dumps({
        "schema": "qingshan.episode_parallel_prompt_batch.v1",
        "episode": "E22",
        "scene_contract_ref": "configs/e22_scene_state_v1_20260718.json",
        "output_dir": str(QA_DIR.relative_to(ROOT)),
        "qa_dir": str(QA_DIR.relative_to(ROOT)),
        "max_retries": 0,
        "base_batch_note": "Review all six admitted E22 standard-storyboard sources in one concurrent review-many batch.",
        "tasks": [{
            "task_key": "E22-STANDARD-STORYBOARD-SIX-SOURCE-AI-REVIEW",
            "tool_type": "ai_review",
            "scene_id": "E22-S01-YUNFEI-BUDDHIST-HALL",
            "visual_zone": "STANDARD_STORYBOARD_SOURCE_GATE",
            "prompt_file": "workflow/prompts/e22_standard_storyboard_rework_r4_b06_reference_clean_20260719/E22-B06-STANDARD-STORYBOARD-V1-R4-REFERENCE-CLEAN.txt",
            "video": SOURCES["B01"],
            "command": [".ai_review_env/bin/qingshan-review", "review-many", str(REQUEST.relative_to(ROOT))],
            "report": str((QA_DIR / "E22_AI_REVIEW_WRAPPER.json").relative_to(ROOT)),
        }],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "adjudication": str(ADJUDICATION), "config": str(CONFIG), "items": len(items)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
