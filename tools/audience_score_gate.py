#!/usr/bin/env python3
"""Validate the evidence-backed simulated-audience gate before release."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DIMENSIONS = {
    "story",
    "continuation",
    "pacing",
    "opening",
    "clarity",
    "visual",
    "anti_ai",
    "completeness",
}
VIEWING_PASSES = {"full_1x", "muted", "sound"}
EVIDENCE_FIELDS = {
    "frame_grid",
    "asr",
    "semantic_group_pct",
    "scene_rotation_table",
    "burned_subtitles",
    "identity_color_consistent",
    "opening_10s_hook",
    "tail_5s_hook_intact",
}


def _as_score(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        score = float(value)
        if 1.0 <= score <= 5.0:
            return score
    return None


def evaluate(report: dict[str, Any], base: Path | None = None) -> dict[str, Any]:
    validation_failures: list[str] = []
    hard_fail: list[str] = list(report.get("hard_fail") or [])

    if report.get("technical_gate_status") != "PASS":
        validation_failures.append("technical_gate_must_pass_before_audience_gate")

    viewing = report.get("viewing_passes") or {}
    for key in sorted(VIEWING_PASSES):
        if viewing.get(key) is not True:
            validation_failures.append(f"viewing_pass_missing:{key}")

    overall = _as_score(report.get("overall"))
    if overall is None:
        validation_failures.append("overall_score_must_be_1_to_5")

    dimensions = report.get("dimensions") or {}
    for key in sorted(DIMENSIONS):
        if _as_score(dimensions.get(key)) is None:
            validation_failures.append(f"dimension_score_invalid:{key}")

    evidence = report.get("evidence") or {}
    for key in sorted(EVIDENCE_FIELDS):
        if key not in evidence:
            validation_failures.append(f"evidence_missing:{key}")

    for key in ("frame_grid", "asr", "scene_rotation_table"):
        ref = evidence.get(key)
        if not isinstance(ref, str) or not ref.strip():
            validation_failures.append(f"evidence_ref_invalid:{key}")
        elif base is not None and not (base / ref).is_file() and not Path(ref).is_file():
            validation_failures.append(f"evidence_ref_missing:{key}:{ref}")

    semantic_groups = evidence.get("semantic_group_pct")
    if not isinstance(semantic_groups, dict) or not semantic_groups:
        validation_failures.append("semantic_group_pct_must_be_nonempty_object")
        max_semantic_pct = None
    else:
        values = [value for value in semantic_groups.values() if isinstance(value, (int, float))]
        if len(values) != len(semantic_groups):
            validation_failures.append("semantic_group_pct_values_must_be_numeric")
            max_semantic_pct = None
        else:
            max_semantic_pct = max(float(value) for value in values)
            if max_semantic_pct > 15.0 and "semantic_group_over_15pct" not in hard_fail:
                hard_fail.append("semantic_group_over_15pct")

    if evidence.get("burned_subtitles") is not True and "missing_burned_subtitles" not in hard_fail:
        hard_fail.append("missing_burned_subtitles")
    if (
        evidence.get("identity_color_consistent") is not True
        and "identity_color_mismatch" not in hard_fail
    ):
        hard_fail.append("identity_color_mismatch")
    if evidence.get("opening_10s_hook") is not True and "opening_10s_no_hook" not in hard_fail:
        hard_fail.append("opening_10s_no_hook")
    if evidence.get("tail_5s_hook_intact") is not True and "tail_5s_hook_broken" not in hard_fail:
        hard_fail.append("tail_5s_hook_broken")

    narrative_stagnation = bool(evidence.get("narrative_stagnation"))
    if (narrative_stagnation or (max_semantic_pct or 0) > 15.0) and dimensions:
        if _as_score(dimensions.get("pacing")) and float(dimensions["pacing"]) > 2.0:
            validation_failures.append("pacing_must_be_le_2_when_narrative_stagnation_or_semantic_over_15pct")
        if _as_score(dimensions.get("visual")) and float(dimensions["visual"]) > 2.0:
            validation_failures.append("visual_must_be_le_2_when_narrative_stagnation_or_semantic_over_15pct")

    expected_verdict = (
        "REJECT_RECUT" if hard_fail or overall is None or overall < 3.0 else "PASS"
    )
    if report.get("verdict") != expected_verdict:
        validation_failures.append(
            f"verdict_mismatch:expected_{expected_verdict}:actual_{report.get('verdict')}"
        )
    if expected_verdict == "REJECT_RECUT" and not report.get("problems"):
        validation_failures.append("rejected_report_requires_problems_and_shot_level_fixes")

    validation_status = "PASS" if not validation_failures else "FAIL"
    gate_status = (
        "PASS"
        if validation_status == "PASS" and expected_verdict == "PASS"
        else "REJECT_RECUT"
        if validation_status == "PASS"
        else "INVALID"
    )
    return {
        "schema": "qingshan.audience_score_gate_result.v1",
        "episode": report.get("episode"),
        "validation_status": validation_status,
        "gate_status": gate_status,
        "release_allowed": gate_status == "PASS",
        "overall": overall,
        "verdict": expected_verdict,
        "hard_fail": sorted(set(hard_fail)),
        "validation_failures": validation_failures,
        "rule": "Technical QA PASS -> full/muted/sound audience gate; opening 10s and tail-hook 5s are zero-tolerance -> supervisor review -> release.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Enforce the pre-release audience score gate.")
    parser.add_argument("--report", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--base")
    parser.add_argument("--expect-verdict", choices=["PASS", "REJECT_RECUT"])
    args = parser.parse_args()

    report_path = Path(args.report).expanduser().resolve()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    result = evaluate(report, Path(args.base).resolve() if args.base else report_path.parents[2])
    if args.expect_verdict and result["verdict"] != args.expect_verdict:
        result["validation_status"] = "FAIL"
        result["gate_status"] = "INVALID"
        result["release_allowed"] = False
        result["validation_failures"].append(
            f"backtest_verdict_mismatch:expected_{args.expect_verdict}:actual_{result['verdict']}"
        )

    out = Path(args.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["validation_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
