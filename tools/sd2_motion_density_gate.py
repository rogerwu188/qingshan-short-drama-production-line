#!/usr/bin/env python3
"""Deterministic SD2 motion/state-delta gates for pre-submit QA."""

from __future__ import annotations

import re
from typing import Any


POLICY_VERSION = "qingshan.video_motion_density.v4_shared_sd2_h3_typed_state_delta"

STATE_DELTA_DIMENSIONS = (
    "POSITION",
    "POSTURE",
    "CONTACT",
    "POSSESSION",
    "INTEGRITY",
    "MOMENTUM",
)

IMPULSE_VERBS = (
    "踹开", "踹破", "踹爆", "砸入", "砸进", "砸开", "砸倒", "劈落",
    "劈开", "劈中", "撞偏", "撞开", "撞翻", "撞中", "格开", "掀翻",
    "贯入", "贯穿", "甩开", "刺入", "直刺", "切开", "震开", "击中",
    "击倒", "击飞", "抡出", "拍开", "扫倒", "摔落", "摔碎", "崩开",
    "横扫", "爆发扫向", "扑近", "猛冲", "闪开", "侧移", "刺穿",
)

EXTEND_WORDS = ("持续", "保持", "连续")


def impulse_verb_hits(text: object) -> list[str]:
    value = str(text or "")
    return [verb for verb in IMPULSE_VERBS if verb in value]


def extend_word_hits(text: object) -> list[str]:
    value = str(text or "")
    return [word for word in EXTEND_WORDS for _ in re.finditer(re.escape(word), value)]


def validate_state_delta(
    beat: dict[str, Any], *, combat: bool, source_id: str
) -> dict[str, Any]:
    failures: list[str] = []
    dimensions = list(beat.get("state_delta_dimensions") or [])
    evidence = beat.get("state_delta_evidence") or {}
    if len(dimensions) != len(set(dimensions)):
        failures.append(f"STATE_DELTA_DUPLICATE_DIMENSION:{source_id}")
    unknown = [value for value in dimensions if value not in STATE_DELTA_DIMENSIONS]
    if unknown:
        failures.append(f"STATE_DELTA_UNKNOWN_DIMENSION:{source_id}:{','.join(unknown)}")
    minimum = 2 if combat else 1
    if len(dimensions) < minimum:
        failures.append(
            f"STATE_DELTA_DIMENSION_COUNT:{source_id}:{len(dimensions)}<{minimum}"
        )
    for dimension in dimensions:
        row = evidence.get(dimension) or {}
        entry = str(row.get("entry") or "").strip()
        exit_state = str(row.get("exit") or "").strip()
        entry_code = str(row.get("entry_code") or "").strip().upper()
        exit_code = str(row.get("exit_code") or "").strip().upper()
        if not entry or not exit_state:
            failures.append(f"STATE_DELTA_EVIDENCE_MISSING:{source_id}:{dimension}")
        elif entry == exit_state:
            failures.append(f"STATE_DELTA_EVIDENCE_NO_CHANGE:{source_id}:{dimension}")
        if not entry_code or not exit_code:
            failures.append(f"STATE_DELTA_EVIDENCE_CODE_MISSING:{source_id}:{dimension}")
        elif entry_code == exit_code:
            failures.append(
                f"STATE_DELTA_EVIDENCE_CODE_NO_CHANGE:{source_id}:{dimension}:{entry_code}"
            )
    entry_state = str(beat.get("entry_state") or "").strip()
    exit_state = str(beat.get("exit_state") or "").strip()
    if not entry_state or not exit_state:
        failures.append(f"STATE_ENDPOINT_MISSING:{source_id}")
    elif entry_state == exit_state:
        failures.append(f"STATE_ENDPOINT_IDENTICAL:{source_id}")
    return {
        "schema": POLICY_VERSION,
        "status": "PASS" if not failures else "FAIL",
        "source_id": source_id,
        "combat": combat,
        "state_delta_dimensions": dimensions,
        "state_delta_evidence": evidence,
        "failures": failures,
    }


