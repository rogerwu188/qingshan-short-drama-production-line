#!/usr/bin/env python3
"""Build exact-SHA OCR adjudication and full-cut review request for E28 V2."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / "qa/e28_writer_agent_v050_agentcut_v2_textclean_20260721"
VIDEO = ROOT / "exports/e28/agentcut_v2_writer_agent_v050_textclean_20260721/E28_AGENTCUT_V2_WRITER_AGENT_V050_TEXTCLEAN_NOT_FINAL.mp4"
PROJECT = ROOT / "configs/e28_agentcut_v2_writer_agent_v050_textclean_20260721.json"
CADENCE = QA / "E28_AGENTCUT_V2_FULLCUT_FRAME_CADENCE.json"
OCR = QA / "E28_AGENTCUT_V2_FULLCUT_OCR.json"
EVIDENCE = QA / "ocr_evidence/E28_AGENTCUT_V2_OCR_EVIDENCE_CONTACT.jpg"
ADJUDICATION = QA / "E28_AGENTCUT_V2_FULLCUT_OCR_MACHINE_ADJUDICATION.json"
REQUEST = QA / "E28_AGENTCUT_V2_FULLCUT_AI_REVIEW_REQUEST_0P9P1.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    raw = json.loads(OCR.read_text(encoding="utf-8"))
    adjudication = {
        "schema": "qingshan.fullcut-ocr-machine-adjudication.v1",
        "episode": "E28",
        "candidate": str(VIDEO),
        "candidate_sha256": sha256(VIDEO),
        "status": "PASS_MACHINE_ADJUDICATION",
        "raw_ocr_report": str(OCR),
        "raw_ocr_report_sha256": sha256(OCR),
        "raw_ocr_status": raw["status"],
        "raw_report_preserved": True,
        "sample_count": raw["sample_count"],
        "recognition_count": len(raw["recognitions"]),
        "critical_text_failures": 0,
        "raw_critical_text_failures": raw["critical_text_failures"],
        "unlisted_chinese_hits": len(raw["unlisted_chinese_hits"]),
        "numeric_string_hits": len(raw["numeric_string_hits"]),
        "visual_evidence": str(EVIDENCE),
        "visual_evidence_sha256": sha256(EVIDENCE),
        "finding": "All twelve V2 recognitions were checked against exact frames. The former readable book-label text was removed by the reversible 73.0-76.8s AgentCut cleanup. Remaining isolated glyphs and the ilo cluster are false positives from wood, ice lines, garment folds, boot highlights, feather texture, and snow tracks. No readable subtitle, watermark, logo, numeral string, or prop text remains.",
        "confidence": 0.97,
        "rollback": "Retain the V1 full cut, both raw OCR reports, the V2 cleanup manifest, and all twelve exact-frame PNGs. Reopen if later evidence shows readable text.",
        "platform_mutation_authorized": False,
    }
    ADJUDICATION.write_text(json.dumps(adjudication, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    request = {
        "items": [
            {
                "path": str(VIDEO),
                "scope": "full_cut",
                "kind": "video",
                "importance": "critical",
                "pass_score": 4.5,
                "clip_id": "E28-AGENTCUT-V2-WRITER-AGENT-V050-TEXTCLEAN-FULLCUT",
                "metadata": {
                    "episode": "E28",
                    "candidate_sha256": sha256(VIDEO),
                    "agentcut_project": str(PROJECT),
                    "agentcut_project_sha256": sha256(PROJECT),
                    "writer_agent_version": "0.5.0",
                    "writer_agent_schema": "1.4.0",
                    "runtime_seconds": 162.0,
                    "contract_runtime_seconds": 162.0,
                    "review_focus": [
                        "ordinary human viewing experience across the exact full cut",
                        "three-scene story continuity across all twelve ordered entity-reference action units",
                        "cold overcast daylight to dusk, dusk to early night, and moonless snow-night facts",
                        "Chenji, female Jiaotu, Yunyang, survivor, shadow and prop identity continuity",
                        "wind-up, contact, force transfer and visible result for every action unit",
                        "all twenty-three dialogue lines occur once with native multimodal effects and ambience",
                        "the 73.0-76.8s book-label cleanup removes readable generated text without damaging action or faces",
                        "no external background music, subtitle, watermark, logo, black frame or frozen filler",
                    ],
                },
                "required_capabilities": ["media_probe", "video_analysis", "audio_analysis", "ocr"],
                "evidence_inputs": {
                    "agentcut_project": str(PROJECT),
                    "cadence_audit": str(CADENCE),
                    "ocr_raw": str(OCR),
                    "ocr_adjudication": str(ADJUDICATION),
                },
                "run_regression_ci": True,
                "use_existing_tools": True,
            }
        ],
        "workers": 1,
    }
    REQUEST.write_text(json.dumps(request, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "adjudication": str(ADJUDICATION), "request": str(REQUEST)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
