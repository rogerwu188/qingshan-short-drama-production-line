#!/usr/bin/env python3
"""Shared pre-generation dialogue handles and post-generation cut safety."""

from __future__ import annotations

import copy
import math
import re
from typing import Any


SCHEMA = "qingshan.dialogue_cut_safety.v1"
DEFAULT_SAFETY_PAD_SECONDS = 0.32
DEFAULT_CHINESE_CHARACTERS_PER_SECOND = 4.2


def spoken_text(raw: object) -> str:
    text = str(raw or "").strip()
    _, separator, words = text.partition("：")
    return words.strip() if separator else text


def estimated_spoken_seconds(raw: object) -> float:
    words = spoken_text(raw)
    if not words:
        return 0.0
    han = len(re.findall(r"[\u3400-\u9fff]", words))
    punctuation = len(re.findall(r"[，。！？；、,.!?;]", words))
    other = len(re.sub(r"[\u3400-\u9fff\s，。！？；、,.!?;]", "", words))
    return round(han / DEFAULT_CHINESE_CHARACTERS_PER_SECOND + punctuation * 0.16 + other * 0.08, 3)


def compile_dialogue_windows(unit: dict[str, Any]) -> list[dict[str, Any]]:
    specs = unit.get("ordered_prompt_specs") or []
    target = float(unit.get("duration_seconds") or 0)
    if not specs or target <= 0:
        return []
    source_spans = [
        max(0.001, float((spec.get("action") or {}).get("t1_seconds", 0)) - float((spec.get("action") or {}).get("t0_seconds", 0)))
        for spec in specs
    ]
    scale = target / sum(source_spans)
    outgoing = unit.get("outgoing_transition_contract") or {}
    tail = float(outgoing.get("outgoing_handle_seconds") or (0.8 if unit.get("outgoing_transition_contract") is None else 0))
    dialogue_deadline = target - tail
    cursor = 0.0
    rows: list[dict[str, Any]] = []
    for index, (spec, source_span) in enumerate(zip(specs, source_spans)):
        beat_end = target if index == len(specs) - 1 else cursor + source_span * scale
        raw = str(spec.get("dialogue") or "").strip()
        if raw:
            duration = estimated_spoken_seconds(raw)
            available_end = min(beat_end, dialogue_deadline if index == len(specs) - 1 else beat_end)
            start = cursor + 0.12
            end = start + duration
            if end + DEFAULT_SAFETY_PAD_SECONDS > available_end:
                raise ValueError(
                    f"{unit.get('unit_id')}:DIALOGUE_CANNOT_FIT_BEFORE_SAFE_CUT:"
                    f"beat={index + 1}:need={end + DEFAULT_SAFETY_PAD_SECONDS:.3f}:available={available_end:.3f}"
                )
            rows.append({
                "spec_index": index,
                "dialogue": raw,
                "start_seconds": round(start, 3),
                "end_seconds": round(end, 3),
                "safety_pad_seconds": DEFAULT_SAFETY_PAD_SECONDS,
                "must_be_silent_after_seconds": round(end, 3),
            })
        cursor = beat_end
    return rows


def minimum_dialogue_safe_integer_duration(
    unit: dict[str, Any], *, minimum: int = 4, maximum: int = 15
) -> int:
    """Return the first provider-valid integer duration preserving speech and tail handle."""
    last_error: ValueError | None = None
    for duration in range(minimum, maximum + 1):
        probe = copy.deepcopy(unit)
        probe["duration_seconds"] = duration
        try:
            compile_dialogue_windows(probe)
        except ValueError as error:
            last_error = error
            continue
        return duration
    raise ValueError(
        f"{unit.get('unit_id')}:DIALOGUE_CANNOT_FIT_PROVIDER_MAX_DURATION:{maximum}:{last_error}"
    )


