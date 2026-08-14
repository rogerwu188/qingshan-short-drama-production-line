#!/usr/bin/env python3
"""Build E27 AgentCut V4 with four admitted picture-only pacing inserts."""

from __future__ import annotations

import copy
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/e27_agentcut_project_v3_standard_storyboard_12slot_20260719.json"
OUT = ROOT / "configs/e27_agentcut_project_v4_pacing_brightness_repair_20260720.json"
CUTAWAYS = {
    "B01": ROOT / "working_assets/e27_terminal_pacing_cutaway_b01_failed_only_r1_20260720/candidates/E27_E27-B01-PACING-CUTAWAY-01-TEXTPROP-R1_167978ec-46a1-45c3-95a1-9acf0d988527.mp4",
    "B02": ROOT / "working_assets/e27_terminal_pacing_cutaways_v1_20260720/candidates/E27_E27-B02-PACING-CUTAWAY-02_5d6bda7e-f294-4c46-bb4a-442e1edde42e.mp4",
    "B03": ROOT / "working_assets/e27_terminal_pacing_cutaways_v1_20260720/candidates/E27_E27-B03-PACING-CUTAWAY-03_b853f498-6b36-4857-945b-0b3fe7b58bf1.mp4",
    "B05": ROOT / "working_assets/e27_terminal_pacing_cutaways_v1_20260720/candidates/E27_E27-B05-PACING-CUTAWAY-04_94290a70-2d34-496f-897a-01addb4e5241.mp4",
}


def segment(source: dict, clip_id: str, start: float, source_in: float, duration: float) -> dict:
    row = copy.deepcopy(source)
    row.update({"id": clip_id, "start": start, "in": source_in, "duration": duration})
    row.setdefault("metadata", {}).update({
        "cut_reason": "PACING_OR_BRIGHTNESS_BRIDGE",
        "cut_reason_note": "Picture split preserves the admitted continuous dialogue track.",
    })
    return row


def insert(beat: str, start: float, purpose: str) -> dict:
    return {
        "id": f"E27-{beat}-PACING-INSERT-VIDEO",
        "source": str(CUTAWAYS[beat]),
        "start": start,
        "in": 1.0,
        "duration": 2.0,
        "metadata": {
            "episode": "E27",
            "source_id": f"{beat}-PACING-INSERT",
            "beat_id": beat,
            "source_qa": "PASS_OBJECTIVE_AND_VISUAL_ADJUDICATION",
            "visual_replacement_only": True,
            "audio_source_preserved": True,
            "cut_reason": "EVIDENCE_OR_REACTION_INSERT",
            "cut_reason_note": purpose,
        },
    }


def main() -> None:
    project = json.loads(BASE.read_text(encoding="utf-8"))
    project["metadata"].update({
        "status": "AGENTCUT_V4_PACING_BRIGHTNESS_REPAIR_NOT_FINAL",
        "source_project": str(BASE),
        "change_scope": "Use four admitted picture-only inserts to lower long-shot cadence and bridge the B02/B05 luma discontinuities without changing dialogue audio or narrative order.",
    })
    project["output"]["path"] = str(ROOT / "exports/e27/agentcut_v4_pacing_brightness_repair_20260720/E27_AGENTCUT_V4_PACING_BRIGHTNESS_REPAIR_NOT_FINAL.mp4")
    track = project["timeline"]["videoTracks"][0]
    by_id = {row["id"]: row for row in track["clips"]}
    replaced = {
        "E27-B01-P1-VIDEO", "E27-B02-P1-VIDEO", "E27-B02-P2-VIDEO",
        "E27-B03-P2-VIDEO", "E27-B05-P1-VIDEO", "E27-B05-P2-VIDEO",
    }
    clips = [row for row in track["clips"] if row["id"] not in replaced]
    b01 = by_id["E27-B01-P1-VIDEO"]
    clips.extend([
        segment(b01, "E27-B01-P1-A-VIDEO", 0.0, 0.0, 6.0),
        insert("B01", 6.0, "Text-free cloth evidence insert; raw OCR texture false-positive independently adjudicated."),
        segment(b01, "E27-B01-P1-B-VIDEO", 8.0, 8.0, 4.0),
    ])
    b02p1, b02p2 = by_id["E27-B02-P1-VIDEO"], by_id["E27-B02-P2-VIDEO"]
    clips.extend([
        segment(b02p1, "E27-B02-P1-A-VIDEO", 24.0, 0.0, 11.0),
        insert("B02", 35.0, "Footwork insert bridges the exterior-to-interior luma boundary at 36 seconds."),
        segment(b02p2, "E27-B02-P2-B-VIDEO", 37.0, 1.0, 11.0),
    ])
    b03 = by_id["E27-B03-P2-VIDEO"]
    clips.extend([
        segment(b03, "E27-B03-P2-A-VIDEO", 60.0, 0.0, 6.0),
        insert("B03", 66.0, "Black-cat archive evidence insert breaks the static information hold."),
        segment(b03, "E27-B03-P2-B-VIDEO", 68.0, 8.0, 4.0),
    ])
    b05p1, b05p2 = by_id["E27-B05-P1-VIDEO"], by_id["E27-B05-P2-VIDEO"]
    clips.extend([
        segment(b05p1, "E27-B05-P1-A-VIDEO", 96.0, 0.0, 11.0),
        insert("B05", 107.0, "Time-cord realization insert bridges the closeup-to-corridor luma boundary at 108 seconds."),
        segment(b05p2, "E27-B05-P2-B-VIDEO", 109.0, 1.0, 11.0),
    ])
    clips.sort(key=lambda row: float(row["start"]))
    track["clips"] = clips
    OUT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
