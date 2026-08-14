#!/usr/bin/env python3
"""Build E26 V5 by removing only the B06-P1 pure-black picture tail."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/e26_agentcut_project_v4_fight_tail_audio_repair_20260720.json"
OUT = ROOT / "configs/e26_agentcut_project_v5_b06_blackframe_repair_20260720.json"


def main() -> None:
    project = json.loads(BASE.read_text(encoding="utf-8"))
    project["metadata"].update({
        "status": "AGENTCUT_V5_B06_BLACKFRAME_REPAIR_NOT_FINAL",
        "source_project": str(BASE),
        "change_scope": "Trim the six decoded pure-black frames at the B06-P1 visual tail and extend B06-P2 picture coverage; preserve all admitted audio edits.",
    })
    project["output"]["path"] = str(
        ROOT
        / "exports/e26/agentcut_v5_b06_blackframe_repair_20260720/E26_AGENTCUT_V5_B06_BLACKFRAME_REPAIR_NOT_FINAL.mp4"
    )

    clips = project["timeline"]["videoTracks"][0]["clips"]
    by_id = {row["id"]: row for row in clips}
    b06p1 = by_id["E26-B06-P1-VIDEO"]
    b06p2 = by_id["E26-B06-P2-VIDEO"]
    b06p1["duration"] = 14.75
    b06p1.setdefault("metadata", {}).update({
        "tail_trim_reason": "Remove six decoded pure-black picture frames at 148.75-148.958s.",
    })
    b06p2.update({"start": 148.75, "in": 0.0, "duration": 14.75})
    b06p2.setdefault("metadata", {}).update({
        "picture_extension_reason": "Cover the trimmed B06-P1 picture interval without changing the audio boundary at 149.0s.",
    })

    OUT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
