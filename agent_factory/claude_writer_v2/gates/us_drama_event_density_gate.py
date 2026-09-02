#!/usr/bin/env python3
"""Validate the registered US-drama pacing and narrative-causal contract.

The structure extension is authorized by
ROGER-20260818-US-PACING-V2-RESTRUCTURE. It is enforced for E41+; older
episodes remain backtest-only so the extension cannot retroactively invalidate
an already released or in-production episode.

The causal extension is authorized by Roger's 2026-08-21 correction that
scene-count, location-name and self-reported event inflation do not constitute
fast American-TV storytelling.  E41+ therefore requires a separately bound
``narrative_canonical`` whose story moves are verified against its real text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

try:
    from canonical_writer_provenance import validate_writer_provenance
except ModuleNotFoundError:
    from tools.canonical_writer_provenance import validate_writer_provenance


STRUCTURE_AUTHORIZATION = "ROGER-20260818-US-PACING-V2-RESTRUCTURE"
CAUSAL_AUTHORIZATION = "ROGER-20260821-NARRATIVE-CANONICAL-CAUSAL-V3"
STRUCTURE_START_EPISODE = 41
NARRATIVE_START_EPISODE = 41
NARRATIVE_SCHEMA = "qingshan.narrative_canonical.v3"
MIN_STORY_MOVES_PER_MINUTE = 3.2
MIN_AGENCY_MOVE_RATIO = 0.50
MAX_CONSECUTIVE_DISCOVERY_MOVES = 1
MAX_NARRATIVE_CHARACTERS_PER_MINUTE = 1400
AGENCY_MOVE_TYPES = {
    "IRREVERSIBLE_ACTION",
    "POWER_SHIFT",
    "RELATIONSHIP_SHIFT",
    "FORCED_CHOICE",
}
ALLOWED_MOVE_TYPES = AGENCY_MOVE_TYPES | {"MATERIAL_FACT", "PAYOFF"}
PRODUCTION_MARKERS = {
    "shot_treatment",
    "first_frame_motion_state",
    "ambient_life",
    "spatial_action_contract",
    "voice_asset_id",
    "SUBSPACE-ID",
    "GLOBAL-SPACE-MAP-ID",
    "首帧动势",
    "景别",
    "运镜",
    "palette",
    "负向提示词",
}
STABLE_LOCATION_ID = re.compile(r"^LOC-[A-Z0-9][A-Z0-9_-]*$")
STABLE_TIME_BLOCK_ID = re.compile(r"^TIME-[A-Z0-9][A-Z0-9_-]*$")
STATE_TOKEN = re.compile(r"^STATE-[A-Z0-9][A-Z0-9_.:-]*$")
MOVE_ID = re.compile(r"^MOVE-[A-Z0-9][A-Z0-9_-]*$")


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


def _visible_character_count(text: str) -> int:
    return len(re.sub(r"\s+", "", text or ""))


def _causal_contract_evaluation(
    manifest: dict,
    *,
    narrative_text: str | None,
) -> tuple[list[str], list[str], dict]:
    """Verify the story authority rather than trusting Writer self-report.

    The contract deliberately models a causal DAG, not a fixed act template.
    A story move must point to literal evidence in the bound narrative text,
    consume a predecessor state and create a distinct result state.  A causal
    cluster may contain only one countable move, preventing one investigation
    chain from being split into many pseudo-events.
    """

    failures: list[str] = []
    warnings: list[str] = []
    contract = manifest.get("narrative_canonical")
    if not isinstance(contract, dict):
        return ["NARRATIVE_CANONICAL_CONTRACT_MISSING"], warnings, {
            "narrative_canonical_present": False
        }

    if contract.get("schema") != NARRATIVE_SCHEMA:
        failures.append("NARRATIVE_CANONICAL_SCHEMA_INVALID")
    if not str(contract.get("authority_path") or "").strip():
        failures.append("NARRATIVE_CANONICAL_PATH_MISSING")
    if contract.get("production_contracts_externalized") is not True:
        failures.append("PRODUCTION_CONTRACTS_NOT_EXTERNALIZED")

    authority_sha = str(contract.get("authority_sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", authority_sha):
        failures.append("NARRATIVE_CANONICAL_SHA_MISSING_OR_INVALID")
    if narrative_text is None:
        failures.append("NARRATIVE_CANONICAL_TEXT_UNAVAILABLE")
        narrative_text = ""
    elif hashlib.sha256(narrative_text.encode("utf-8")).hexdigest() != authority_sha:
        failures.append("NARRATIVE_CANONICAL_SHA_MISMATCH")

    found_markers = sorted(marker for marker in PRODUCTION_MARKERS if marker in narrative_text)
    if found_markers:
        failures.append("PRODUCTION_METADATA_INSIDE_NARRATIVE_CANONICAL")

    target, _, _, _, _ = _runtime_contract(manifest)
    visible_characters = _visible_character_count(narrative_text)
    characters_per_minute = visible_characters / (target / 60.0) if target else 0.0
    if target and characters_per_minute > MAX_NARRATIVE_CHARACTERS_PER_MINUTE:
        failures.append("NARRATIVE_CANONICAL_TEXT_BLOAT")

    scenes = contract.get("scene_sequence") or []
    if not isinstance(scenes, list) or not scenes:
        failures.append("NARRATIVE_SCENE_SEQUENCE_MISSING")
        scenes = []
    scene_ids: set[str] = set()
    location_ids: set[str] = set()
    time_block_ids: set[str] = set()
    for index, scene in enumerate(scenes, 1):
        if not isinstance(scene, dict):
            failures.append(f"NARRATIVE_SCENE_INVALID:{index}")
            continue
        scene_id = str(scene.get("scene_id") or "")
        location_id = str(scene.get("location_id") or "")
        time_block_id = str(scene.get("time_block_id") or "")
        if not scene_id or scene_id in scene_ids:
            failures.append(f"NARRATIVE_SCENE_ID_MISSING_OR_DUPLICATE:{index}")
        scene_ids.add(scene_id)
        if not STABLE_LOCATION_ID.fullmatch(location_id):
            failures.append(f"UNSTABLE_LOCATION_ID:{scene_id or index}")
        else:
            location_ids.add(location_id)
        if not STABLE_TIME_BLOCK_ID.fullmatch(time_block_id):
            failures.append(f"UNSTABLE_TIME_BLOCK_ID:{scene_id or index}")
        else:
            time_block_ids.add(time_block_id)
        if not str(scene.get("thread_id") or "").strip():
            failures.append(f"SCENE_THREAD_ID_MISSING:{scene_id or index}")
        if not scene.get("story_move_ids"):
            failures.append(f"SCENE_WITHOUT_STORY_MOVE:{scene_id or index}")

    time_blocks = contract.get("time_blocks") or []
    declared_time_blocks: set[str] = set()
    meaningful_time_jumps = 0
    for index, block in enumerate(time_blocks, 1):
        if not isinstance(block, dict):
            failures.append(f"TIME_BLOCK_INVALID:{index}")
            continue
        block_id = str(block.get("time_block_id") or "")
        if not STABLE_TIME_BLOCK_ID.fullmatch(block_id) or block_id in declared_time_blocks:
            failures.append(f"TIME_BLOCK_ID_MISSING_OR_DUPLICATE:{index}")
        declared_time_blocks.add(block_id)
        before = str(block.get("before_condition_token") or "")
        after = str(block.get("after_condition_token") or "")
        change = str(block.get("action_condition_change") or "").strip()
        if before and after and before != after and change:
            meaningful_time_jumps += 1
    if time_block_ids - declared_time_blocks:
        failures.append("SCENE_TIME_BLOCK_NOT_DECLARED")

    moves = contract.get("story_moves") or []
    if not isinstance(moves, list) or not moves:
        failures.append("STORY_MOVES_MISSING")
        moves = []
    move_ids: list[str] = []
    move_by_id: dict[str, dict] = {}
    cluster_ids: set[str] = set()
    result_tokens: set[str] = set()
    agency_count = 0
    discovery_run = 0
    max_discovery_run = 0
    for index, move in enumerate(moves, 1):
        if not isinstance(move, dict):
            failures.append(f"STORY_MOVE_INVALID:{index}")
            continue
        move_id = str(move.get("story_move_id") or "")
        if not MOVE_ID.fullmatch(move_id) or move_id in move_by_id:
            failures.append(f"STORY_MOVE_ID_MISSING_OR_DUPLICATE:{index}")
        else:
            move_ids.append(move_id)
            move_by_id[move_id] = move
        move_type = str(move.get("move_type") or "").upper()
        if move_type not in ALLOWED_MOVE_TYPES:
            failures.append(f"STORY_MOVE_TYPE_INVALID:{move_id or index}")
        if move_type in AGENCY_MOVE_TYPES:
            agency_count += 1
            discovery_run = 0
        else:
            discovery_run += 1
            max_discovery_run = max(max_discovery_run, discovery_run)
        cluster_id = str(move.get("causal_cluster_id") or "")
        if not cluster_id or cluster_id in cluster_ids:
            failures.append(f"CAUSAL_CLUSTER_FRAGMENTED:{cluster_id or index}")
        cluster_ids.add(cluster_id)
        cause_token = str(move.get("cause_state_token") or "")
        result_token = str(move.get("result_state_token") or "")
        if not STATE_TOKEN.fullmatch(cause_token) or not STATE_TOKEN.fullmatch(result_token):
            failures.append(f"STORY_STATE_TOKEN_INVALID:{move_id or index}")
        elif cause_token == result_token or result_token in result_tokens:
            failures.append(f"STORY_STATE_NOT_NET_NEW:{move_id or index}")
        result_tokens.add(result_token)
        if not str(move.get("action") or "").strip() or not str(move.get("external_change") or "").strip():
            failures.append(f"STORY_MOVE_CAUSAL_CONTENT_MISSING:{move_id or index}")
        scene_id = str(move.get("scene_id") or "")
        if scene_id not in scene_ids:
            failures.append(f"STORY_MOVE_SCENE_UNKNOWN:{move_id or index}")
        evidence = str(move.get("evidence_text") or "").strip()
        if not evidence or narrative_text.count(evidence) != 1:
            failures.append(f"STORY_MOVE_EVIDENCE_NOT_EXACTLY_ONCE:{move_id or index}")

    for index, move_id in enumerate(move_ids):
        move = move_by_id[move_id]
        predecessors = [str(value) for value in move.get("predecessor_move_ids") or []]
        for predecessor in predecessors:
            if predecessor not in move_by_id or move_ids.index(predecessor) >= index:
                failures.append(f"STORY_MOVE_PREDECESSOR_INVALID:{move_id}:{predecessor}")
        if index > 0 and not predecessors:
            failures.append(f"STORY_MOVE_ORPHANED:{move_id}")
        elif predecessors:
            predecessor_results = {
                str(move_by_id[predecessor].get("result_state_token") or "")
                for predecessor in predecessors
                if predecessor in move_by_id
            }
            if str(move.get("cause_state_token") or "") not in predecessor_results:
                failures.append(f"STORY_MOVE_CAUSE_STATE_NOT_FROM_PREDECESSOR:{move_id}")
        forced_next = str(move.get("forces_next_story_move_id") or "")
        if index < len(move_ids) - 1:
            if forced_next not in move_by_id or move_ids.index(forced_next) <= index:
                failures.append(f"STORY_MOVE_NEXT_CAUSAL_LINK_INVALID:{move_id}")
        elif forced_next:
            failures.append(f"FINAL_STORY_MOVE_MUST_NOT_FORCE_UNKNOWN_NEXT:{move_id}")

    scene_move_refs: list[str] = []
    for scene in scenes:
        if isinstance(scene, dict):
            scene_move_refs.extend(str(value) for value in scene.get("story_move_ids") or [])
    if sorted(scene_move_refs) != sorted(move_ids):
        failures.append("SCENE_STORY_MOVE_BINDING_MISMATCH")

    move_rate = len(moves) / (target / 60.0) if target else 0.0
    agency_ratio = agency_count / len(moves) if moves else 0.0
    if move_rate < MIN_STORY_MOVES_PER_MINUTE:
        failures.append("STORY_MOVE_DENSITY_BELOW_MINIMUM")
    if agency_ratio < MIN_AGENCY_MOVE_RATIO:
        failures.append("AGENCY_MOVE_RATIO_BELOW_MINIMUM")
    if max_discovery_run > MAX_CONSECUTIVE_DISCOVERY_MOVES:
        failures.append("CONSECUTIVE_DISCOVERY_CHAIN_TOO_LONG")

    return list(dict.fromkeys(failures)), warnings, {
        "narrative_canonical_present": True,
        "schema": contract.get("schema"),
        "authority_sha256": authority_sha,
        "production_contracts_externalized": contract.get("production_contracts_externalized"),
        "visible_character_count": visible_characters,
        "characters_per_runtime_minute": round(characters_per_minute, 3),
        "production_markers_found": found_markers,
        "scene_count": len(scenes),
        "stable_location_count": len(location_ids),
        "stable_time_block_count": len(time_block_ids),
        "meaningful_time_jump_count": meaningful_time_jumps,
        "story_move_count": len(moves),
        "story_moves_per_minute": round(move_rate, 3),
        "agency_move_count": agency_count,
        "agency_move_ratio": round(agency_ratio, 3),
        "maximum_consecutive_discovery_moves": max_discovery_run,
        "causal_cluster_count": len(cluster_ids),
    }


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

    causal_moves = (manifest.get("narrative_canonical") or {}).get("story_moves") or []
    planned_events = len(causal_moves) or int(
        density.get("planned_event_count") or pacing.get("countable_events") or 0
    )
    declared_rate = dialogue_pacing.get("true_event_density_per_min") or pacing.get("events_per_minute")
    observed_rate = (
        planned_events / (target / 60) if target else 0.0
    ) if causal_moves else (
        _float(declared_rate) if declared_rate is not None else (
            planned_events / (target / 60) if target else 0.0
        )
    )
    hard_min = MIN_STORY_MOVES_PER_MINUTE if causal_moves else _float(
        density.get("hard_min_per_minute"), 4.0
    )
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

    # v3: scene count, location variety, clock movement and cross-cut volume are
    # useful diagnostics, not proxies for story velocity.  They were previously
    # easy to game by splitting one scene or renaming corners of one room.
    if not 8 <= scene_count <= 12:
        warnings.append("DIAGNOSTIC_SCENE_COUNT_OUT_OF_REFERENCE_RANGE")
    if max_scene_seconds > 22:
        failures.append("SCENE_TOO_LONG")
    if distinct_locations < 4:
        warnings.append("DIAGNOSTIC_LOCATION_VARIETY_LOW")
    if max_consecutive > 2:
        failures.append("LOCATION_STAGNATION")
    if time_jumps < 1:
        warnings.append("DIAGNOSTIC_NO_CLOCK_TIME_JUMP")
    if parallel_threads < 2:
        failures.append("NO_PARALLEL_THREAD")
    if cross_cuts < 3:
        warnings.append("DIAGNOSTIC_FEW_CROSS_CUTS")
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
        warnings.append("LEGACY_EVENT_LIST_NOT_IN_CAUSAL_FORM")

    mechanical_template, template_counts = _template_failure(manifest, history)
    if mechanical_template:
        warnings.append("DIAGNOSTIC_MECHANICAL_SCENE_TEMPLATE")
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


def evaluate(
    manifest: dict,
    *,
    history_manifests: Iterable[dict] = (),
    structure_mode: str = "auto",
    narrative_text: str | None = None,
    writer_receipt: dict[str, Any] | None = None,
    writer_receipt_sha256: str | None = None,
) -> dict:
    numeric_failures, numeric_observed = _numeric_evaluation(manifest)
    structure_failures, structure_warnings, structure_observed = _structure_evaluation(
        manifest, history_manifests
    )
    causal_failures, causal_warnings, causal_observed = _causal_contract_evaluation(
        manifest, narrative_text=narrative_text
    )
    authority_sha = str((manifest.get("narrative_canonical") or {}).get("authority_sha256") or "")
    provenance_failures, provenance_observed = validate_writer_provenance(
        manifest,
        receipt=writer_receipt,
        receipt_sha256=writer_receipt_sha256,
        authority_sha256=authority_sha,
    )
    episode_number = _episode_number(manifest.get("episode"))
    if structure_mode not in {"auto", "enforce", "warn"}:
        raise ValueError(f"unsupported structure_mode: {structure_mode}")
    structure_enforced = structure_mode == "enforce" or (
        structure_mode == "auto" and episode_number is not None and episode_number >= STRUCTURE_START_EPISODE
    )
    narrative_enforced = structure_mode == "enforce" or (
        structure_mode == "auto" and episode_number is not None and episode_number >= NARRATIVE_START_EPISODE
    )
    warnings = list(structure_warnings)
    warnings.extend(causal_warnings)
    if not structure_enforced:
        warnings.extend(f"BACKTEST_ONLY:{failure}" for failure in structure_failures)
    if not narrative_enforced:
        warnings.extend(f"BACKTEST_ONLY:{failure}" for failure in causal_failures)
        warnings.extend(f"BACKTEST_ONLY:{failure}" for failure in provenance_failures)
    blocking_failures = (
        numeric_failures
        + (structure_failures if structure_enforced else [])
        + (causal_failures if narrative_enforced else [])
        + (provenance_failures if narrative_enforced else [])
    )

    return {
        "schema": "qingshan.us_drama_event_density_gate.v3",
        "episode": manifest.get("episode"),
        "status": "PASS" if not blocking_failures else "FAIL",
        "authorization_ref": f"{STRUCTURE_AUTHORIZATION};{CAUSAL_AUTHORIZATION}",
        "scope": "R-49_NARRATIVE_CAUSAL_V3",
        "hard_policy": {
            "legacy_event_density_min_per_minute": 4.0,
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
            "dialogue_lines_per_minute_is_reference_only": True,
            "scene_location_time_crosscut_counts_are_diagnostic": True,
            "story_moves_min_per_minute": MIN_STORY_MOVES_PER_MINUTE,
            "agency_move_ratio_minimum": MIN_AGENCY_MOVE_RATIO,
            "maximum_consecutive_discovery_moves": MAX_CONSECUTIVE_DISCOVERY_MOVES,
            "maximum_narrative_characters_per_minute": MAX_NARRATIVE_CHARACTERS_PER_MINUTE,
            "production_contracts_must_be_externalized": True
        },
        "structure_enforcement": {
            "mode": structure_mode,
            "effective": structure_enforced,
            "starts_at_episode": f"E{STRUCTURE_START_EPISODE}",
            "legacy_episode_failures_are_warnings": True
        },
        "narrative_enforcement": {
            "effective": narrative_enforced,
            "starts_at_episode": f"E{NARRATIVE_START_EPISODE}",
            "legacy_episode_failures_are_warnings": True,
        },
        "observed": {
            **numeric_observed,
            "structure_v2": structure_observed,
            "structure_v2_diagnostic": structure_observed,
            "narrative_causal_v3": causal_observed,
            "writer_provenance": provenance_observed,
        },
        "numeric_failures": numeric_failures,
        "structure_failures": structure_failures,
        "narrative_causal_failures": causal_failures,
        "writer_provenance_failures": provenance_failures,
        "warnings": list(dict.fromkeys(warnings)),
        "failures": blocking_failures,
        "machine_decision": True,
        "confidence": 0.96 if not blocking_failures else 0.99,
        "rollback": "Delete only the gate report; the source manifest is not modified.",
        "scope_note": (
            "E41+ enforces bound narrative-causal truth plus non-gameable structural checks; "
            "scene/location/time/cross-cut quantities are diagnostic. E40 and earlier are warning-only backtests."
        )
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
    parser.add_argument("--narrative-canonical", type=Path)
    parser.add_argument("--writer-receipt", type=Path)
    parser.add_argument("--history-manifest", action="append", default=[], type=Path)
    parser.add_argument("--structure-mode", choices=("auto", "enforce", "warn"), default="auto")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    narrative_path = args.narrative_canonical
    if narrative_path is None:
        configured = (manifest.get("narrative_canonical") or {}).get("authority_path")
        if configured:
            configured_path = Path(str(configured))
            candidates = [
                configured_path,
                args.manifest.parent / configured_path,
                Path(__file__).resolve().parents[1] / configured_path,
            ]
            narrative_path = next((path for path in candidates if path.exists()), configured_path)
    narrative_text = (
        narrative_path.read_text(encoding="utf-8")
        if narrative_path is not None and narrative_path.exists()
        else None
    )
    receipt_path = args.writer_receipt
    if receipt_path is None:
        configured = (manifest.get("writer_provenance") or {}).get("receipt_path")
        if configured:
            configured_path = Path(str(configured))
            candidates = [
                configured_path,
                args.manifest.parent / configured_path,
                Path(__file__).resolve().parents[1] / configured_path,
            ]
            receipt_path = next((path for path in candidates if path.exists()), configured_path)
    writer_receipt = (
        json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt_path is not None and receipt_path.exists()
        else None
    )
    writer_receipt_sha256 = (
        file_sha256(receipt_path)
        if receipt_path is not None and receipt_path.exists()
        else None
    )
    history_paths = args.history_manifest or discover_history_manifests(args.manifest, manifest.get("episode"))
    history = [json.loads(path.read_text(encoding="utf-8")) for path in history_paths]
    report = evaluate(
        manifest,
        history_manifests=history,
        structure_mode=args.structure_mode,
        narrative_text=narrative_text,
        writer_receipt=writer_receipt,
        writer_receipt_sha256=writer_receipt_sha256,
    )
    report["manifest"] = str(args.manifest)
    report["manifest_sha256"] = file_sha256(args.manifest)
    report["history_manifests"] = [str(path) for path in history_paths]
    report["narrative_canonical"] = str(narrative_path) if narrative_path else None
    report["writer_receipt"] = str(receipt_path) if receipt_path else None
    report["recorded_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "out": str(args.out), "failures": report["failures"]}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
