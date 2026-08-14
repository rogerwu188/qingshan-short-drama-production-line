#!/usr/bin/env python3
"""Build E27 V8 by replacing only B04 P2 with a local opening-luma repair."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/e27_agentcut_project_v7_human_gate_source_repair_20260720.json"
OUT = ROOT / "configs/e27_agentcut_project_v8_b04_luma_ramp_20260720.json"
REPAIRED = ROOT / "working_assets/e27_b04_p2_luma_ramp_v1_20260720/E27_B04_P2_OPENING_LUMA_RAMP_V1.mp4"


def main() -> None:
    if not REPAIRED.exists():
        raise SystemExit(f"missing repaired source: {REPAIRED}")
    project = json.loads(BASE.read_text(encoding="utf-8"))
    project["metadata"].update({
        "status": "AGENTCUT_V8_B04_LUMA_RAMP_NOT_FINAL",
        "source_project": str(BASE),
        "rollback_from": str(BASE.relative_to(ROOT)),
        "change_scope": "Replace only B04 P2 picture with a 2-second opening luma ramp; preserve timing, dialogue audio, order, and all admitted sibling sources.",
    })
    project["output"]["path"] = str(
        ROOT / "exports/e27/agentcut_v8_b04_luma_ramp_20260720/E27_AGENTCUT_V8_B04_LUMA_RAMP_NOT_FINAL.mp4"
    )
    changed = 0
    for clip in project["timeline"]["videoTracks"][0]["clips"]:
        if clip.get("id") != "E27-B04-P2-VIDEO":
            continue
        clip["source"] = str(REPAIRED)
        clip.setdefault("metadata", {}).update({
            "visual_replacement_only": True,
            "audio_source_preserved": True,
            "luma_repair": {
                "kind": "OPENING_RAMP",
                "seconds": 2.0,
                "brightness_start": 0.16,
                "brightness_end": 0.0,
                "reason": "Match the preceding B04 P1 end luma without changing scene, performance, timing, or story content.",
            },
        })
        changed += 1
    if changed != 1:
        raise SystemExit(f"expected one B04 P2 clip, changed {changed}")
    OUT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
