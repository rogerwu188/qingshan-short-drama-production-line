#!/usr/bin/env python3
"""Build the deterministic QA queue for listener-reaction coverage clips."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt-manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    prompts = json.loads(args.prompt_manifest.read_text(encoding="utf-8"))
    clips = prompts.get("clips", [])
    expected_count = int(prompts.get("clip_count", len(clips)))
    if not clips or len(clips) != expected_count:
        raise SystemExit(f"manifest clip count mismatch: expected {expected_count}, got {len(clips)}")

    checks = [
        {
            "id": "BQA-01",
            "name": "source_file",
            "condition": "downloaded MP4 exists and is decodable",
            "failure": "BLOCK_SOURCE_MISSING_OR_CORRUPT",
        },
        {
            "id": "BQA-02",
            "name": "duration",
            "condition": "3.8 <= duration_seconds <= 4.2",
            "failure": "REJECT_DURATION",
        },
        {
            "id": "BQA-03",
            "name": "near_duplicate_frames",
            "condition": "near_duplicate_ratio <= 0.10 and repeated_cluster_count <= 2",
            "failure": "REJECT_FROZEN_REACTION",
        },
        {
            "id": "BQA-04",
            "name": "reaction_timing",
            "condition": "visible reaction begins by 1.8s and develops continuously in real time",
            "failure": "REJECT_SLOW_OR_STATIC_REACTION",
        },
        {
            "id": "BQA-05",
            "name": "single_action_unit",
            "condition": "one listener reaction progression; no repeated gesture or second action",
            "failure": "REJECT_MULTI_ACTION_OR_REPLAY",
        },
        {
            "id": "BQA-06",
            "name": "silent_listener",
            "condition": "mouth remains naturally closed; no dialogue, lip-sync or generated subtitle",
            "failure": "REJECT_SPEAKING_LISTENER",
        },
        {
            "id": "BQA-07",
            "name": "identity_axis_scene",
            "condition": "listener identity, eyeline, axis direction and scene light match manifest",
            "failure": "REJECT_CONTINUITY_DRIFT",
        },
        {
            "id": "BQA-08",
            "name": "scale_posture",
            "condition": "human occupancy 0.55-0.72; Chenji upright; Wuyun natural scale if present",
            "failure": "REJECT_SCALE_OR_POSTURE",
        },
        {
            "id": "BQA-09",
            "name": "period_text",
            "condition": "Song/Ming world; no modern objects, English/Latin text or central bold text",
            "failure": "REJECT_PERIOD_OR_TEXT",
        },
        {
            "id": "BQA-10",
            "name": "editorial_delta",
            "condition": "final state visibly differs from opening and can carry the assigned beat delta",
            "failure": "REJECT_NO_REACTION_DELTA",
        },
        {
            "id": "BQA-11",
            "name": "expression_arc",
            "condition": "face visibly moves from declared start state to end state at the declared trigger; facial delta is primary",
            "failure": "REJECT_EXPRESSION_ARC_MISSING_OR_MISTIMED",
        },
    ]

    queue = {
        "schema": "qingshan.b_coverage_qa_queue.v1",
        "episode": prompts.get("episode"),
        "source_prompt_manifest": str(args.prompt_manifest),
        "status": "WAITING_FOR_REMOTE_SOURCES",
        "pass_rule": "all automatic and agent-watch checks pass; no metric alone implies acceptance",
        "checks": checks,
        "clips": [],
    }
    for clip in clips:
        queue["clips"].append(
            {
                "coverage_source_id": clip["coverage_source_id"],
                "submission_batch": clip["submission_batch"],
                "serves_dialogue_beats": clip["serves_dialogue_beats"],
                "listener": clip["listener"],
                "expected_source": f"{clip['output_dir']}/result_01.mp4",
                "qa_dir": clip["qa_dir"],
                "required_check_ids": [check["id"] for check in checks],
                "status": "WAITING_FOR_SOURCE",
                "result": None,
            }
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"generated QA queue for {len(clips)} B sources: {args.output}")


if __name__ == "__main__":
    main()
