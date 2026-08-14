#!/usr/bin/env python3
"""Build E27 V5 from V3, retaining only the two motivated brightness bridges."""

from __future__ import annotations

import copy
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/e27_agentcut_project_v3_standard_storyboard_12slot_20260719.json"
OUT = ROOT / "configs/e27_agentcut_project_v5_b02_b05_brightness_only_20260720.json"
CUTAWAYS = {
    "B02": ROOT / "working_assets/e27_terminal_pacing_cutaways_v1_20260720/candidates/E27_E27-B02-PACING-CUTAWAY-02_5d6bda7e-f294-4c46-bb4a-442e1edde42e.mp4",
    "B05": ROOT / "working_assets/e27_terminal_pacing_cutaways_v1_20260720/candidates/E27_E27-B05-PACING-CUTAWAY-04_94290a70-2d34-496f-897a-01addb4e5241.mp4",
}


def segment(source: dict, clip_id: str, start: float, source_in: float, duration: float) -> dict:
    row = copy.deepcopy(source)
    row.update({"id": clip_id, "start": start, "in": source_in, "duration": duration})
    row.setdefault("metadata", {}).update({
        "cut_reason": "BRIGHTNESS_BRIDGE",
        "cut_reason_note": "Picture split preserves the admitted continuous dialogue track.",
    })
    return row


def insert(beat: str, start: float, purpose: str) -> dict:
    return {
        "id": f"E27-{beat}-BRIGHTNESS-BRIDGE-VIDEO",
        "source": str(CUTAWAYS[beat]),
        "start": start,
        "in": 1.0,
        "duration": 2.0,
        "metadata": {
            "episode": "E27",
            "source_id": f"{beat}-BRIGHTNESS-BRIDGE",
            "beat_id": beat,
            "source_qa": "PASS_OBJECTIVE_AND_VISUAL_ADJUDICATION",
            "visual_replacement_only": True,
            "audio_source_preserved": True,
            "cut_reason": "BRIGHTNESS_BRIDGE",
            "cut_reason_note": purpose,
        },
    }


def main() -> None:
    project = json.loads(BASE.read_text(encoding="utf-8"))
    project["metadata"].update({
        "status": "AGENTCUT_V5_B02_B05_BRIGHTNESS_ONLY_NOT_FINAL",
        "source_project": str(BASE),
        "rollback_from": "configs/e27_agentcut_project_v4_pacing_brightness_repair_20260720.json",
        "change_scope": "Retain only B02 and B05 luma bridges; roll back the nonessential B01 and B03 inserts that created new luma jumps.",
    })
    project["output"]["path"] = str(ROOT / "exports/e27/agentcut_v5_b02_b05_brightness_only_20260720/E27_AGENTCUT_V5_B02_B05_BRIGHTNESS_ONLY_NOT_FINAL.mp4")
    track = project["timeline"]["videoTracks"][0]
    by_id = {row["id"]: row for row in track["clips"]}
    replaced = {"E27-B02-P1-VIDEO", "E27-B02-P2-VIDEO", "E27-B05-P1-VIDEO", "E27-B05-P2-VIDEO"}
    clips = [row for row in track["clips"] if row["id"] not in replaced]

    b02p1, b02p2 = by_id["E27-B02-P1-VIDEO"], by_id["E27-B02-P2-VIDEO"]
    clips.extend([
        segment(b02p1, "E27-B02-P1-A-VIDEO", 24.0, 0.0, 11.0),
        insert("B02", 35.0, "Footwork insert bridges the B02 36-second luma discontinuity."),
        segment(b02p2, "E27-B02-P2-B-VIDEO", 37.0, 1.0, 11.0),
    ])

    b05p1, b05p2 = by_id["E27-B05-P1-VIDEO"], by_id["E27-B05-P2-VIDEO"]
    clips.extend([
        segment(b05p1, "E27-B05-P1-A-VIDEO", 96.0, 0.0, 11.0),
        insert("B05", 107.0, "Time-cord insert bridges the B05 108-second luma discontinuity."),
        segment(b05p2, "E27-B05-P2-B-VIDEO", 109.0, 1.0, 11.0),
    ])
    clips.sort(key=lambda row: float(row["start"]))
    track["clips"] = clips
    OUT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
