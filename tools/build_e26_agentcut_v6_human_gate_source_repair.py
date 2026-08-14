#!/usr/bin/env python3
"""Build E26 V6 with only the admitted B06 picture sources replaced."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/e26_agentcut_project_v5_b06_blackframe_repair_20260720.json"
OUT = ROOT / "configs/e26_agentcut_project_v6_human_gate_source_repair_20260720.json"
P1 = ROOT / "working_assets/e26_e27_human_gate_failed_only_videos_r1_20260720/candidates/E26_E27_E26-B06-P1-STANDARD-STORYBOARD-V1-HUMAN-GATE-R1_7c688089-9a83-44e1-92f3-6e88435b50e7.mp4"
P2 = ROOT / "working_assets/e26_e27_human_gate_failed_only_videos_r1_20260720/candidates/E26_E27_E26-B06-P2-STANDARD-STORYBOARD-V1-HUMAN-GATE-R1_032b5ec9-fcae-4791-9697-421b8ad9d5ab.mp4"


def main() -> None:
    project = json.loads(BASE.read_text(encoding="utf-8"))
    project["metadata"].update({
        "status": "AGENTCUT_V6_HUMAN_GATE_SOURCE_REPAIR_NOT_FINAL",
        "source_project": str(BASE),
        "change_scope": "Replace only E26 B06-P1/P2 picture sources after machine human-viewing FAIL; preserve the accepted audio tracks and all B01-B05 edits.",
    })
    project["output"]["path"] = str(
        ROOT / "exports/e26/agentcut_v6_human_gate_source_repair_20260720/E26_AGENTCUT_V6_HUMAN_GATE_SOURCE_REPAIR_NOT_FINAL.mp4"
    )
    clips = {clip["id"]: clip for clip in project["timeline"]["videoTracks"][0]["clips"]}
    clips["E26-B06-P1-VIDEO"]["source"] = str(P1)
    clips["E26-B06-P2-VIDEO"]["source"] = str(P2)
    for clip in (clips["E26-B06-P1-VIDEO"], clips["E26-B06-P2-VIDEO"]):
        clip.setdefault("metadata", {}).update({
            "source_qa": "PASS_CADENCE_AND_MACHINE_VISUAL_OCR_ADJUDICATION",
            "visual_replacement_only": True,
            "audio_source_preserved": True,
            "human_gate_repair_receipt": "workflow/tasks/E26_E27_HUMAN_GATE_FAILED_ONLY_VIDEO_BATCH_R1_RECEIPT_20260720.json",
        })
    OUT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