def allocate_dialogue_safe_integer_durations(
    units: list[dict[str, Any]], *, total_seconds: int | None = None,
    minimum: int = 4, maximum: int = 15
) -> dict[str, int]:
    """Allocate authored pacing only after every unit's dialogue and tail handle fit.

    When ``total_seconds`` is omitted, episode duration is allowed to float.  This
    is the preferred production mode: every unit receives at least its authored
    rounded-up duration and may grow to satisfy speech safety.
    """
    authored = {str(row["unit_id"]): float(row["duration_seconds"]) for row in units}
    result = {
        str(row["unit_id"]): minimum_dialogue_safe_integer_duration(
            row, minimum=minimum, maximum=maximum
        )
        for row in units
    }
    if total_seconds is None:
        for uid, authored_seconds in authored.items():
            result[uid] = min(maximum, max(result[uid], math.ceil(authored_seconds)))
        return result
    current = sum(result.values())
    if current > total_seconds:
        raise ValueError(
            f"DIALOGUE_SAFE_MINIMUMS_EXCEED_EPISODE_RUNTIME:need={current}:available={total_seconds}"
        )
    remaining = total_seconds - current
    stable_order = {str(row["unit_id"]): index for index, row in enumerate(units)}
    while remaining:
        candidates = [uid for uid, value in result.items() if value < maximum]
        if not candidates:
            raise ValueError(
                f"DIALOGUE_SAFE_ALLOCATION_CANNOT_REACH_RUNTIME:remaining={remaining}:maximum={maximum}"
            )
        uid = max(
            candidates,
            key=lambda value: (
                authored[value] - result[value],
                -result[value],
                -stable_order[value],
            ),
        )
        result[uid] += 1
        remaining -= 1
    return result


def adapt_outgoing_handles_for_provider_limit(
    units: list[dict[str, Any]], *, minimum_duration: int = 4,
    maximum_duration: int = 15, minimum_tail_handle: float = 0.6
) -> list[dict[str, Any]]:
    """Reduce only an overlong unit's tail handle, never below the media contract.

    The same boundary value is mirrored into the following unit's incoming
    contract.  If dialogue still cannot fit at provider maximum, grouping must be
    split and the function fails closed.
    """
    rows = copy.deepcopy(units)
    for index, unit in enumerate(rows):
        try:
            minimum_dialogue_safe_integer_duration(
                unit, minimum=minimum_duration, maximum=maximum_duration
            )
            continue
        except ValueError:
            pass
        outgoing = unit.get("outgoing_transition_contract") or {}
        authored_tail = float(outgoing.get("outgoing_handle_seconds") or 0.8)
        candidates = sorted({authored_tail, 0.8, minimum_tail_handle}, reverse=True)
        selected: float | None = None
        for tail in candidates:
            if tail < minimum_tail_handle or tail > authored_tail:
                continue
            outgoing["outgoing_handle_seconds"] = tail
            unit["outgoing_transition_contract"] = outgoing
            try:
                minimum_dialogue_safe_integer_duration(
                    unit, minimum=minimum_duration, maximum=maximum_duration
                )
            except ValueError:
                continue
            selected = tail
            break
        if selected is None:
            raise ValueError(
                f"{unit.get('unit_id')}:REQUIRES_UNIT_SPLIT_AFTER_DIALOGUE_AND_MINIMUM_TAIL_HANDLE"
            )
        if index + 1 < len(rows):
            incoming = rows[index + 1].get("incoming_transition_contract") or {}
            if incoming.get("boundary_id") == outgoing.get("boundary_id"):
                incoming["outgoing_handle_seconds"] = selected
                rows[index + 1]["incoming_transition_contract"] = incoming
    return rows


def evaluate_cut(
    *,
    planned_cut_seconds: float,
    actual_duration_seconds: float,
    dialogue_end_seconds: float | None,
    trimmed_tail_max_volume_db: float | None,
    safety_pad_seconds: float = DEFAULT_SAFETY_PAD_SECONDS,
    active_audio_threshold_db: float = -42.0,
) -> dict[str, Any]:
    failures: list[str] = []
    cut = float(planned_cut_seconds)
    actual = float(actual_duration_seconds)
    if cut > actual + 0.05:
        failures.append("PLANNED_CUT_EXCEEDS_SOURCE_DURATION")
    if dialogue_end_seconds is not None and cut + 1e-6 < float(dialogue_end_seconds) + safety_pad_seconds:
        failures.append("CUT_BEFORE_DIALOGUE_END_SAFETY_PAD")
    if cut < actual - 0.05 and trimmed_tail_max_volume_db is not None and trimmed_tail_max_volume_db > active_audio_threshold_db:
        failures.append("TRIMMED_TAIL_CONTAINS_ACTIVE_AUDIO")
    return {
        "schema": SCHEMA,
        "status": "PASS" if not failures else "FAIL",
        "planned_cut_seconds": cut,
        "actual_duration_seconds": actual,
        "dialogue_end_seconds": dialogue_end_seconds,
        "safety_pad_seconds": safety_pad_seconds,
        "trimmed_tail_max_volume_db": trimmed_tail_max_volume_db,
        "failures": failures,
    }
