#!/usr/bin/env python3
"""Build E20 v2 duration scaffolding and final SHA-bound local cross-contract QA."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def split_seconds(total: int, count: int) -> list[int]:
    base, remainder = divmod(total, count)
    return [base + (1 if index < remainder else 0) for index in range(count)]


def build_duration(beat_sheet: dict[str, Any], coverage: dict[str, Any], sha256: str) -> dict[str, Any]:
    if coverage.get("beat_sheet_sha256") != sha256:
        raise ValueError("coverage beat_sheet_sha256 mismatch")
    coverage_by_beat = {row["beat_id"]: row for row in coverage["beat_coverage"]}
    beats = []
    for beat in beat_sheet["structure"]:
        coverage_beat = coverage_by_beat[beat["beat_id"]]
        units = coverage_beat["planned_units"]
        allocations = split_seconds(int(beat["target_seconds"]), len(units))
        beats.append(
            {
                "beat_id": beat["beat_id"],
                "segment_type": beat["segment_type"],
                "target_seconds": beat["target_seconds"],
                "dialogue_ids": coverage_beat["dialogue_ids"],
                "units": [
                    {
                        "unit_id": f"{beat['beat_id']}-V2-U{index:02d}",
                        "coverage_unit": unit,
                        "budget_seconds": seconds,
                        "source_id": None,
                        "budget_is_not_single_shot_permission": True,
                    }
                    for index, (unit, seconds) in enumerate(zip(units, allocations), start=1)
                ],
            }
        )
    target = int(beat_sheet["runtime_target_seconds"]["target"])
    return {
        "schema": "qingshan.timeline_duration_skeleton.v2",
        "episode": "E20",
        "created_at_pdt": "2026-07-16 11:5x",
        "status": "V2_LOCAL_DURATION_SKELETON_NO_SOURCE_ASSIGNMENT",
        "review_ref": "CL2X-184",
        "beat_sheet_sha256": sha256,
        "dialogue_count": len(beat_sheet["dialogue_draft"]),
        "target_runtime_seconds": target,
        "generation_allowed": False,
        "source_lock_allowed": False,
        "edit_allowed": False,
        "submittable": False,
        "provider_payload": None,
        "rhythm_policy": {
            "episode_asl_max_seconds": 3.5,
            "burst_asl_target_max_seconds": 2.0,
            "single_shot_max_seconds": 6.0,
            "unmotivated_shots_over_8_seconds": 0,
            "no_dialogue_near_still_over_4_seconds_forbidden": True,
            "freeze_speed_change_loop_replay_forbidden": True,
            "note": "Unit budgets contain multiple internal shots and reactions; they never authorize one held shot."
        },
        "beats": beats,
        "checks": {
            "declared_runtime_target_seconds": target,
            "beat_total_seconds": sum(row["target_seconds"] for row in beats),
            "unit_total_seconds": sum(unit["budget_seconds"] for row in beats for unit in row["units"]),
            "unit_count": sum(len(row["units"]) for row in beats),
            "non_null_source_ids": 0,
        },
    }


def build_cross_qa(
    beat_sheet: dict[str, Any],
    sha256: str,
    performance: dict[str, Any],
    audio: dict[str, Any],
    sound: dict[str, Any],
    coverage: dict[str, Any],
    source_request: dict[str, Any],
    duration: dict[str, Any],
    visual_qa: dict[str, Any],
) -> dict[str, Any]:
    contracts = [performance, audio, sound, coverage, source_request, duration]
    expected_ids = [row["dia_id"] for row in beat_sheet["dialogue_draft"]]
    audio_ids = [row["dia_id"] for beat in audio["beats"] for row in beat["AUDIO_PROMPT_DIALOGUE_ONLY"]]
    sound_ids = [dia for beat in sound["beat_sound_design"] for dia in beat["dialogue_ids"]]
    coverage_ids = [row["dia_id"] for row in coverage["dialogue_coverage"]]
    request_ids = [dia for beat in source_request["beat_requests"] for dia in beat["audio_scope"]]
    checks = {
        "all_contract_sha_match": all(row.get("beat_sheet_sha256") == sha256 for row in contracts),
        "performance_ids_match": [row["dia_id"] for row in performance["lines"]] == expected_ids,
        "audio_ids_match": audio_ids == expected_ids,
        "sound_ids_match": sound_ids == expected_ids,
        "coverage_ids_match": coverage_ids == expected_ids,
        "source_request_ids_match": request_ids == expected_ids,
        "dialogue_count": len(expected_ids),
        "every_dialogue_has_a_source": all(row["a_source"]["required"] for row in coverage["dialogue_coverage"]),
        "every_dialogue_has_b_source": all(row["b_source"]["required"] for row in coverage["dialogue_coverage"]),
        "source_requests_all_disabled": all(not row["submittable"] for row in source_request["beat_requests"]),
        "provider_payloads_absent": all(
            row.get("provider_payload") is None and row.get("provider_request_payload") is None
            for row in contracts
        ),
        "duration_target_matches": duration["target_runtime_seconds"] == beat_sheet["runtime_target_seconds"]["target"],
        "duration_units_sum_matches": duration["checks"]["unit_total_seconds"] == duration["target_runtime_seconds"],
        "duration_source_ids_empty": duration["checks"]["non_null_source_ids"] == 0,
        "visual_prompt_v2_dialogue_scan_pass": (
            visual_qa.get("beat_sheet_sha256") == sha256
            and visual_qa.get("summary", {}).get("dialogue_lines_scanned") == len(expected_ids)
            and visual_qa.get("summary", {}).get("exact_dialogue_leaks") == 0
        ),
    }
    hard_pass = all(value is True or key == "dialogue_count" for key, value in checks.items())
    return {
        "schema": "qingshan.e20_v2_cross_contract_qa.v1",
        "episode": "E20",
        "created_at_pdt": "2026-07-16 11:5x",
        "status": "PASS_LOCAL_REBASE_COMPLETE_VOICE_BLOCKED" if hard_pass else "FAIL",
        "review_ref": "CL2X-184",
        "beat_sheet_sha256": sha256,
        "checks": checks,
        "generation_allowed": False,
        "open_blockers": [
            "21 dialogue lines across Yunyang, Jiaotu, Fozi and patrol leader still require immutable voice assets or approved reassignment",
            "final assembled audio must prove at least 15 ASR/VAD speech segments per minute",
            "actual generated A/B sources and final package QA do not yet exist"
        ],
        "release_rule": "Only a PASS closes the v0-to-v2 local contract rebase. No result here authorizes generation, source lock, edit, package or release."
    }


def read(path: str) -> dict[str, Any]:
    return json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--beat-sheet", required=True)
    parser.add_argument("--performance", required=True)
    parser.add_argument("--audio", required=True)
    parser.add_argument("--sound", required=True)
    parser.add_argument("--coverage", required=True)
    parser.add_argument("--source-request", required=True)
    parser.add_argument("--visual-qa", required=True)
    parser.add_argument("--duration-out", required=True)
    parser.add_argument("--qa-out", required=True)
    args = parser.parse_args()
    beat_path = Path(args.beat_sheet).expanduser().resolve()
    beat_bytes = beat_path.read_bytes()
    beat_sheet = json.loads(beat_bytes)
    sha256 = hashlib.sha256(beat_bytes).hexdigest()
    performance = read(args.performance)
    audio = read(args.audio)
    sound = read(args.sound)
    coverage = read(args.coverage)
    source_request = read(args.source_request)
    visual_qa = read(args.visual_qa)
    duration = build_duration(beat_sheet, coverage, sha256)
    qa = build_cross_qa(
        beat_sheet,
        sha256,
        performance,
        audio,
        sound,
        coverage,
        source_request,
        duration,
        visual_qa,
    )
    for output, payload in ((args.duration_out, duration), (args.qa_out, qa)):
        path = Path(output).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": qa["status"], "unit_count": duration["checks"]["unit_count"]}, ensure_ascii=False))
    return 0 if qa["status"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
