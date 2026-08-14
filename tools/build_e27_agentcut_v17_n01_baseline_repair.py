#!/usr/bin/env python3
"""Build E27 V17 by replacing the cadence-failing N01 source only."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path("/Users/rogerwu/qingshan_short_drama")
BASE = ROOT / "configs/e27_agentcut_project_v16_writer_agent_v040_release_candidate_20260720.json"
N01 = ROOT / "working_assets/e27_writer_agent_v040_video_v1_20260720/candidates/E27_E27-N01-WRITER-AGENT-V040-VIDEO-V1_5e2731ff-75dd-47bd-81ce-00635de94e49.mp4"
N01_CADENCE = ROOT / "qa/e27_writer_agent_v040_video_v1_20260720/E27-N01-WRITER-AGENT-V040-VIDEO-V1_frame_cadence.json"
N01_OCR = ROOT / "qa/e27_writer_agent_v040_video_v1_20260720/E27-N01-WRITER-AGENT-V040-VIDEO-V1_ocr.json"
PROJECT = ROOT / "configs/e27_agentcut_project_v17_n01_baseline_repair_20260720.json"
OUTPUT = ROOT / "exports/e27/agentcut_v17_n01_baseline_repair_20260720/E27_AGENTCUT_V17_N01_BASELINE_REPAIR_NOT_FINAL.mp4"
RECEIPT = ROOT / "workflow/tasks/E27_AGENTCUT_V17_N01_BASELINE_REPAIR_BUILD_RECEIPT_20260720.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_pass(path: Path, label: str) -> None:
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("status") != "PASS":
        raise SystemExit(f"{label} is not PASS: {path}")


def main() -> int:
    for path in (BASE, N01, N01_CADENCE, N01_OCR):
        if not path.is_file():
            raise SystemExit(f"missing input: {path}")
    require_pass(N01_CADENCE, "N01 cadence")
    require_pass(N01_OCR, "N01 OCR")

    project = json.loads(BASE.read_text(encoding="utf-8"))
    clips = project["timeline"]["videoTracks"][0]["clips"]
    matches = [clip for clip in clips if clip.get("metadata", {}).get("shot_id") == "E27-N01"]
    if len(matches) != 1:
        raise SystemExit(f"expected one E27-N01 clip, found {len(matches)}")
    clip = matches[0]
    old_source = clip["source"]
    old_sha256 = clip["metadata"]["source_sha256"]
    clip["source"] = str(N01)
    clip["metadata"].update(
        {
            "source_sha256": sha256(N01),
            "source_variant": "V040_VIDEO_V1_BASELINE",
            "source_admission": "DIRECT_PASS",
            "source_admission_confidence": 1.0,
            "repair_reason": "CL2X-467_N01_PER_SHOT_CADENCE_FAIL_ROLLBACK",
            "cadence_evidence": str(N01_CADENCE),
            "cadence_evidence_sha256": sha256(N01_CADENCE),
            "ocr_evidence": str(N01_OCR),
            "ocr_evidence_sha256": sha256(N01_OCR),
        }
    )
    project["output"]["path"] = str(OUTPUT)
    project["metadata"].update(
        {
            "status": "AGENTCUT_V17_POST_RELEASE_REPAIR_QA_PENDING",
            "base_project": str(BASE),
            "base_project_sha256": sha256(BASE),
            "repair_scope": ["E27-N01"],
            "preserved_shots": 23,
            "supervisor_instruction": "CL2X-467",
        }
    )
    PROJECT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    receipt = {
        "schema": "qingshan.agentcut_post_release_repair.v1",
        "episode": "E27",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "READY_VALIDATE_COMPILE_RENDER_FULL_CUT_VISUAL_QA",
        "project": str(PROJECT),
        "project_sha256": sha256(PROJECT),
        "output": str(OUTPUT),
        "replacement_shot": "E27-N01",
        "old_source": old_source,
        "old_source_sha256": old_sha256,
        "new_source": str(N01),
        "new_source_sha256": sha256(N01),
        "new_source_cadence_status": "PASS",
        "new_source_ocr_status": "PASS",
        "preserved_shots": 23,
        "remote_credit": 0,
        "remote_credit_reason": "LOCAL_DETERMINISTIC_AGENTCUT_REPAIR",
    }
    RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "project": str(PROJECT), "output": str(OUTPUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
