#!/usr/bin/env python3
"""Enforce natural performance splits before submission and after source QA."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STREAMING_POLICY = "SUBMIT_EACH_UNIT_IMMEDIATELY_WHEN_ITS_OWN_DEPENDENCIES_PASS"
REFERENCE_POLICY = "DYNAMIC_BY_MODEL_CAPABILITY_AND_ACTION_DESIGN"
NATURAL_BOUNDARIES = {
    "speaker_transition",
    "action_purpose_transition",
    "scene_transition",
    "physical_continuity_break",
}
REQUIRED_BEAT_FIELDS = {
    "start_seconds",
    "end_seconds",
    "subject",
    "action",
    "contact_point",
    "direction",
    "end_state",
    "expression",
    "intent",
}
ACCEPTED_ADMISSIONS = {"PASS", "CONDITIONAL_MACHINE_ADMISSION"}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else base / path).resolve()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dialogue_ids(unit: dict[str, Any]) -> list[str]:
    return [str(value) for value in unit.get("dialogue_ids") or []]


def _validate_motion_beats(unit: dict[str, Any], failures: list[str]) -> None:
    unit_id = str(unit.get("unit_id") or "UNKNOWN")
    duration = float(unit.get("duration_seconds") or 0)
    beats = unit.get("motion_beats") or []
    if duration <= 0:
        failures.append(f"invalid_duration:{unit_id}")
        return
    if not beats:
        failures.append(f"motion_beats_missing:{unit_id}")
        return
    cursor = 0.0
    for index, beat in enumerate(beats):
        missing = sorted(REQUIRED_BEAT_FIELDS - set(beat))
        if missing:
            failures.append(f"motion_beat_fields_missing:{unit_id}:{index}:{','.join(missing)}")
            continue
        start = float(beat["start_seconds"])
        end = float(beat["end_seconds"])
        if abs(start - cursor) > 0.05 or end <= start:
            failures.append(f"motion_beat_not_contiguous:{unit_id}:{index}")
        cursor = end
    if beats and abs(cursor - duration) > 0.05:
        failures.append(f"motion_beats_do_not_cover_unit:{unit_id}:{cursor}:{duration}")


def _validate_dialogue_bindings(
    unit: dict[str, Any], base: Path, failures: list[str]
) -> None:
    unit_id = str(unit.get("unit_id") or "UNKNOWN")
    dialogue_ids = _dialogue_ids(unit)
    bindings = unit.get("dialogue_audio_bindings") or []
    by_id = {str(row.get("dialogue_id")): row for row in bindings}
    if set(by_id) != set(dialogue_ids):
        failures.append(f"dialogue_audio_coverage_mismatch:{unit_id}")
        return
    for dialogue_id, row in by_id.items():
        path_value = str(row.get("path") or "")
        slot = str(row.get("audio_slot") or "")
        if not path_value or not slot:
            failures.append(f"dialogue_audio_binding_incomplete:{unit_id}:{dialogue_id}")
            continue
        path = _resolve(base, path_value)
        if not path.is_file():
            failures.append(f"dialogue_audio_missing:{unit_id}:{dialogue_id}:{path}")
            continue
        expected_sha = str(row.get("sha256") or "")
        if len(expected_sha) != 64 or _sha256(path) != expected_sha:
            failures.append(f"dialogue_audio_sha_mismatch:{unit_id}:{dialogue_id}")
    if len(dialogue_ids) > 1 and unit.get("same_speaker_contiguous_dialogue") is True:
        paths = {str(row.get("path")) for row in bindings}
        slots = {str(row.get("audio_slot")) for row in bindings}
        if unit.get("dialogue_audio_strategy") != "SINGLE_BEAT_ALIGNED_CONTIGUOUS_AUDIO":
            failures.append(f"contiguous_dialogue_strategy_missing:{unit_id}")
        if len(paths) != 1 or len(slots) != 1:
            failures.append(f"contiguous_dialogue_split_across_modalities:{unit_id}")


def _validate_design(contract: dict[str, Any], base: Path) -> list[str]:
    failures: list[str] = []
    units = contract.get("units") or []
    order = [str(value) for value in contract.get("unit_order") or []]
    if contract.get("streaming_submission_policy") != STREAMING_POLICY:
        failures.append("episode_wide_wait_or_non_streaming_submission_policy")
    if contract.get("reference_count_policy") != REFERENCE_POLICY:
        failures.append("fixed_or_undeclared_reference_count_policy")
    if contract.get("duration_policy") != "NATURAL_PERFORMANCE_SECONDS_NO_ORIGINAL_DURATION_FLOOR":
        failures.append("mechanical_duration_or_original_duration_floor")
    boundaries = set(contract.get("split_boundary_evidence") or [])
    if not boundaries or not boundaries <= NATURAL_BOUNDARIES:
        failures.append("split_not_bound_to_authored_natural_boundary")
    if len(units) < 2:
        failures.append("split_requires_at_least_two_replacement_units")
    if order != [str(unit.get("unit_id")) for unit in units]:
        failures.append("unit_order_does_not_match_replacement_sequence")
    split_orders = [unit.get("split_order") for unit in units]
    if split_orders != list(range(1, len(units) + 1)):
        failures.append("split_order_not_contiguous")
    source_unit = str(contract.get("source_unit_id") or "")
    if not source_unit or any(unit.get("replaces_unit_id") != source_unit for unit in units):
        failures.append("replacement_source_coverage_mismatch")
    seen_dialogue: set[str] = set()
    for unit in units:
        unit_id = str(unit.get("unit_id") or "UNKNOWN")
        reference_plan = unit.get("reference_plan") or {}
        if reference_plan.get("policy") != REFERENCE_POLICY:
            failures.append(f"unit_reference_policy_not_dynamic:{unit_id}")
        count = reference_plan.get("selected_count")
        if not isinstance(count, int) or count < 0:
            failures.append(f"unit_reference_count_invalid:{unit_id}")
        if not str(reference_plan.get("rationale") or "").strip():
            failures.append(f"unit_reference_rationale_missing:{unit_id}")
        dialogue_ids = _dialogue_ids(unit)
        duplicates = seen_dialogue.intersection(dialogue_ids)
        if duplicates:
            failures.append(f"dialogue_assigned_to_multiple_units:{','.join(sorted(duplicates))}")
        seen_dialogue.update(dialogue_ids)
        _validate_motion_beats(unit, failures)
        _validate_dialogue_bindings(unit, base, failures)
    expected_dialogue = set(contract.get("source_dialogue_ids") or [])
    if seen_dialogue != expected_dialogue:
        failures.append("source_dialogue_not_exactly_partitioned")
    return failures


def _validate_config(
    contract: dict[str, Any], config: dict[str, Any], failures: list[str]
) -> None:
    if config.get("streaming_submission_policy") != STREAMING_POLICY:
        failures.append("config_blocks_until_whole_batch_ready")
    expected = {str(row["unit_id"]): row for row in contract.get("units") or []}
    tasks = [
        task for task in config.get("tasks") or []
        if str(task.get("unit_id") or "") in expected
    ]
    if not tasks:
        failures.append("config_contains_no_contracted_split_unit")
        return
    unknown = [
        str(task.get("unit_id")) for task in config.get("tasks") or []
        if task.get("replaces_unit_id") == contract.get("source_unit_id")
        and str(task.get("unit_id")) not in expected
    ]
    failures.extend(f"config_unknown_replacement_unit:{value}" for value in unknown)
    for task in tasks:
        unit_id = str(task["unit_id"])
        spec = expected[unit_id]
        if task.get("replaces_unit_id") != spec.get("replaces_unit_id"):
            failures.append(f"config_replacement_source_mismatch:{unit_id}")
        if task.get("split_order") != spec.get("split_order"):
            failures.append(f"config_split_order_mismatch:{unit_id}")
        task_dialogue = [str(row.get("dia_id")) for row in task.get("dialogue") or []]
        if task_dialogue != spec.get("dialogue_ids"):
            failures.append(f"config_dialogue_order_mismatch:{unit_id}")
        task_beats = (task.get("performance_spec") or {}).get("motion_beats") or []
        if len(task_beats) != len(spec.get("motion_beats") or []):
            failures.append(f"config_motion_beat_count_mismatch:{unit_id}")
        visual_count = len(task.get("reference_images") or []) + len(task.get("reference_videos") or [])
        if visual_count != (spec.get("reference_plan") or {}).get("selected_count"):
            failures.append(f"config_reference_count_mismatch:{unit_id}")
        task_audio = {
            str(row.get("dia_id")): (str(row.get("path")), str(row.get("audio_slot")))
            for row in task.get("dialogue_audio_assets") or []
        }
        for row in spec.get("dialogue_audio_bindings") or []:
            actual = task_audio.get(str(row["dialogue_id"]))
            expected_binding = (str(row["path"]), str(row["audio_slot"]))
            if actual != expected_binding:
                failures.append(f"config_dialogue_audio_mismatch:{unit_id}:{row['dialogue_id']}")


def _validate_admission(
    contract: dict[str, Any], admission: dict[str, Any], base: Path, failures: list[str]
) -> None:
    expected = {str(row["unit_id"]): row for row in contract.get("units") or []}
    rows = admission.get("units") or []
    by_unit = {str(row.get("unit_id")): row for row in rows}
    if set(by_unit) != set(expected):
        failures.append("post_generation_replacement_coverage_mismatch")
        return
    for unit_id, spec in expected.items():
        row = by_unit[unit_id]
        decision = str(row.get("decision") or "")
        if decision not in ACCEPTED_ADMISSIONS:
            failures.append(f"unit_not_admitted:{unit_id}:{decision}")
        candidate_value = str(row.get("candidate_path") or "")
        candidate = _resolve(base, candidate_value) if candidate_value else Path()
        if not candidate_value or not candidate.is_file():
            failures.append(f"candidate_missing:{unit_id}")
            continue
        if _sha256(candidate) != row.get("candidate_sha256"):
            failures.append(f"candidate_sha_mismatch:{unit_id}")
        if set(row.get("dialogue_ids_asr_pass") or []) != set(spec.get("dialogue_ids") or []):
            failures.append(f"asr_dialogue_coverage_mismatch:{unit_id}")
        required_passes = {"identity", "scene_authority", "audio_stream", "frame_cadence", "story_facts"}
        passes = row.get("preserved_passes") or {}
        if any(passes.get(key) != "PASS" for key in required_passes):
            failures.append(f"required_source_pass_missing:{unit_id}")
        if decision == "CONDITIONAL_MACHINE_ADMISSION":
            for key in (
                "original_qa_status",
                "original_failures",
                "selection_reason",
                "confidence",
                "rollback_point",
                "replacement_condition",
            ):
                if row.get(key) in (None, "", []):
                    failures.append(f"conditional_admission_field_missing:{unit_id}:{key}")


def evaluate(
    contract: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
    admission: dict[str, Any] | None = None,
    base: Path = ROOT,
) -> dict[str, Any]:
    failures = _validate_design(contract, base)
    if config is not None:
        _validate_config(contract, config, failures)
    if admission is not None:
        _validate_admission(contract, admission, base, failures)
    return {
        "schema": "qingshan.performance_unit_natural_split_gate.v1",
        "gate_id": "VIDEO-PERFORMANCE-NATURAL-SPLIT",
        "episode": contract.get("episode"),
        "source_unit_id": contract.get("source_unit_id"),
        "status": "PASS" if not failures else "FAIL",
        "invoked": True,
        "design_checked": True,
        "submission_config_checked": config is not None,
        "post_generation_admission_checked": admission is not None,
        "replacement_unit_count": len(contract.get("units") or []),
        "failures": failures,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--admission", type=Path)
    parser.add_argument("--base", type=Path, default=ROOT)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    result = evaluate(
        _load(args.contract.resolve()),
        config=_load(args.config.resolve()) if args.config else None,
        admission=_load(args.admission.resolve()) if args.admission else None,
        base=args.base.resolve(),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "failures": result["failures"], "out": str(args.out)}, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
