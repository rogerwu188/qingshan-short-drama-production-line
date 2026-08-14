#!/usr/bin/env python3
"""Insert short visual reaction cuts without changing AgentCut runtime or audio."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path

try:
    from tools.cut_motivation_gate import CONTINUITY_FIELDS, CUT_REASONS, METRIC_LANGUAGE
except ModuleNotFoundError:  # direct `python tools/insert_agentcut_short_cuts.py`
    from cut_motivation_gate import CONTINUITY_FIELDS, CUT_REASONS, METRIC_LANGUAGE


def _required_insert_metadata(row: dict) -> dict:
    """Reject an insert before it can enter the project timeline.

    Insert generation must provide the same evidence the independent edit
    gates will later verify. In particular, there is deliberately no default
    reason: a missing reason means the proposed clip does not exist.
    """
    reason = row.get("reason")
    if reason not in CUT_REASONS:
        raise SystemExit(
            f"Insert {row.get('id', '<unknown>')} requires an explicit closed-vocabulary reason"
        )
    if METRIC_LANGUAGE.search(str(reason)) or METRIC_LANGUAGE.search(str(row.get("reason_note", ""))):
        raise SystemExit(f"Insert {row.get('id', '<unknown>')} uses metric-driven cut language")
    missing = [field for field in CONTINUITY_FIELDS if not row.get(field)]
    if missing:
        raise SystemExit(
            f"Insert {row.get('id', '<unknown>')} missing continuity fields: {', '.join(missing)}"
        )
    if not row.get("new_information"):
        raise SystemExit(
            f"Insert {row.get('id', '<unknown>')} requires explicit new_information"
        )
    reason_evidence_field = CUT_REASONS[reason]
    reason_evidence = row.get(reason_evidence_field)
    if not reason_evidence:
        raise SystemExit(
            f"Insert {row.get('id', '<unknown>')} requires {reason_evidence_field} "
            f"for cut reason {reason}"
        )
    return {
        "cut_reason": reason,
        "insert_reason": reason,
        reason_evidence_field: reason_evidence,
        **{field: row[field] for field in CONTINUITY_FIELDS},
        "new_information": row["new_information"],
    }


def _insert_semantic_group(row: dict) -> str:
    """Give each inserted visual beat its own cooldown identity."""
    return str(row.get("semantic_group") or row["id"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--out-project", type=Path, required=True)
    parser.add_argument("--out-report", type=Path, required=True)
    parser.add_argument("--output-media", type=Path, required=True)
    args = parser.parse_args()

    project = json.loads(args.project.read_text())
    plan = json.loads(args.plan.read_text())
    rebuilt = deepcopy(project)
    rebuilt["output"]["path"] = str(args.output_media.expanduser().resolve())
    track = rebuilt["timeline"]["videoTracks"][0]
    clips = track["clips"]
    by_id = {clip["id"]: clip for clip in clips}
    inserted = []

    for row in plan["inserts"]:
        evidence = _required_insert_metadata(row)
        target = by_id[row["target_clip_id"]]
        duration = float(row["duration"])
        if duration >= float(target["duration"]) - 0.2:
            raise SystemExit(f"Insert is too long for {target['id']}")
        target["duration"] = round(float(target["duration"]) - duration, 6)
        insert = {
            "id": row["id"],
            "source": str(Path(row["source"]).expanduser().resolve()),
            "start": round(float(target["start"]) + float(target["duration"]), 6),
            "in": float(row.get("in", 0.0)),
            "duration": duration,
            "metadata": {
                **target.get("metadata", {}),
                "dialogue_id": None,
                "short_reaction_insert": True,
                **evidence,
                # An insert carries new visual information and must not inherit
                # the parent dialogue's semantic cooldown identity.
                "semantic_group": _insert_semantic_group(row),
                "source_target_clip_id": target["id"],
            },
        }
        clips.append(insert)
        inserted.append(insert)

    clips.sort(key=lambda clip: (float(clip["start"]), clip["id"]))
    short_count = sum(float(clip["duration"]) < 1.0 for clip in clips)
    short_ratio = short_count / len(clips)
    overlaps = []
    for left, right in zip(clips, clips[1:]):
        gap = float(right["start"]) - (
            float(left["start"]) + float(left["duration"])
        )
        if gap < -0.001:
            overlaps.append(
                {"left": left["id"], "right": right["id"], "gap": round(gap, 6)}
            )

    status = "PASS" if not overlaps and 0.05 <= short_ratio <= 0.15 else "FAIL"
    report = {
        "schema": "qingshan.agentcut_short_cut_insert.v1",
        "status": status,
        "source_project": str(args.project.resolve()),
        "plan": str(args.plan.resolve()),
        "video_clip_count": len(clips),
        "under_one_second_count": short_count,
        "under_one_second_ratio": round(short_ratio, 6),
        "target_range": [0.05, 0.15],
        "inserted": inserted,
        "overlaps": overlaps,
        "runtime_unchanged": True,
        "audio_and_subtitles_unchanged": True,
    }
    args.out_report.parent.mkdir(parents=True, exist_ok=True)
    args.out_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if status == "PASS":
        args.out_project.parent.mkdir(parents=True, exist_ok=True)
        args.out_project.write_text(
            json.dumps(rebuilt, ensure_ascii=False, indent=2) + "\n"
        )
    print(json.dumps({"status": status, "clip_count": len(clips), "short_count": short_count, "short_ratio": round(short_ratio, 6), "overlaps": len(overlaps)}))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
