#!/usr/bin/env python3
"""Build E27 V7 with only the admitted B02-P1 and B04-P1 pictures replaced."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/e27_agentcut_project_v6_b02_textsafe_bridge_20260720.json"
OUT = ROOT / "configs/e27_agentcut_project_v7_human_gate_source_repair_20260720.json"
B02 = ROOT / "working_assets/e26_e27_human_gate_failed_only_videos_r1_20260720/candidates/E26_E27_E27-B02-P1-STANDARD-STORYBOARD-V1-HUMAN-GATE-R1_5ed92cd3-f656-4045-9edf-c58c2dbd45ec.mp4"
B04 = ROOT / "working_assets/e26_e27_human_gate_failed_only_videos_r1_20260720/candidates/E26_E27_E27-B04-P1-STANDARD-STORYBOARD-V1-HUMAN-GATE-R1_c98b1156-730c-4b85-9eb2-f8ef4d478d74.mp4"


def main() -> None:
    project = json.loads(BASE.read_text(encoding="utf-8"))
    project["metadata"].update({
        "status": "AGENTCUT_V7_HUMAN_GATE_SOURCE_REPAIR_NOT_FINAL",
        "source_project": str(BASE),
        "change_scope": "Replace only E27 B02-P1 and B04-P1 picture sources after machine human-viewing FAIL; preserve accepted audio and every other admitted picture edit.",
    })
    project["output"]["path"] = str(
        ROOT / "exports/e27/agentcut_v7_human_gate_source_repair_20260720/E27_AGENTCUT_V7_HUMAN_GATE_SOURCE_REPAIR_NOT_FINAL.mp4"
    )
    clips = {clip["id"]: clip for clip in project["timeline"]["videoTracks"][0]["clips"]}
    clips["E27-B02-P1-A-VIDEO"]["source"] = str(B02)
    clips["E27-B04-P1-VIDEO"]["source"] = str(B04)
    for clip in (clips["E27-B02-P1-A-VIDEO"], clips["E27-B04-P1-VIDEO"]):
        clip.setdefault("metadata", {}).update({
            "source_qa": "PASS_CADENCE_AND_OCR",
            "visual_replacement_only": True,
            "audio_source_preserved": True,
            "human_gate_repair_receipt": "workflow/tasks/E26_E27_HUMAN_GATE_FAILED_ONLY_VIDEO_BATCH_R1_RECEIPT_20260720.json",
        })
    OUT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