def validate_combat_impulse(
    beat: dict[str, Any], *, duration_seconds: float, source_id: str
) -> dict[str, Any]:
    failures: list[str] = []
    duration = float(duration_seconds)
    start = float(beat.get("start_seconds") or 0.0)
    contact = beat.get("contact_time_seconds")
    if not isinstance(contact, (int, float)):
        failures.append(f"COMBAT_CONTACT_TIME_MISSING:{source_id}")
        ratio = None
        entry_to_contact = None
    else:
        contact = float(contact)
        ratio = contact / duration if duration > 0 else None
        entry_to_contact = contact - start
        if ratio is None or ratio < 0.25 or ratio > 0.75:
            failures.append(f"COMBAT_CONTACT_RATIO:{source_id}:{ratio}")
        if entry_to_contact < 0 or entry_to_contact > 1.2:
            failures.append(
                f"COMBAT_ENTRY_TO_CONTACT:{source_id}:{entry_to_contact:.3f}>1.2"
            )
    primary = str(beat.get("primary_action") or "")
    impulse_hits = impulse_verb_hits(primary)
    if not impulse_hits:
        failures.append(f"COMBAT_IMPULSE_VERB_MISSING:{source_id}")
    action_fields = " ".join(str(beat.get(key) or "") for key in (
        "entry_state", "primary_action", "contact_point", "force_feedback", "exit_state"
    ))
    extend_hits = extend_word_hits(action_fields)
    if extend_hits:
        failures.append(
            f"COMBAT_EXTEND_WORD_FORBIDDEN:{source_id}:{','.join(extend_hits)}"
        )
    failures.extend(validate_combat_causal_chain(beat, source_id=source_id))
    delta = validate_state_delta(beat, combat=True, source_id=source_id)
    failures.extend(delta["failures"])
    return {
        "schema": POLICY_VERSION,
        "status": "PASS" if not failures else "FAIL",
        "source_id": source_id,
        "duration_seconds": duration,
        "contact_ratio": ratio,
        "entry_to_contact_seconds": entry_to_contact,
        "impulse_verb_hits": impulse_hits,
        "extend_word_hits": extend_hits,
        "state_delta": delta,
        "failures": failures,
    }


def validate_combat_causal_chain(beat: dict[str, Any], *, source_id: str) -> list[str]:
    failures: list[str] = []
    interaction_mode = str(beat.get("interaction_mode") or "").upper()
    if interaction_mode not in {"CONTACT", "EVASION", "THREAT_THRESHOLD"}:
        failures.append(f"COMBAT_INTERACTION_MODE_INVALID:{source_id}:{interaction_mode or 'MISSING'}")
    if not str(beat.get("force_origin") or "").strip():
        failures.append(f"COMBAT_FORCE_ORIGIN_MISSING:{source_id}")
    if not str(beat.get("primary_feedback") or beat.get("force_feedback") or "").strip():
        failures.append(f"COMBAT_PRIMARY_FEEDBACK_MISSING:{source_id}")
    if len(beat.get("secondary_feedback") or []) > 1:
        failures.append(f"COMBAT_SECONDARY_FEEDBACK_LIMIT:{source_id}")
    contact_text = " ".join(str(beat.get(key) or "") for key in (
        "contact_point", "primary_action", "exit_state"
    ))
    non_contact = any(token in contact_text for token in (
        "一掌距离", "尚未接触", "没有接触", "未碰到", "尚未碰到", "接触前"
    ))
    dimensions = set(beat.get("state_delta_dimensions") or [])
    if interaction_mode == "CONTACT" and non_contact:
        failures.append(f"AMBIGUOUS_CONTACT_TYPE:{source_id}:CONTACT_AND_NON_CONTACT")
    if interaction_mode in {"EVASION", "THREAT_THRESHOLD"} and "CONTACT" in dimensions:
        failures.append(f"AMBIGUOUS_CONTACT_TYPE:{source_id}:{interaction_mode}_WITH_CONTACT_DELTA")
    patient = str(beat.get("action_patient") or "").strip()
    if patient and beat.get("e51_rectification_required") is True:
        patient_dimensions = set(beat.get("patient_state_delta_dimensions") or [])
        if not patient_dimensions.intersection({"POSITION", "POSTURE"}):
            failures.append(f"COMBAT_PATIENT_STATE_DELTA_MISSING:{source_id}:{patient}")
        evidence = beat.get("patient_state_delta_evidence") or {}
        for dimension in patient_dimensions.intersection({"POSITION", "POSTURE"}):
            row = evidence.get(dimension) or {}
            if not str(row.get("entry") or "").strip() or not str(row.get("exit") or "").strip():
                failures.append(f"COMBAT_PATIENT_STATE_DELTA_EVIDENCE_MISSING:{source_id}:{patient}:{dimension}")
            elif str(row.get("entry")).strip() == str(row.get("exit")).strip():
                failures.append(f"COMBAT_PATIENT_STATE_DELTA_NO_CHANGE:{source_id}:{patient}:{dimension}")
    return failures


