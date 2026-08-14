#!/usr/bin/env python3
"""Normalise the project's several edit-plan formats into AgentCut clip shape.

Only E18R and E19R were cut with AgentCut. E16 used an ordered EDL
(`segments[]` with `a_source_id` + `b_insert`) and E17 a scene timeline, so the
cut-motivation gate could not be run on them without a translation layer.

Honesty note on what this can and cannot recover: the adapter maps structure,
never invents intent. Where a source format has no field in which a cut reason
could be recorded, the adapter leaves `cut_reason` absent — and that absence is
itself the finding, not an artifact of the conversion. E16's `b_insert` carries
`source_id / video_path / duration / counted_duration_estimate / placement /
listener`; there is nowhere to say why the cut exists.

Outputs an AgentCut-shaped project so `cut_motivation_gate.py` can read it.
The adapter is strict: a source plan without explicit motivation and
continuity metadata is rejected instead of receiving a fabricated default.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from tools.cut_motivation_gate import required_cut_metadata
except ModuleNotFoundError:  # direct `python tools/edit_plan_adapter.py`
    from cut_motivation_gate import required_cut_metadata


def from_ordered_edl(plan: dict, diagnostic: bool = False) -> dict:
    """E16 form: segments[] each carrying an A shot and an optional B insert."""
    clips: list[dict] = []
    cursor = 0.0
    evidence_fields = (
        "new_information", "action", "emotion_delta", "space_id", "shot_size",
        "composition_note", "insert_reason", "cut_reason_note",
    )
    for index, segment in enumerate(plan.get("segments", [])):
        a_duration = float(segment.get("target_duration") or 0.0)
        clips.append(
            {
                "id": f"A-{index:03d}",
                "source": segment.get("a_video_path") or segment.get("a_source_id") or "",
                "start": round(cursor, 6),
                "duration": a_duration,
                "metadata": {
                    **(segment.get("metadata") or {}),
                    "shot_index": index,
                    "dialogue_id": segment.get("dialogue_id"),
                    "speaker": segment.get("speaker"),
                    "coverage_group": "A",
                    **{key: segment[key] for key in evidence_fields if key in segment},
                    **required_cut_metadata(segment, label=f"E16 A segment {index}", diagnostic=diagnostic),
                },
            }
        )
        cursor += a_duration

        insert = segment.get("b_insert")
        if insert:
            b_duration = float(insert.get("counted_duration_estimate") or insert.get("duration") or 0.0)
            clips.append(
                {
                    "id": f"B-{index:03d}",
                    "source": insert.get("video_path") or insert.get("source_id") or "",
                    "start": round(cursor, 6),
                    "duration": b_duration,
                    "metadata": {
                        **(insert.get("metadata") or {}),
                        "shot_index": index,
                        "dialogue_id": None,  # picture-only insert
                        "speaker": None,
                        "coverage_group": "B",
                        "listener": insert.get("listener"),
                        "placement": insert.get("placement"),
                        **{key: insert[key] for key in evidence_fields if key in insert},
                        **required_cut_metadata(insert, label=f"E16 B insert {index}", diagnostic=diagnostic),
                    },
                }
            )
            cursor += b_duration

    return {"timeline": {"videoTracks": [{"clips": clips}]}, "requireCutReason": True}


def from_scene_timeline(plan: dict, diagnostic: bool = False) -> dict:
    """E17 form: a scene/shot timeline rather than a clip list."""
    rows: list[dict] = []
    for key in ("shots", "timeline", "scenes", "segments", "final_admission"):
        value = plan.get(key)
        if isinstance(value, list) and value and isinstance(value[0], dict):
            rows = value
            break
        if isinstance(value, dict):
            for inner in value.values():
                if isinstance(inner, list) and inner and isinstance(inner[0], dict):
                    rows = inner
                    break
            if rows:
                break
    if not rows:
        raise ValueError("no shot list found in scene timeline")

    clips: list[dict] = []
    cursor = 0.0
    for index, row in enumerate(rows):
        # E17's scene timeline states start/end rather than a duration.
        if row.get("end") is not None and row.get("start") is not None:
            duration = float(row["end"]) - float(row["start"])
        else:
            duration = float(
                row.get("duration")
                or row.get("duration_seconds")
                or row.get("target_duration")
                or (row.get("expected_frames", 0) / float(plan.get("fps") or 24))
                or 0.0
            )
        clips.append(
            {
                "id": row.get("shot_id") or f"S-{index:03d}",
                "source": row.get("source") or row.get("video_path") or row.get("source_id") or "",
                "start": round(cursor, 6),
                "duration": duration,
                "metadata": {
                    **(row.get("metadata") or {}),
                    "shot_index": index,
                    "dialogue_id": row.get("dialogue_id"),
                    "speaker": row.get("speaker"),
                    "scene_id": row.get("scene_id"),
                    "light_key": row.get("light_key"),
                    **required_cut_metadata(row, label=f"scene timeline shot {index}", diagnostic=diagnostic),
                },
            }
        )
        cursor += duration
    return {"timeline": {"videoTracks": [{"clips": clips}]}, "requireCutReason": True}


def adapt(plan: dict, diagnostic: bool = False) -> tuple[dict, str]:
    if "timeline" in plan and isinstance(plan.get("timeline"), dict) and "videoTracks" in plan["timeline"]:
        return plan, "agentcut_native"
    if isinstance(plan.get("segments"), list) and plan["segments"] and "a_source_id" in plan["segments"][0]:
        return from_ordered_edl(plan, diagnostic), "ordered_edl"
    return from_scene_timeline(plan, diagnostic), "scene_timeline"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument(
        "--diagnostic",
        action="store_true",
        help="audit a pre-contract plan: record missing motivation instead of rejecting it",
    )
    args = parser.parse_args()

    plan = json.loads(Path(args.plan).expanduser().resolve().read_text(encoding="utf-8"))
    project, form = adapt(plan, diagnostic=args.diagnostic)
    clips = [c for t in project["timeline"]["videoTracks"] for c in t.get("clips", [])]

    out = Path(args.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"source_form": form, "clips": len(clips)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
