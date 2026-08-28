#!/usr/bin/env python3
"""Bind the reduced post-generation QA scope after strict prompt preflight.

Generation-time creative precision is fail-closed before paid submission.  Once
media exists, admission checks technical integrity and broad plot identity only;
it must not trigger remakes for gesture, microexpression, choreography, or other
task-detail preferences that should have been solved in the prompt contract.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ALLOWED_TECHNICAL_CHECKS = {
    "decode", "duration", "resolution", "aspect_ratio", "codec", "audio_stream",
    "av_sync", "black_frame", "freeze", "corruption", "frame_rate", "sample_rate",
}
ALLOWED_BASIC_PLOT_CHECKS = {
    "episode_scene_correspondence", "principal_character_presence",
    "major_event_presence", "major_dialogue_presence", "chronological_unit_order",
}
FORBIDDEN_POST_GENERATION_CHECKS = {
    "action_reasonableness", "gesture_precision", "hand_contact_precision",
    "microexpression_precision", "task_detail_compliance", "camera_action_detail",
    "prop_trajectory_precision", "boundary_action_match", "choreography_precision",
}


def evaluate(requested_checks: list[str]) -> dict[str, Any]:
    requested = {str(value).strip() for value in requested_checks if str(value).strip()}
    allowed = ALLOWED_TECHNICAL_CHECKS | ALLOWED_BASIC_PLOT_CHECKS
    forbidden = sorted(requested & FORBIDDEN_POST_GENERATION_CHECKS)
    unknown = sorted(requested - allowed - FORBIDDEN_POST_GENERATION_CHECKS)
    failures = [*(f"FORBIDDEN_POST_GENERATION_QA:{value}" for value in forbidden), *(f"UNKNOWN_POST_GENERATION_QA:{value}" for value in unknown)]
    return {
        "schema": "qingshan.post_generation_qa_scope_gate.v1",
        "status": "PASS" if not failures else "FAIL",
        "strict_creative_continuity_stage": "PRE_SUBMISSION_ONLY",
        "post_generation_scope": "TECHNICAL_AND_BASIC_PLOT_ONLY",
        "allowed_technical_checks": sorted(ALLOWED_TECHNICAL_CHECKS),
        "allowed_basic_plot_checks": sorted(ALLOWED_BASIC_PLOT_CHECKS),
        "explicitly_forbidden_post_generation_checks": sorted(FORBIDDEN_POST_GENERATION_CHECKS),
        "requested_checks": sorted(requested),
        "failures": failures,
        "remake_policy": (
            "Post-generation remake may be triggered only by technical failure or basic plot mismatch; "
            "never by action reasonableness, gesture/microexpression precision, choreography, or task-detail preference."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--check", action="append", default=[])
    args = parser.parse_args()
    requested = args.check or sorted(ALLOWED_TECHNICAL_CHECKS | ALLOWED_BASIC_PLOT_CHECKS)
    result = evaluate(requested)
    result["episode"] = args.episode
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"episode": args.episode, "status": result["status"], "failure_count": len(result["failures"]), "out": str(args.out)}, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