def validate_execution_plan(plan: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    unit_id = str(plan.get("unit_id") or "UNKNOWN")
    unit_class = str(plan.get("unit_class") or "")
    duration = float(plan.get("duration_seconds") or 0.0)
    classification = plan.get("unit_classification_gate") or {}
    failures.extend(classification.get("failures") or [])
    failures.extend((plan.get("camera_authority_gate") or {}).get("failures") or [])
    if unit_class == "COMBAT_EXCHANGE" and classification.get("required") is True:
        contact_count = int(classification.get("combat_contact_count") or 0)
        if duration < 7.0 or duration > 12.0 or contact_count > 2:
            failures.append(
                f"UNIT_CLASS_LAUNDERING:{unit_id}:COMBAT_EXCHANGE_REQUIRES_7_TO_12_SECONDS_AND_AT_MOST_2_CONTACTS"
            )
    duration_authority = plan.get("duration_authority") or {}
    underfill = float(duration_authority.get("underfill_seconds") or 0.0)
    if underfill > 0.05:
        failures.append(
            f"DURATION_EXCEEDS_AUTHORIZED_CONTENT:{unit_id}:{underfill:.3f}s"
        )
    beats = plan.get("beats") or []
    if not beats:
        failures.append(f"EXECUTION_BEATS_MISSING:{unit_id}")
    cursor = 0.0
    reports = []
    for index, beat in enumerate(beats, 1):
        source_id = f"{unit_id}:BEAT_{index}"
        start = float(beat.get("start_seconds") or 0.0)
        end = float(beat.get("end_seconds") or 0.0)
        if abs(start - cursor) > 0.02 or end <= start:
            failures.append(f"EXECUTION_TIMELINE_INVALID:{source_id}:{start}->{end}")
        cursor = end
        # Mixed units are legitimate: a short atmosphere/recovery beat may
        # border a combat beat without becoming combat itself. Validate each
        # beat against its authoritative action kind instead of forcing every
        # beat in a COMBAT_EXCHANGE unit through the interaction gate.
        source_action_kind = str(beat.get("source_action_kind") or "").upper()
        failures.extend(beat.get("prop_state_failures") or [])
        beat_is_combat = (
            source_action_kind == "COMBAT"
            if source_action_kind
            else unit_class in {"COMBAT_IMPULSE", "COMBAT_EXCHANGE"}
        )
        if unit_class == "COMBAT_IMPULSE" and beat_is_combat:
            report = validate_combat_impulse(
                beat, duration_seconds=duration, source_id=source_id
            )
        else:
            report = validate_state_delta(
                beat,
                combat=beat_is_combat,
                source_id=source_id,
            )
            if beat_is_combat:
                report["failures"].extend(
                    validate_combat_causal_chain(beat, source_id=source_id)
                )
                action_fields = " ".join(str(beat.get(key) or "") for key in (
                    "entry_state", "primary_action", "contact_point", "force_feedback", "exit_state"
                ))
                extend_hits = extend_word_hits(action_fields)
                if extend_hits:
                    report["failures"].append(
                        f"COMBAT_EXTEND_WORD_FORBIDDEN:{source_id}:{','.join(extend_hits)}"
                    )
                report["status"] = "PASS" if not report["failures"] else "FAIL"
        reports.append(report)
        failures.extend(report["failures"])
    if abs(cursor - duration) > 0.02:
        failures.append(f"EXECUTION_DURATION_MISMATCH:{unit_id}:{cursor}!={duration}")
    return {
        "schema": POLICY_VERSION,
        "status": "PASS" if not failures else "FAIL",
        "unit_id": unit_id,
        "unit_class": unit_class,
        "beat_reports": reports,
        "failures": failures,
    }
