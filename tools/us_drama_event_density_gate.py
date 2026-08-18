#!/usr/bin/env python3
"""Validate the registered US-drama numeric and pacing-v2 structure contract.

The structure extension is authorized by
ROGER-20260818-US-PACING-V2-RESTRUCTURE. It is enforced for E41+; older
episodes remain backtest-only so the extension cannot retroactively invalidate
an already released or in-production episode.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


STRUCTURE_AUTHORIZATION = "ROGER-20260818-US-PACING-V2-RESTRUCTURE"
STRUCTURE_START_EPISODE = 41


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _float(value: Any, default: float = 0.0) -> float:
    if isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value)
        if not match:
            return default
        number = float(match.group(0))
        return number / 100.0 if "%" in value else number
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _episode_number(value: Any) -> int | None:
    match = re.search(r"(\d+)", str(value or ""))
    return int(match.group(1)) if match else None


def _runtime_contract(manifest: dict) -> tuple[float, float, float, float, bool]:
    runtime = manifest.get("runtime_target_seconds") or manifest.get("runtime_range_seconds") or {}
    target = _float(runtime.get("target") or manifest.get("total_seconds"))
    minimum = _float(runtime.get("min"), target)
    maximum = _float(runtime.get("max"), target)
    beats = manifest.get("structure") or []
    if beats:
        structure_seconds = sum(_float(row.get("target_seconds")) for row in beats)
    else:
        breakdown = manifest.get("scene_breakdown_seconds") or {}
        structure_seconds = sum(_float(value) for value in breakdown.values())
    return target, minimum, maximum, structure_seconds, bool(beats)


def _ratio_contract(manifest: dict, pacing: dict) -> tuple[float | None, float | None]:
    dialogue = manifest.get("dialogue_pacing") or {}
    episode_candidates = (
        pacing.get("dialogue_ratio"),
        manifest.get("dialogue_ratio"),
        dialogue.get("episode_dialogue_ratio"),
        dialogue.get("ratio_mid"),
    )
    episode_ratio = next((_float(value) for value in episode_candidates if value is not None), None)

    action_candidates = [
        pacing.get("action_scene_dialogue_ratio"),
        manifest.get("action_scene_dialogue_ratio"),
    ]
    action_candidates.extend(
        value
        for key, value in dialogue.items()
        if key.startswith("action_scene_") and (key.endswith("_ratio") or re.search(r"\d", key))
    )
    parsed_action = [_float(value) for value in action_candidates if value is not None]
    return episode_ratio, max(parsed_action) if parsed_action else None


def _numeric_evaluation(manifest: dict) -> tuple[list[str], dict]:
    failures: list[str] = []
    target, minimum, maximum, structure_seconds, has_numeric_structure = _runtime_contract(manifest)
    dialogue = manifest.get("dialogue_draft") or []
    dialogue_pacing = manifest.get("dialogue_pacing") or {}
    density = manifest.get("event_density") or {}
    pacing = manifest.get("pacing_v2") or {}

    if not (minimum <= target <= maximum and target > 0):
        failures.append("runtime_target_out_of_range")
    if has_numeric_structure and abs(structure_seconds - target) > 0.01:
        failures.append("structure_runtime_target_mismatch")

    planned_events = int(density.get("planned_event_count") or pacing.get("countable_events") or 0)
    declared_rate = dialogue_pacing.get("true_event_density_per_min") or pacing.get("events_per_minute")
    observed_rate = _float(declared_rate) if declared_rate is not None else (
        planned_events / (target / 60) if target else 0.0
    )
    hard_min = _float(density.get("hard_min_per_minute"), 4.0)
    if observed_rate < hard_min:
        failures.append("event_density_below_hard_minimum")
    gap_value = density.get("max_information_gap_seconds")
    if gap_value is None:
        gap_value = dialogue_pacing.get("max_no_progress_gap_seconds")
    max_gap = _float(gap_value, 20.0)
    if max_gap > 20:
        failures.append("maximum_information_gap_exceeds_20s")
    non_advancing = _float(density.get("non_advancing_percentage"), 0.0)
    if non_advancing > 15.0:
        failures.append("non_advancing_atmosphere_percentage_exceeds_15")

    dialogue_count = len(dialogue) or int(dialogue_pacing.get("lines_total") or dialogue_pacing.get("lines") or 0)
    dialogue_rate = dialogue_count / (target / 60) if target else 0.0
    return failures, {
        "runtime_target_seconds": target,
        "structure_target_seconds": structure_seconds,
        "planned_event_count": planned_events,
        "events_per_minute": round(observed_rate, 3),
        "max_information_gap_seconds": max_gap,
        "non_advancing_percentage": non_advancing,
        "dialogue_line_count": dialogue_count,
        "dialogue_lines_per_minute_reference": round(dialogue_rate, 3),
        "beat_count": len(manifest.get("structure") or []),
    }


def _template_failure(manifest: dict, history: Iterable[dict]) -> tuple[bool, list[int]]:
    current_episode = _episode_number(manifest.get("episode"))
    pacing = manifest.get("pacing_v2") or {}
    current_count = int(pacing.get("scene_count") or 0)
    if current_episode is None or current_count <= 0:
        return False, []
    episode_counts = {
        episode: int((row.get("pacing_v2") or {}).get("scene_count") or 0)
        for row in history
        if (episode := _episode_number(row.get("episode"))) is not None
    }
    counts = [episode_counts.get(current_episode - 2), episode_counts.get(current_episode - 1), current_count]
    same_three = all(count == current_count for count in counts)
    justification = pacing.get("scene_count_justification") or pacing.get("template_justification")
    return bool(same_three and not str(justification or "").strip()), [int(value or 0) for value in counts]


def _structure_evaluation(manifest: dict, history: Iterable[dict]) -> tuple[list[str], list[str], dict]:
    failures: list[str] = []
    warnings: list[str] = []
    pacing = manifest.get("pacing_v2")
    if not isinstance(pacing, dict):
        return ["PACING_V2_MISSING"], warnings, {"pacing_v2_present": False}

    scene_seconds = [_float(value) for value in pacing.get("scene_seconds") or []]
    scene_count = int(pacing.get("scene_count") or 0)
    max_scene_seconds = _float(pacing.get("max_scene_seconds"), max(scene_seconds, default=0.0))
    location_list = pacing.get("location_list") or []
    # CL2X-1195..1197 fixed the authoritative counting basis to location_list.
    distinct_locations = len(location_list)
    max_consecutive = int(pacing.get("max_consecutive_same_location") or 0)
    time_jumps = int(pacing.get("time_jumps") or 0)
    parallel_threads = int(pacing.get("parallel_threads") or 0)
    cross_cuts = int(pacing.get("cross_cuts") or 0)
    scenes_without_turn = int(pacing.get("scenes_without_turn") or 0)
    new_locations = int(pacing.get("new_locations_added") or 0)
    dialogue_ratio, action_ratio = _ratio_contract(manifest, pacing)
    event_list = pacing.get("event_list") or []

    if not 8 <= scene_count <= 12:
        failures.append("SCENE_COUNT_OUT_OF_RANGE")
    if max_scene_seconds > 22:
        failures.append("SCENE_TOO_LONG")
    if distinct_locations < 4:
        failures.append("TOO_FEW_LOCATIONS")
    if distinct_locations == 1:
        failures.append("SINGLE_LOCATION_EPISODE")
    if max_consecutive > 2:
        failures.append("LOCATION_STAGNATION")
    if time_jumps < 1:
        failures.append("NO_TIME_JUMP")
    if parallel_threads < 2:
        failures.append("NO_PARALLEL_THREAD")
    if cross_cuts < 3:
        failures.append("TOO_FEW_CROSS_CUTS")
    if scenes_without_turn != 0:
        failures.append("SCENE_WITHOUT_TURN")
    if new_locations > 2:
        failures.append("LOCATION_BUDGET_EXCEEDED")
    if dialogue_ratio is None:
        warnings.append("DIALOGUE_RATIO_UNAVAILABLE")
    elif dialogue_ratio > 0.35:
        failures.append("DIALOGUE_RATIO_EXCEEDED")
    if action_ratio is None:
        warnings.append("ACTION_SCENE_DIALOGUE_RATIO_UNAVAILABLE")
    elif action_ratio > 0.20:
        failures.append("DIALOGUE_RATIO_EXCEEDED")
    if not event_list or any(
        "→" not in str(event)
        or not all(part.strip() for part in str(event).split("→", 1))
        for event in event_list
    ):
        failures.append("EVENT_NOT_IN_CAUSAL_FORM")

    mechanical_template, template_counts = _template_failure(manifest, history)
    if mechanical_template:
        failures.append("MECHANICAL_SCENE_TEMPLATE")
    elif len(template_counts) < 3 or 0 in template_counts:
        warnings.append("TEMPLATE_HISTORY_INCOMPLETE")

    return list(dict.fromkeys(failures)), warnings, {
        "pacing_v2_present": True,
        "scene_count": scene_count,
        "scene_seconds": scene_seconds,
        "max_scene_seconds": max_scene_seconds,
        "distinct_locations_authoritative": distinct_locations,
        "distinct_locations_declared": pacing.get("distinct_locations"),
        "location_count_basis": "manifest.pacing_v2.location_list",
        "max_consecutive_same_location": max_consecutive,
        "time_jumps": time_jumps,
        "parallel_threads": parallel_threads,
        "cross_cuts": cross_cuts,
        "scenes_without_turn": scenes_without_turn,
        "new_locations_added": new_locations,
        "dialogue_ratio": dialogue_ratio,
        "action_scene_dialogue_ratio": action_ratio,
        "event_list_count": len(event_list),
        "template_scene_counts": template_counts,
    }


def evaluate(manifest: dict, *, history_manifests: Iterable[dict] = (), structure_mode: str = "auto") -> dict:
    numeric_failures, numeric_observed = _numeric_evaluation(manifest)
    structure_failures, structure_warnings, structure_observed = _structure_evaluation(
        manifest, history_manifests
    )
    episode_number = _episode_number(manifest.get("episode"))
    if structure_mode not in {"auto", "enforce", "warn"}:
        raise ValueError(f"unsupported structure_mode: {structure_mode}")
    structure_enforced = structure_mode == "enforce" or (
        structure_mode == "auto" and episode_number is not None and episode_number >= STRUCTURE_START_EPISODE
    )
    warnings = list(structure_warnings)
    if not structure_enforced:
        warnings.extend(f"BACKTEST_ONLY:{failure}" for failure in structure_failures)
    blocking_failures = numeric_failures + (structure_failures if structure_enforced else [])

    return {
        "schema": "qingshan.us_drama_event_density_gate.v2",
        "episode": manifest.get("episode"),
        "status": "PASS" if not blocking_failures else "FAIL",
        "authorization_ref": STRUCTURE_AUTHORIZATION,
        "scope": "R-49_NUMERIC_PLUS_STRUCTURE_V2",
        "hard_policy": {
            "event_density_min_per_minute": 4.0,
            "maximum_information_gap_seconds": 20,
            "scene_count_range": [8, 12],
            "maximum_scene_seconds": 22,
            "minimum_distinct_locations": 4,
            "maximum_consecutive_same_location": 2,
            "minimum_time_jumps": 1,
            "minimum_parallel_threads": 2,
            "minimum_cross_cuts": 3,
            "maximum_new_locations": 2,
            "maximum_dialogue_ratio": 0.35,
            "maximum_action_scene_dialogue_ratio": 0.20,
            "dialogue_lines_per_minute_is_reference_only": True
        },
        "structure_enforcement": {
            "mode": structure_mode,
            "effective": structure_enforced,
            "starts_at_episode": f"E{STRUCTURE_START_EPISODE}",
            "legacy_episode_failures_are_warnings": True
        },
        "observed": {**numeric_observed, "structure_v2": structure_observed},
        "numeric_failures": numeric_failures,
        "structure_failures": structure_failures,
        "warnings": list(dict.fromkeys(warnings)),
        "failures": blocking_failures,
        "machine_decision": True,
        "confidence": 0.96 if not blocking_failures else 0.99,
        "rollback": "Delete only the gate report; the source manifest is not modified.",
        "scope_note": "E41+ enforces numeric density plus pacing_v2 structure; E40 and earlier are warning-only backtests."
    }


def discover_history_manifests(manifest_path: Path, episode: Any) -> list[Path]:
    """Find the latest local manifest for each of the two prior episodes."""
    episode_number = _episode_number(episode)
    if episode_number is None:
        return []
    discovered: list[Path] = []
    for prior_episode in (episode_number - 2, episode_number - 1):
        candidates = sorted(
            manifest_path.parent.glob(f"E{prior_episode}_manifest*.json"),
            key=lambda path: (path.stat().st_mtime_ns, path.name),
        )
        if candidates:
            discovered.append(candidates[-1])
    return discovered


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--script", "--manifest", dest="manifest", required=True, type=Path)
    parser.add_argument("--history-manifest", action="append", default=[], type=Path)
    parser.add_argument("--structure-mode", choices=("auto", "enforce", "warn"), default="auto")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    history_paths = args.history_manifest or discover_history_manifests(args.manifest, manifest.get("episode"))
    history = [json.loads(path.read_text(encoding="utf-8")) for path in history_paths]
    report = evaluate(manifest, history_manifests=history, structure_mode=args.structure_mode)
    report["manifest"] = str(args.manifest)
    report["manifest_sha256"] = file_sha256(args.manifest)
    report["history_manifests"] = [str(path) for path in history_paths]
    report["recorded_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "out": str(args.out), "failures": report["failures"]}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
