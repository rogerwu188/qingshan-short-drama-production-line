#!/usr/bin/env python3
"""Replace E27 B03 P2 with verified text-free source intervals only."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/e27_agentcut_project_v10_b03_textfree_visual_20260720.json"
OUT = ROOT / "configs/e27_agentcut_project_v11_b03_textfree_segments_20260720.json"
PRIMARY = ROOT / "working_assets/e27_standard_storyboard_v4_sheetbound_20260719/candidates/E27_E27-B03-P2-STANDARD-STORYBOARD-V1-R1B-FAILED-ONLY-R2B-FAILED-ONLY-OCR-SAFE-R3B_5c0d7085-8b8b-4da6-b865-da8e81c78c53.mp4"
REACTION = ROOT / "working_assets/e27_standard_storyboard_v1_20260719/candidates/E27_E27-B03-P2-STANDARD-STORYBOARD-V1_4b9d525c-dab1-4499-978a-d379250d296d.mp4"
REPAIRED = ROOT / "working_assets/e27_b03_p2_textfree_visual_v3_20260720/E27_B03_P2_TEXTFREE_VISUAL_V3.mp4"


def main() -> None:
    for source in (BASE, PRIMARY, REACTION):
        if not source.exists():
            raise SystemExit(f"missing source: {source}")
    REPAIRED.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y", "-i", str(PRIMARY), "-i", str(REACTION),
        "-filter_complex",
        (
            "[0:v]trim=start=0:end=4.5,setpts=PTS-STARTPTS[p];"
            "[1:v]trim=start=0:end=2,setpts=1.25*(PTS-STARTPTS)[r0];"
            "[1:v]trim=start=5:end=7,setpts=1.25*(PTS-STARTPTS)[r1];"
            "[1:v]trim=start=10:end=12,setpts=1.25*(PTS-STARTPTS)[r2];"
            "[p][r0][r1][r2]concat=n=4:v=1:a=0,format=yuv420p[v]"
        ),
        "-map", "[v]", "-an", "-r", "24", "-c:v", "libx264", "-crf", "16",
        "-preset", "medium", "-movflags", "+faststart", str(REPAIRED),
    ], check=True)

    project = json.loads(BASE.read_text(encoding="utf-8"))
    project["metadata"].update({
        "status": "AGENTCUT_V11_B03_TEXTFREE_SEGMENTS_NOT_FINAL",
        "source_project": str(BASE),
        "rollback_from": str(BASE.relative_to(ROOT)),
        "change_scope": (
            "Replace B03 P2 paper-text intervals with machine-inspected text-free "
            "corridor and reaction intervals; preserve original dialogue audio and runtime."
        ),
    })
    project["output"]["path"] = str(
        ROOT / "exports/e27/agentcut_v11_b03_textfree_segments_20260720/E27_AGENTCUT_V11_B03_TEXTFREE_SEGMENTS_NOT_FINAL.mp4"
    )
    changed = 0
    for clip in project["timeline"]["videoTracks"][0]["clips"]:
        if clip.get("id") != "E27-B03-P2-VIDEO":
            continue
        clip["source"] = str(REPAIRED)
        clip.setdefault("metadata", {})["text_removal_repair"] = {
            "kind": "VERIFIED_TEXT_FREE_INTERVAL_REPLACEMENT_V3",
            "primary_seconds": [[0.0, 4.5]],
            "reaction_seconds": [[0.0, 2.0], [5.0, 7.0], [10.0, 12.0]],
            "reaction_speed_factor": 0.8,
            "excluded_observer_readable_text_seconds": [[2.0, 5.0], [7.0, 10.0]],
            "evidence_contact_sheet": str(
                ROOT / "qa/e27_b03_p2_reaction_source_inspection_20260720/reaction_contact.jpg"
            ),
            "audio_source_preserved": True,
        }
        changed += 1
    if changed != 1:
        raise SystemExit(f"expected one B03 P2 video clip, changed {changed}")
    OUT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
