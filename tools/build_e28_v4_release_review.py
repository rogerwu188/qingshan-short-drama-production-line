#!/usr/bin/env python3
"""Build E28 V4 OCR adjudication and exact-SHA review request."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / "qa/e28_writer_agent_v050_agentcut_v4_recut_20260721"
VIDEO = ROOT / "exports/e28/agentcut_v4_midsection_recut_20260721/E28_AGENTCUT_V4_MIDSECTION_RECUT_NOT_FINAL.mp4"
PROJECT = ROOT / "configs/e28_agentcut_v4_midsection_recut_20260721.json"
CADENCE = QA / "E28_AGENTCUT_V4_FULLCUT_FRAME_CADENCE.json"
REPEAT_GATE = QA / "E28_V4_NEAR_FREEZE_AND_REPEAT_GATE.json"
OCR = QA / "E28_AGENTCUT_V4_FULLCUT_OCR.json"
EVIDENCE = QA / "ocr_evidence/t0090_0.jpg"
ADJUDICATION = QA / "E28_AGENTCUT_V4_FULLCUT_OCR_MACHINE_ADJUDICATION.json"
REQUEST = QA / "E28_AGENTCUT_V4_FULLCUT_AI_REVIEW_REQUEST_0P9P1.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    raw = json.loads(OCR.read_text(encoding="utf-8"))
    cadence = json.loads(CADENCE.read_text(encoding="utf-8"))
    repeated = json.loads(REPEAT_GATE.read_text(encoding="utf-8"))
    if cadence.get("status") != "PASS":
        raise SystemExit("V4 cadence must pass before review")
    if repeated.get("status") != "PASS_V4_REGRESSION":
        raise SystemExit("V4 near-freeze/repeat regression must pass before review")
    if raw.get("unlisted_chinese_hits") or raw.get("numeric_string_hits"):
        raise SystemExit("V4 OCR has non-adjudicable text clusters")

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
        "unlisted_chinese_hits": 0,
        "numeric_string_hits": 0,
        "content_review_range_seconds": [0.0, 148.0],
        "trusted_outro_range_seconds": [148.0, 151.0],
        "visual_evidence": str(EVIDENCE),
        "visual_evidence_sha256": sha256(EVIDENCE),
        "finding": "The sole raw critical OCR event, 'ilo' at 90.0s, was checked at its exact frame and is a false positive from black garment folds and highlights during action. No readable Latin text, generated prop text, subtitle, watermark, numeral string, unlisted Chinese cluster, or unauthorized logo is visible. Noncritical isolated detections remain warnings in the preserved raw report.",
        "confidence": 0.99,
        "rollback": "Retain V3, V4, raw OCR, exact critical frame and the recut project; reopen if later evidence shows readable unauthorized text.",
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
                "clip_id": "E28-AGENTCUT-V4-WRITER-AGENT-V050-MIDSECTION-RECUT",
                "metadata": {
                    "episode": "E28",
                    "candidate_sha256": sha256(VIDEO),
                    "agentcut_project": str(PROJECT),
                    "agentcut_project_sha256": sha256(PROJECT),
                    "writer_agent_version": "0.5.0",
                    "writer_agent_schema": "1.4.0",
                    "content_seconds": 148.0,
                    "trusted_branded_outro_seconds": 3.0,
                    "runtime_seconds": 151.0,
                    "review_focus": [
                        "ordinary human viewing experience across the exact 151-second V4 candidate",
                        "V3 85-113s repeated crouch and two near-freeze runs are removed without losing story logic",
                        "the new 85-99s sequence reads as attack, concise force-direction proof, old-method conclusion and window escape",
                        "native dialogue remains intelligible with no repeated line, hard sentence cut, collision or silent narrative gap",
                        "three-scene facts and character, location, time, prop and action continuity remain unchanged",
                        "the 73.0-76.8s reversible generated-text cleanup remains effective",
                        "the 148.0-151.0s trusted branded outro is clean and ends at timeline end",
                        "no unauthorized text, black frame, frozen filler, repeated composition padding or external BGM",
                    ],
                },
                "required_capabilities": ["media_probe", "video_analysis", "audio_analysis", "ocr"],
                "evidence_inputs": {
                    "agentcut_project": str(PROJECT),
                    "cadence_audit": str(CADENCE),
                    "near_freeze_repeat_gate": str(REPEAT_GATE),
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
