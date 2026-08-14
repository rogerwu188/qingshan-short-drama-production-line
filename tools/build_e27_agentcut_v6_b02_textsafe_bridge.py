#!/usr/bin/env python3
"""Build E27 V6 by extending the admitted B02 bridge over pseudo-text frames."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/e27_agentcut_project_v5_b02_b05_brightness_only_20260720.json"
OUT = ROOT / "configs/e27_agentcut_project_v6_b02_textsafe_bridge_20260720.json"


def main() -> None:
    project = json.loads(BASE.read_text(encoding="utf-8"))
    project["metadata"].update({
        "status": "AGENTCUT_V6_B02_TEXTSAFE_BRIDGE_NOT_FINAL",
        "source_project": str(BASE),
        "change_scope": "Extend only the admitted B02 visual bridge across 34.0-37.0s to remove pseudo-readable energy strokes at 34.5s; preserve native dialogue audio.",
    })
    project["output"]["path"] = str(
        ROOT
        / "exports/e27/agentcut_v6_b02_textsafe_bridge_20260720/E27_AGENTCUT_V6_B02_TEXTSAFE_BRIDGE_NOT_FINAL.mp4"
    )

    clips = project["timeline"]["videoTracks"][0]["clips"]
    by_id = {row["id"]: row for row in clips}
    b02p1 = by_id["E27-B02-P1-A-VIDEO"]
    bridge = by_id["E27-B02-BRIGHTNESS-BRIDGE-VIDEO"]
    b02p1["duration"] = 10.0
    b02p1.setdefault("metadata", {})["tail_trim_reason"] = (
        "Remove pseudo-readable white energy strokes detected at 34.5s."
    )
    bridge.update({"start": 34.0, "in": 1.0, "duration": 3.0})
    bridge.setdefault("metadata", {})["cut_reason_note"] = (
        "Three-second text-safe footwork insert covers the B02 luma discontinuity and the isolated pseudo-text frame."
    )

    OUT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
