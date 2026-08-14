#!/usr/bin/env python3
"""Compute a speech-feasible minimum E36 recovery duration and credit floor."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/E36_DIALOGUE_NATIVE_VIDEO_CONTRACT_V1.json"
SCOPE_GATE = ROOT / "qa/e36_agentcut_20260730/E36_CANONICAL_DIALOGUE_RECOVERY_SCOPE_AND_CREDIT_GATE_V1.json"
CREDIT_AUDIT = ROOT / "qa/e36_v2_stills_repair_20260729/E36_ACTUAL_CREDIT_SPEND_AUDIT_5863_V9.json"
OUT = ROOT / "qa/e36_agentcut_20260730/E36_RECOVERY_DIALOGUE_TIMING_AND_CREDIT_FLOOR_V1.json"


FASTEST_EXACT_ACCEPTED_RATE_CHARS_PER_SECOND = 5.0
HEAD_TAIL_SECONDS = 0.8
INTERLINE_BREATH_SECONDS = 0.35
MINIMUM_CLIP_SECONDS = 5
MAXIMUM_CLIP_SECONDS = 12
FAST_CREDITS_PER_SECOND = 16

# Line groups preserve canonical order and keep every recovery clip at or below
# 12 seconds at the fastest exact accepted E36 native-dialogue rate.
CLIP_GROUPS = [
    ("U02-R1", "U02", [1, 2, 3], 0),
    ("U04-R1", "U04", [], 5),
    ("U08-R1", "U08", [4, 5], 5),
    ("U09-R1", "U09", [6, 7, 8], 0),
    ("U09-R2", "U09", [9, 10], 0),
    ("U10-R1", "U10", [11, 12, 13], 0),
    ("U10-R2", "U10", [14, 15], 0),
    ("U11-R1", "U11", [16, 17], 0),
    ("U13-R1", "U13", [21], 0),
    ("U14-R1", "U14", [22, 23], 0),
    ("U14-R2", "U14", [24, 25, 26], 0),
    ("U14-R3", "U14", [27, 28], 0),
    ("U18-R1", "U18", [36], 5),
    ("U20A-R1", "U20A", [40], 0),
    ("U20A-R2", "U20A", [41, 42], 0),
    ("U21-R1", "U21", [46, 47], 0),
]


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def han_count(text: str) -> int:
    return len(re.findall(r"[\u3400-\u9fff]", text))


def main() -> int:
    contract = load(CONTRACT)
    scope_gate = load(SCOPE_GATE)
    credit_audit = load(CREDIT_AUDIT)
    lines = {index: row for index, row in enumerate(contract["lines"], start=1)}
    expected_unproven = {row["contract_line_number"] for row in scope_gate["unproven_line_assignments"]}
    grouped_lines = {line for _, _, group, _ in CLIP_GROUPS for line in group}
    if grouped_lines != expected_unproven:
        raise ValueError(f"recovery groups mismatch unproven lines: missing={sorted(expected_unproven-grouped_lines)} extra={sorted(grouped_lines-expected_unproven)}")

    clips = []
    for clip_id, unit, line_numbers, motion_floor in CLIP_GROUPS:
        chars = sum(han_count(lines[number]["text"]) for number in line_numbers)
        speech_seconds = chars / FASTEST_EXACT_ACCEPTED_RATE_CHARS_PER_SECOND if chars else 0
        breath_seconds = max(0, len(line_numbers) - 1) * INTERLINE_BREATH_SECONDS
        raw_minimum = speech_seconds + breath_seconds + (HEAD_TAIL_SECONDS if line_numbers else 0)
        duration = max(MINIMUM_CLIP_SECONDS, motion_floor, math.ceil(raw_minimum))
        if duration > MAXIMUM_CLIP_SECONDS:
            raise ValueError(f"speech-feasibility split exceeds max duration: {clip_id}={duration}s")
        clips.append(
            {
                "clip_id": clip_id,
                "canonical_unit": unit,
                "canonical_line_numbers": line_numbers,
                "dialogue": [lines[number]["text"] for number in line_numbers],
                "han_character_count": chars,
                "speech_seconds_at_fastest_exact_accepted_rate": round(speech_seconds, 3),
                "interline_breath_seconds": round(breath_seconds, 3),
                "head_tail_seconds": HEAD_TAIL_SECONDS if line_numbers else 0,
                "raw_minimum_seconds": round(raw_minimum, 3),
                "minimum_clip_seconds": duration,
                "minimum_fast_credits": duration * FAST_CREDITS_PER_SECOND,
            }
        )

    total_seconds = sum(row["minimum_clip_seconds"] for row in clips)
    additional_credits = total_seconds * FAST_CREDITS_PER_SECOND
    current = credit_audit["net_actual_credits"]
    cap = credit_audit["episode_limit"]
    projected = current + additional_credits
    prior_seconds = scope_gate["credit_floor"]["total_minimum_video_seconds"]
    prior_projected = scope_gate["credit_floor"]["projected_episode_credits"]

    payload = {
        "schema": "qingshan.e36_recovery_dialogue_timing_and_credit_floor.v1",
        "episode": "E36",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_cl2x": "CL2X-788",
        "source_mailbox_sha256": "e0a371f2062f16c467a7b9b833b9b879b7a8dbc3f88cbec736e3c494a452ef15",
        "inputs": {
            "canonical_dialogue_contract": {"path": str(CONTRACT.relative_to(ROOT)), "sha256": sha256(CONTRACT)},
            "complete_recovery_scope_gate": {"path": str(SCOPE_GATE.relative_to(ROOT)), "sha256": sha256(SCOPE_GATE)},
            "exact_credit_audit": {"path": str(CREDIT_AUDIT.relative_to(ROOT)), "sha256": sha256(CREDIT_AUDIT)},
        },
        "timing_authority": {
            "fastest_exact_accepted_native_dialogue_rate_han_chars_per_second": FASTEST_EXACT_ACCEPTED_RATE_CHARS_PER_SECOND,
            "evidence": "E36 U16A accepted exact native dialogue: 15 Han characters in a 3.0-second detected speech span.",
            "head_tail_seconds_per_clip": HEAD_TAIL_SECONDS,
            "interline_breath_seconds": INTERLINE_BREATH_SECONDS,
            "minimum_clip_seconds": MINIMUM_CLIP_SECONDS,
            "maximum_clip_seconds": MAXIMUM_CLIP_SECONDS,
            "pricing_floor_credits_per_second": FAST_CREDITS_PER_SECOND,
        },
        "clips": clips,
        "summary": {
            "recovery_clip_count": len(clips),
            "recovery_unit_count": len({row["canonical_unit"] for row in clips}),
            "canonical_unproven_lines_covered": len(grouped_lines),
            "speech_feasible_minimum_video_seconds": total_seconds,
            "minimum_additional_video_credits": additional_credits,
            "current_episode_credits": current,
            "projected_episode_credits": projected,
            "episode_cap": cap,
            "minimum_cap_shortfall": projected - cap,
            "image_repair_or_retry_buffer_included": False,
        },
        "supersession": {
            "prior_floor_seconds": prior_seconds,
            "prior_projected_episode_credits": prior_projected,
            "status": "SUPERSEDED_UNSPLIT_AUTHORED_DURATIONS_WERE_NOT_DIALOGUE_FEASIBLE",
            "reason": "The prior92-second floor reused original unit durations even where canonical dialogue could not fit naturally. This audit splits recovery into natural spoken units and prices the shortest speech-feasible containers.",
        },
        "gate_results": {
            "canonical_unproven_line_assignment": "PASS_31_OF_31_EXACTLY_ONCE",
            "natural_dialogue_timing": "PASS_ALL_RECOVERY_CLIPS_AT_OR_BELOW_12_SECONDS",
            "credit_cap": f"FAIL_PROJECTED_{projected}_GT_{cap}_SHORTFALL_{projected-cap}",
            "remote_submit": "BLOCKED_PENDING_ROGER",
            "agentcut_render": "BLOCKED",
        },
        "blocked_by": f"ROGER_DECISION_REQUIRED_REVISED_E36_CAP_AT_LEAST_{projected}_BEFORE_BUFFER_OR_CANONICAL_SCOPE_CHANGE",
        "next_action": "Roger chooses a ceiling at or above the speech-feasible floor, or explicitly amends canonical scope. After authorization, image-QA and submit the16 recovery clips incrementally, then require motion30/30 and exact dialogue47/47 before AgentCut.",
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(OUT), "sha256": sha256(OUT), "summary": payload["summary"], "supersession": payload["supersession"]}, ensure_ascii=False))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
