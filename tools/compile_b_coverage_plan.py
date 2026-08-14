#!/usr/bin/env python3
"""Compile missing dialogue B coverage into the smallest honest source batch."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


FIXED_NEGATIVE = (
    "hunched posture, sloped shoulders, forward head, oversized cat, giant cat, "
    "cat closer to camera than humans, modern police uniform, peaked cap, epaulettes, "
    "Republic of China era, suitcase, briefcase, modern signage, English letters, "
    "Latin letters, readable generated Chinese, central bold dialogue text, slow motion, "
    "dreamy pace, floating, weightless"
)


def chunks(items: list[dict], size: int = 2) -> list[list[dict]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--coverage", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    source = Path(args.coverage).resolve()
    out = Path(args.out).resolve()
    payload = json.loads(source.read_text(encoding="utf-8"))
    missing = [beat for beat in payload["beats"] if beat["B"]["status"] == "MISSING_SOURCE"]

    grouped: dict[tuple[str, str, str, str], list[dict]] = defaultdict(list)
    for beat in missing:
        grouped[(beat["scene_id"], beat["listener"], beat["axis_line"], beat["light_key"])].append(beat)

    clips = []
    clip_index = 1
    for (scene_id, listener, axis_line, light_key), beats in grouped.items():
        for pair in chunks(beats):
            beat_ids = [beat["dialogue_beat_id"] for beat in pair]
            reactions = [beat["listener_reaction"] for beat in pair]
            eyeline = pair[0]["eyeline_b"]
            clips.append(
                {
                    "coverage_source_id": f"E16-B{clip_index:02d}",
                    "serves_dialogue_beats": beat_ids,
                    "max_final_uses": 2,
                    "scene_id": scene_id,
                    "listener": listener,
                    "coverage": "listener_reaction",
                    "axis_line": axis_line,
                    "eyeline": eyeline,
                    "light_key": light_key,
                    "reaction_arc": reactions,
                    "duration_seconds": 4,
                    "camera": {
                        "lens_mm": 85,
                        "angle": "eye level",
                        "depth": "listener on the established dialogue plane; never closer than the speaking subject without an explicit OTS",
                    },
                    "scale_and_posture": {
                        "chenji_height_cm": 182,
                        "human_frame_occupancy": "0.55-0.72 for a reaction medium/close shot",
                        "chenji_posture": "upright spine, open shoulders, level chin, calm controlled confidence",
                        "wuyun_if_present": "four-footed natural cat, shoulder height 0.16 of Chenji, head 0.33 of Chenji head, same plane or behind humans",
                    },
                    "motion": "one continuous real-time reaction change; no speaking; no frozen stare; no second action unit",
                    "positive_speed": "real-time speed, no slow motion",
                    "negative_prompt": FIXED_NEGATIVE,
                    "status": "PLANNED_NO_SOURCE",
                }
            )
            clip_index += 1

    result = {
        "schema": "qingshan.b_coverage_batch.v1",
        "episode": payload["episode"],
        "source_coverage": str(source),
        "strategy": "Group only identical scene/listener/axis/light combinations and serve at most two dialogue beats from one evolving reaction source.",
        "missing_dialogue_beats": len(missing),
        "planned_new_sources": len(clips),
        "source_reuse_limit": 2,
        "status": "PLANNED_NOT_GENERATED",
        "clips": clips,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(out), "missing_beats": len(missing), "planned_sources": len(clips)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
