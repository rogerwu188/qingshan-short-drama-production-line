#!/usr/bin/env python3
"""Apply four evidence-backed, shot-local E17 boundary brightness corrections."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

SHOT_EQ_BRIGHTNESS = {
    21: -0.35,
    26: 0.23,
    31: 0.22,
    37: 0.14,
}


def tune(plan: dict) -> dict:
    result = deepcopy(plan)
    for shot_number, brightness in SHOT_EQ_BRIGHTNESS.items():
        row = result["segments"][shot_number - 1]
        row["eq_brightness"] = brightness
        row["scene_boundary_tune"] = {
            "source_ref": "qa/e17_full_assembly_trial_v0_20260714/E17_REMAKE_PACING_REFINED_SCENE_BRIGHTNESS_V2_20260716.json",
            "reason": "SHOT_LOCAL_SAME_SCENE_END_TO_START_LUMA_JUMP_OVER_25",
        }
    result["schema"] = "qingshan.frame_exact_video_plan.v5"
    result["status"] = "LOCAL_SCENE_BOUNDARY_TUNED_DIAGNOSTIC_ONLY"
    result["supersedes"] = "configs/e17_remake_pacing_finecut_plan_v2_20260716.json"
    result["scene_boundary_tuning"] = {
        "shot_numbers_one_based": sorted(SHOT_EQ_BRIGHTNESS),
        "scope": "FOUR_SHOT_LOCAL_EQ_CORRECTIONS_ONLY",
        "retime_freeze_loop": False,
        "frame_total_preserved": True,
        "retest_required": True,
    }
    if sum(int(row["expected_frames"]) for row in result["segments"]) != int(result["expected_frames"]):
        raise ValueError("Brightness tuning changed frame total")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=ROOT / "configs/e17_remake_pacing_finecut_plan_v2_20260716.json")
    parser.add_argument("--out", type=Path, default=ROOT / "configs/e17_remake_pacing_finecut_plan_v3_brightness_20260716.json")
    args = parser.parse_args()
    result = tune(json.loads(args.plan.read_text(encoding="utf-8")))
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["scene_boundary_tuning"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
