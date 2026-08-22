#!/usr/bin/env python3
"""Compile E40's missing native-dialogue performance units from locked inputs.

This compiler is deliberately zero-cost.  It creates the unit contract that the
keyframe builder consumes; it never submits provider work and never fabricates
final subtitle timing.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e40_remake_v1_20260817"
DIALOGUE = PROD / "E40_REMAKE_DIALOGUE_SUBTITLE_CONTRACT_V1.json"
DEFINITION = PROD / "E40_REMAKE_V1_PRODUCTION_DEFINITION.json"
SPATIAL = PROD / "E40_SPATIAL_SHOT_PLAN_V1.json"
OUTPUT = PROD / "full_performance_native_dialogue_v1/E40_FULL_PERFORMANCE_NATIVE_DIALOGUE_PLAN_V1.json"


GROUPS = (
    ("R01-YUNFEI-A", "R01", "云妃", ("E40-DIA-001", "E40-DIA-002", "E40-DIA-003"), 8),
    ("R01-CHENJI-B", "R01", "陈迹", ("E40-DIA-004",), 4),
    ("R02-CHENJI-A", "R02", "陈迹", ("E40-DIA-005", "E40-DIA-006", "E40-DIA-007"), 10),
    ("R03-CHENJI-A", "R03", "陈迹", ("E40-DIA-008",), 4),
    ("R03-YUNFEI-B", "R03", "云妃", ("E40-DIA-009",), 4),
    ("R04-CHENJI-A", "R04", "陈迹", ("E40-DIA-010",), 4),
    ("R04-YUNFEI-B", "R04", "云妃", ("E40-DIA-011", "E40-DIA-012"), 8),
    ("R05-CHENJI-A", "R05", "陈迹", ("E40-DIA-013", "E40-DIA-014"), 8),
    ("R06-ASHUAN-A", "R06A", "阿栓", ("E40-DIA-015",), 4),
    ("R07-YUNYANG-A", "R07", "云羊", ("E40-DIA-016",), 4),
    ("R08-YUNFEI-A", "R08", "云妃", ("E40-DIA-017",), 4),
    ("R08-CHENJI-B", "R08", "陈迹", ("E40-DIA-018",), 6),
    ("R08-YUNFEI-C", "R08", "云妃", ("E40-DIA-019", "E40-DIA-020"), 8),
)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    dialogue = load(DIALOGUE)
    definition = load(DEFINITION)
    spatial = load(SPATIAL)
    rows = {row["dialogue_id"]: row for row in dialogue["rows"]}
    expected = set(rows)
    compiled_ids = [dialogue_id for group in GROUPS for dialogue_id in group[3]]
    if len(compiled_ids) != len(set(compiled_ids)) or set(compiled_ids) != expected:
        raise SystemExit("dialogue grouping must cover every locked line exactly once")

    spatial_items = spatial.get("tasks", spatial.get("shots", spatial.get("units", [])))
    spatial_rows = {
        row.get("unit") or row.get("unit_id") or row.get("shot_id") or row.get("task_id"): row
        for row in spatial_items
    }
    units = []
    for unit_id, source_unit, speaker, dialogue_ids, duration in GROUPS:
        selected = [rows[item] for item in dialogue_ids]
        if any(row["speaker"] != speaker for row in selected):
            raise SystemExit(f"speaker mismatch in {unit_id}")
        spatial_row = spatial_rows.get(source_unit, {})
        units.append({
            "task_id": f"E40-FP-{unit_id}-V1",
            "source_unit": source_unit,
            "shot_type": "DIALOGUE_PERFORMANCE",
            "model": "seedance-2.0-fast",
            "duration_seconds": duration,
            "aspect_ratio": "9:16",
            "resolution": "720p",
            "speaker": speaker,
            "dialogue_ids": list(dialogue_ids),
            "spoken_lines": [
                {"dialogue_id": row["dialogue_id"], "text": row["spoken_text"], "emotion": row["emotion"]}
                for row in selected
            ],
            "native_audio_contract": {
                "required": True,
                "visible_lips_must_match_same_provider_task_audio": True,
                "external_tts_or_old_candidate_replacement_forbidden": True,
                "preserve_dialogue_ambience_foley_and_action_sfx": True,
                "bgm_policy": "NONE_UNLESS_NAMED_NARRATIVE_CUE",
            },
            "spatial_authority": {
                "episode_global_space_map_id": spatial.get("episode_global_space_map_id"),
                "global_space_map_id": spatial.get("global_space_map_id"),
                "subspace_id": (spatial_row.get("subspace_layout") or {}).get("subspace_id"),
                "resolution_order": spatial.get("resolution_order"),
            },
            "keyframe_input_policy": {
                "native_registry_lookup_required_before_generation": True,
                "exact_sha_q1_admission_required": True,
                "character_identity_output_verification_required": True,
                "no_prior_rejected_e40_media": True,
            },
            "submit_state": "BLOCKED_UNTIL_KEYFRAME_Q1_AND_PAID_TRANSACTION",
        })

    result = {
        "schema": "qingshan.e40.full_performance_native_dialogue_plan.v1",
        "episode": "E40",
        "compiled_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "COMPILED_AWAITING_KEYFRAME_Q1",
        "canonical": definition["canonical_story"],
        "dialogue_contract": {"path": str(DIALOGUE.relative_to(ROOT)), "sha256": sha(DIALOGUE)},
        "spatial_plan": {"path": str(SPATIAL.relative_to(ROOT)), "sha256": sha(SPATIAL)},
        "unit_count": len(units),
        "locked_dialogue_line_count": len(compiled_ids),
        "planned_generated_seconds": sum(item[4] for item in GROUPS),
        "final_timing_policy": "Measure admitted provider audio, then author subtitles and edit; never force speech speed or fabricate timestamps.",
        "units": units,
    }
    write(OUTPUT, result)
    print(json.dumps({"status": "PASS", "output": str(OUTPUT.relative_to(ROOT)), "sha256": sha(OUTPUT), "units": len(units)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
