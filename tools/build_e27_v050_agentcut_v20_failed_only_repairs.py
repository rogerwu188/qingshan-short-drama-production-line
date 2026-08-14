#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path


ROOT = Path("/Users/rogerwu/qingshan_short_drama")
BASE = ROOT / "configs/e27_agentcut_v19_writer_agent_v050_release_candidate_20260720.json"
PROJECT = ROOT / "configs/e27_agentcut_v20_writer_agent_v050_failed_only_repairs_20260721.json"
OUTPUT = ROOT / "exports/e27/agentcut_v20_writer_agent_v050_failed_only_repairs_20260721/E27_AGENTCUT_V20_WRITER_AGENT_V050_FAILED_ONLY_REPAIRS_CANDIDATE.mp4"
RECEIPT = ROOT / "workflow/tasks/E27_AGENTCUT_V20_FAILED_ONLY_REPAIRS_BUILD_RECEIPT_20260721.json"

REPAIRS = {
    "E27-B02-U01": {
        "path": ROOT / "working_assets/e27_v050_failed_only_identity_text_r1_20260721/candidates/E27_E27-B02-U01-ENTITY-REFERENCE-V050-FAILED-ONLY-R1_586006ae-721e-4ab5-ace1-db5952a4b12d.mp4",
        "cadence": ROOT / "qa/e27_v050_failed_only_identity_text_r1_20260721/E27-B02-U01-ENTITY-REFERENCE-V050-FAILED-ONLY-R1_frame_cadence.json",
        "ocr": ROOT / "qa/e27_v050_failed_only_identity_text_r1_20260721/E27-B02-U01-ENTITY-REFERENCE-V050-FAILED-ONLY-R1_ocr.json",
        "reason": "Failed-only identity and motif repair R1; batch QA PASS.",
    },
    "E27-B05-U02": {
        "path": ROOT / "working_assets/e27_v050_failed_only_identity_text_r1_20260721/candidates/E27_E27-B05-U02-ENTITY-REFERENCE-V050-FAILED-ONLY-R1_5444f0b5-17f0-41b6-9f0f-98060e3a48a0.mp4",
        "cadence": ROOT / "qa/e27_v050_failed_only_identity_text_r1_20260721/E27-B05-U02-ENTITY-REFERENCE-V050-FAILED-ONLY-R1_frame_cadence.json",
        "ocr": ROOT / "qa/e27_v050_failed_only_identity_text_r1_20260721/E27-B05-U02-ENTITY-REFERENCE-V050-FAILED-ONLY-R1_ocr.json",
        "reason": "Failed-only readable-text and identity repair R1; batch QA PASS.",
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    project = json.loads(BASE.read_text(encoding="utf-8"))
    applied = []

    for key, repair in REPAIRS.items():
        source = repair["path"]
        if not source.is_file():
            raise SystemExit(f"missing repair candidate: {source}")
        for evidence_key in ("cadence", "ocr"):
            if not repair[evidence_key].is_file():
                raise SystemExit(f"missing repair evidence: {repair[evidence_key]}")

        source_sha = sha256(source)
        matched_video = False
        matched_audio = False
        for track in project["timeline"]["videoTracks"]:
            for clip in track["clips"]:
                if clip["id"] != f"{key}-VIDEO":
                    continue
                clip["source"] = str(source)
                clip["metadata"].update({
                    "source_sha256": source_sha,
                    "source_variant": "WRITER_AGENT_V050_FAILED_ONLY_R1",
                    "source_admission": "PASS_FAILED_ONLY_R1_BATCH_QA",
                    "source_admission_confidence": 0.95,
                    "cadence_report_path": str(repair["cadence"]),
                    "ocr_report_path": str(repair["ocr"]),
                    "failed_only_repair_evidence": repair["reason"],
                })
                matched_video = True
        for track in project["timeline"]["audioTracks"]:
            for clip in track["clips"]:
                if clip["id"] != f"{key}-AUDIO":
                    continue
                clip["source"] = str(source)
                clip["metadata"].update({
                    "source_sha256": source_sha,
                    "source_variant": "WRITER_AGENT_V050_FAILED_ONLY_R1",
                    "source_admission": "PASS_FAILED_ONLY_R1_BATCH_QA",
                })
                matched_audio = True
        if not matched_video or not matched_audio:
            raise SystemExit(f"missing AgentCut clips for {key}: video={matched_video} audio={matched_audio}")
        applied.append({"key": key, "path": str(source), "sha256": source_sha})

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    project["output"]["path"] = str(OUTPUT)
    project["metadata"].update({
        "status": "V20_WRITER_AGENT_V050_FAILED_ONLY_REPAIRS_FINAL_QA_PENDING",
        "platformUploadAllowed": False,
        "base_project": str(BASE),
        "base_project_sha256": sha256(BASE),
        "failed_only_repair_count": len(applied),
    })
    project["qingshanAudit"].update({
        "pipelineStage": "WRITER_AGENT_V050_FAILED_ONLY_REPAIRS_FULLCUT",
        "final": False,
        "platformUploadAllowed": False,
        "failedOnlyRepairCount": len(applied),
    })
    PROJECT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    receipt = {
        "schema": "qingshan.agentcut.failed-only-repairs-build.v1",
        "episode": "E27",
        "status": "BUILT_NOT_RENDERED",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "base_project": str(BASE),
        "base_project_sha256": sha256(BASE),
        "project": str(PROJECT),
        "project_sha256": sha256(PROJECT),
        "output": str(OUTPUT),
        "repairs": applied,
        "platformUploadAllowed": False,
    }
    RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    main()
