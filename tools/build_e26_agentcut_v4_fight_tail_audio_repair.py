#!/usr/bin/env python3
"""Build E26 AgentCut V4 from the admitted V3 timeline and four QA-passed inserts."""

from __future__ import annotations

import copy
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/e26_agentcut_project_v3_standard_storyboard_12slot_20260719.json"
OUT = ROOT / "configs/e26_agentcut_project_v4_fight_tail_audio_repair_20260720.json"

CUTAWAYS = [
    ROOT / "working_assets/e26_b04_fight_cutaways_v1_failed_only_r1_20260720/candidates/E26_E26-B04-CUTAWAY-01-CADENCE-OCR-R1_cf2e1ac4-b92b-495b-8365-0c3ee7b24a28.mp4",
    ROOT / "working_assets/e26_b04_fight_cutaways_v1_20260719/candidates/E26_E26-B04-CUTAWAY-02_c1c9066f-595e-418d-a029-ac1a9e0d3d42.mp4",
    ROOT / "working_assets/e26_b04_fight_cutaways_v1_20260719/candidates/E26_E26-B04-CUTAWAY-03_d6c51ed2-d7a6-49a8-a461-2864a185bd47.mp4",
    ROOT / "working_assets/e26_b04_fight_cutaways_v1_20260719/candidates/E26_E26-B04-CUTAWAY-04_6b947a0f-1730-4fba-98cf-22ac43d64506.mp4",
]


def segment(source: dict, clip_id: str, start: float, source_in: float, duration: float) -> dict:
    row = copy.deepcopy(source)
    row.update({"id": clip_id, "start": start, "in": source_in, "duration": duration})
    row.setdefault("metadata", {}).update({
        "cut_reason": "ACTION_CONTINUITY",
        "cut_reason_note": "Native dialogue remains continuous while picture pacing is repaired.",
    })
    return row


def insert(index: int, start: float) -> dict:
    return {
        "id": f"E26-B04-FIGHT-CUTAWAY-{index + 1:02d}-VIDEO",
        "source": str(CUTAWAYS[index]),
        "start": start,
        "in": 1.0,
        "duration": 2.0,
        "metadata": {
            "episode": "E26",
            "source_id": f"B04-CUTAWAY-{index + 1:02d}",
            "beat_id": "B04",
            "source_qa": "PASS_OBJECTIVE_AND_VISUAL_ADJUDICATION",
            "visual_replacement_only": True,
            "audio_source_preserved": True,
            "cut_reason": "ACTION_INSERT",
            "cut_reason_note": "QA-passed native-speed fight insert; admitted dialogue audio continues underneath.",
        },
    }


def main() -> None:
    project = json.loads(BASE.read_text(encoding="utf-8"))
    project["metadata"].update({
        "status": "AGENTCUT_V4_FIGHT_TAIL_AUDIO_REPAIR_NOT_FINAL",
        "runtime_seconds": 163.5,
        "change_scope": "Insert four QA-passed B04 action cutaways, trim the final 0.5-second black tail, and bridge the B05-P2 native audio-bed hole without replacing dialogue.",
        "source_project": str(BASE),
    })
    project["output"]["path"] = str(ROOT / "exports/e26/agentcut_v4_fight_tail_audio_repair_20260720/E26_AGENTCUT_V4_FIGHT_TAIL_AUDIO_REPAIR_NOT_FINAL.mp4")

    track = project["timeline"]["videoTracks"][0]
    by_id = {clip["id"]: clip for clip in track["clips"]}
    rebuilt = []
    for clip in track["clips"]:
        if clip["id"] not in {"E26-B04-P1-VIDEO", "E26-B04-P2-VIDEO"}:
            rebuilt.append(clip)
    p1 = by_id["E26-B04-P1-VIDEO"]
    p2 = by_id["E26-B04-P2-VIDEO"]
    rebuilt.extend([
        segment(p1, "E26-B04-P1-A-VIDEO", 74.0, 0.0, 3.0),
        insert(0, 77.0),
        segment(p1, "E26-B04-P1-B-VIDEO", 79.0, 5.0, 4.0),
        insert(1, 83.0),
        segment(p1, "E26-B04-P1-C-VIDEO", 85.0, 11.0, 4.0),
        segment(p2, "E26-B04-P2-A-VIDEO", 89.0, 0.0, 3.0),
        insert(2, 92.0),
        segment(p2, "E26-B04-P2-B-VIDEO", 94.0, 5.0, 5.0),
        insert(3, 99.0),
        segment(p2, "E26-B04-P2-C-VIDEO", 101.0, 12.0, 3.0),
    ])
    rebuilt.sort(key=lambda row: float(row["start"]))
    for clip in rebuilt:
        if clip["id"] == "E26-B06-P2-VIDEO":
            clip["duration"] = 14.5
            clip.setdefault("metadata", {})["tail_trim_reason"] = "Remove ten decoded pure-black tail frames without padding."
    track["clips"] = rebuilt

    for audio_track in project["timeline"].get("audioTracks", []):
        for clip in audio_track.get("clips", []):
            if clip["id"] == "E26-B06-P2-AUDIO":
                clip["duration"] = 14.5
    project["timeline"]["audioTracks"].append({
        "id": "E26_NATIVE_AMBIENCE_REPAIR",
        "clips": [{
            "id": "E26-B05-P2-NATIVE-AMBIENCE-BRIDGE",
            "source": str(CUTAWAYS[1]),
            "start": 119.0,
            "in": 0.5,
            "duration": 2.5,
            "volume": 0.10,
            "transitionIn": {"type": "fade", "duration": 0.35},
            "transitionOut": {"type": "fade", "duration": 0.35},
            "metadata": {
                "episode": "E26",
                "beat_id": "B05",
                "kind": "NATIVE_SCENE_AMBIENCE",
                "speech_free": True,
                "source_prompt_declares_no_speech": True,
                "repair_reason": "Bridge 119.0-121.5s native audio-bed dropout while preserving the B05-P2 dialogue track.",
            },
        }],
    })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
