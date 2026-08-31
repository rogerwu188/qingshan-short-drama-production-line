#!/usr/bin/env python3
"""MiniMax-H3 official full-reference (Ref2VA) prompt compiler.

The provider-facing prompt is deliberately separated from the internal Chinese
directing contract.  MiniMax's Ref2VA grammar reserves non-English source text
for dialogue/lyrics inside ``<d>`` (or truly visible scene text, which this
production line forbids).  Role, map, wardrobe, prop, action, transition and
sound gates remain structured machine evidence and are rendered here as
natural English inside the six official sections.
"""

from __future__ import annotations

import re
from typing import Any


H3_OFFICIAL_REF2VA_PROFILE = "H3_OFFICIAL_REF2VA_V1"
H3_OFFICIAL_REF2VA_POLICY = "qingshan.minimax_h3_ref2va.v1_official_six_section"
H3_REF2VA_FIELDS = (
    "subject_definitions:",
    "summary:",
    "retention_analysis:",
    "detailed_description:",
    "overall_soundscape:",
    "non_diegetic_music:",
)
REQUIRED_CONSTRAINT_COVERAGE = {
    "identity",
    "wardrobe",
    "map",
    "props",
    "screen_direction",
    "lighting",
    "camera",
    "action_physics",
    "microexpression",
    "transition",
    "text_free",
    "native_sound",
    "dialogue_roles",
}

REFERENCE_TEXT_AUDIT_STATUS = "PASS_TEXT_FREE_REFERENCES"

_DIALOGUE = re.compile(r"<d>\[([A-Za-z][A-Za-z -]*)\]\s*(.*?)</d>", re.DOTALL)
_CJK = re.compile(r"[\u3400-\u9fff]")
_SPEAKER = re.compile(r"\(S\d+\)")
_SHOT_RANGE = re.compile(
    r"(?<![A-Za-z0-9])(?:\d+(?:\.\d+)?\s*(?:-|–|—|to)\s*\d+(?:\.\d+)?\s*(?:s|sec|seconds))",
    re.IGNORECASE,
)
_SHOT_TIMESTAMP = re.compile(r"\[Shot\s+(\d+)\](?:\s+At\s+(\d{2}:\d{2}\.\d{3}),)?")


def _dialogues(unit: dict[str, Any]) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for spec in unit.get("ordered_prompt_specs") or []:
        raw = str(spec.get("dialogue") or "").strip()
        if not raw:
            continue
        speaker, sep, words = raw.partition("：")
        if not sep or not speaker.strip() or not words.strip():
            raise ValueError(f"H3 dialogue must use speaker：text format: {raw}")
        rows.append((speaker.strip(), words.strip()))
    return rows


def _contract(unit: dict[str, Any]) -> dict[str, Any]:
    value = unit.get("h3_ref2va_contract") or (unit.get("machine_contract") or {}).get(
        "h3_ref2va_contract"
    )
    if not isinstance(value, dict):
        raise ValueError("H3_OFFICIAL_REF2VA_CONTRACT_MISSING")
    return value


def _lines(value: Any, field: str) -> str:
    if isinstance(value, str):
        text = value.strip()
    elif isinstance(value, list):
        text = "\n".join(str(row).strip() for row in value if str(row).strip())
    else:
        text = ""
    if not text:
        raise ValueError(f"H3_OFFICIAL_REF2VA_EMPTY_SECTION:{field}")
    return text


def _validate_reference_text_audit(
    unit: dict[str, Any], contract: dict[str, Any], source_id: str
) -> tuple[list[str], dict[str, Any]]:
    """Fail closed when an H3 visual reference can seed visible writing.

    Ref2VA deliberately retains reference-image content.  A prose-only
    ``no text`` instruction cannot safely override writing already present in
    an anchor, so every official H3 Ref2VA contract must carry auditable,
    per-picture evidence.  This is intentionally H3-only; Seedance/SD2 never
    imports or calls this compiler.
    """
    failures: list[str] = []
    refs = [str(value) for value in (unit.get("reference_images") or [])]
    audit = contract.get("reference_text_audit")
    if not isinstance(audit, dict):
        return [f"H3_REF2VA_REFERENCE_TEXT_AUDIT_MISSING:{source_id}"], {
            "status": "MISSING",
            "picture_count": 0,
        }
    if audit.get("status") != REFERENCE_TEXT_AUDIT_STATUS:
        failures.append(f"H3_REF2VA_REFERENCE_TEXT_AUDIT_NOT_PASS:{source_id}")
    if int(audit.get("picture_count") or 0) != len(refs):
        failures.append(
            f"H3_REF2VA_REFERENCE_TEXT_AUDIT_COUNT_MISMATCH:{source_id}:"
            f"{audit.get('picture_count')}:{len(refs)}"
        )
    rows = audit.get("rows")
    if not isinstance(rows, list) or len(rows) != len(refs):
        failures.append(f"H3_REF2VA_REFERENCE_TEXT_AUDIT_ROWS_MISMATCH:{source_id}")
        rows = []
    by_index = {
        int(row.get("picture_index") or 0): row
        for row in rows
        if isinstance(row, dict)
    }
    for index, reference_image in enumerate(refs, 1):
        row = by_index.get(index)
        if not row:
            failures.append(f"H3_REF2VA_REFERENCE_TEXT_AUDIT_ROW_MISSING:{source_id}:{index}")
            continue
        if str(row.get("reference_image") or "") != reference_image:
            failures.append(f"H3_REF2VA_REFERENCE_TEXT_AUDIT_PATH_MISMATCH:{source_id}:{index}")
        if row.get("readable_text_detected") is not False:
            failures.append(f"H3_REF2VA_REFERENCE_READABLE_TEXT_PRESENT:{source_id}:{index}")
        if row.get("character_like_marks_detected") is not False:
            failures.append(f"H3_REF2VA_REFERENCE_CHARACTER_MARKS_PRESENT:{source_id}:{index}")
        if not str(row.get("reference_sha256") or "").strip():
            failures.append(f"H3_REF2VA_REFERENCE_TEXT_AUDIT_SHA_MISSING:{source_id}:{index}")
        if not str(row.get("evidence_ref") or "").strip():
            failures.append(f"H3_REF2VA_REFERENCE_TEXT_AUDIT_EVIDENCE_MISSING:{source_id}:{index}")
    return failures, {
        "status": audit.get("status") or "UNKNOWN",
        "picture_count": len(rows),
    }


def compile_h3_official_ref2va_prompt(unit: dict[str, Any]) -> str:
    """Serialize an approved English Ref2VA contract into the exact six sections."""
    if str(unit.get("model") or "MiniMax-H3").strip().lower() not in {"minimax-h3", "h3"}:
        raise ValueError("H3 official Ref2VA compiler only accepts MiniMax-H3")
    refs = unit.get("reference_images") or []
    duration = float(unit.get("duration_seconds") or 0)
    if not 1 <= len(refs) <= 9:
        raise ValueError("H3 official Ref2VA requires 1-9 reference images")
    if not 3 <= duration <= 15:
        raise ValueError("H3 official Ref2VA duration must be 3-15 seconds")
    contract = _contract(unit)
    rendered = []
    for field in H3_REF2VA_FIELDS:
        key = field[:-1]
        rendered.append(field)
        rendered.append(_lines(contract.get(key), key))
    text = "\n".join(rendered).strip() + "\n"
    report = validate_h3_official_ref2va_prompt(
        text, source_id=str(unit.get("unit_id") or "UNKNOWN"), unit=unit
    )
    if report["status"] != "PASS":
        raise ValueError(";".join(report["failures"]))
    return text


def validate_h3_official_ref2va_prompt(
    text: str, *, source_id: str, unit: dict[str, Any]
) -> dict[str, Any]:
    failures: list[str] = []
    positions: list[int] = []
    for field in H3_REF2VA_FIELDS:
        count = text.count(field)
        if count != 1:
            failures.append(f"H3_REF2VA_SECTION_COUNT:{source_id}:{field}:{count}")
        positions.append(text.find(field))
    if any(value < 0 for value in positions) or positions != sorted(positions):
        failures.append(f"H3_REF2VA_SECTION_ORDER:{source_id}")

    tagged = _DIALOGUE.findall(text)
    outside = _DIALOGUE.sub("", text)
    if _CJK.search(outside):
        failures.append(f"H3_REF2VA_CJK_OUTSIDE_DIALOGUE:{source_id}")
    if any(mark in text for mark in ('"', "“", "”", "‘", "’")):
        failures.append(f"H3_REF2VA_QUOTED_TEXT_FORBIDDEN:{source_id}")
    if "ROLE_LOCK" in text or "ROLE_RULE" in text:
        failures.append(f"H3_REF2VA_MACHINE_ROLE_BLOCK_EXPOSED:{source_id}")
    if _SHOT_RANGE.search(outside):
        failures.append(f"H3_REF2VA_SENTENCE_TIME_RANGE_FORBIDDEN:{source_id}")

    expected = [words for _, words in _dialogues(unit)]
    actual = [words.strip() for _, words in tagged]
    if actual != expected:
        failures.append(f"H3_REF2VA_DIALOGUE_SEQUENCE_MISMATCH:{source_id}")
    for words in expected:
        if text.count(words) != 1:
            failures.append(f"H3_REF2VA_DIALOGUE_LITERAL_COUNT:{source_id}:{text.count(words)}")

    contract = unit.get("h3_ref2va_contract") or (unit.get("machine_contract") or {}).get(
        "h3_ref2va_contract"
    ) or {}
    reference_audit_failures, reference_audit_summary = _validate_reference_text_audit(
        unit, contract, source_id
    )
    failures.extend(reference_audit_failures)
    coverage = contract.get("constraint_coverage") or {}
    missing_coverage = sorted(
        key for key in REQUIRED_CONSTRAINT_COVERAGE if coverage.get(key) is not True
    )
    if missing_coverage:
        failures.append(
            f"H3_REF2VA_CONSTRAINT_COVERAGE_MISSING:{source_id}:" + ",".join(missing_coverage)
        )

    detailed = ""
    if "detailed_description:" in text and "overall_soundscape:" in text:
        detailed = text.split("detailed_description:", 1)[1].split("overall_soundscape:", 1)[0]
    english_word_count = len(re.findall(r"\b[A-Za-z][A-Za-z'-]*\b", _DIALOGUE.sub("", detailed)))
    if not 350 <= english_word_count <= 500:
        failures.append(
            f"H3_REF2VA_DETAILED_WORD_COUNT:{source_id}:{english_word_count}:EXPECTED_350_500"
        )

    shots = _SHOT_TIMESTAMP.findall(detailed)
    if not shots or shots[0][0] != "1" or shots[0][1]:
        failures.append(f"H3_REF2VA_SHOT_ONE_FORMAT:{source_id}")
    for expected_index, (number, timestamp) in enumerate(shots, 1):
        if int(number) != expected_index:
            failures.append(f"H3_REF2VA_SHOT_SEQUENCE:{source_id}:{number}")
        if expected_index > 1 and not timestamp:
            failures.append(f"H3_REF2VA_SHOT_TIMESTAMP_MISSING:{source_id}:{number}")

    speaker_ids = _SPEAKER.findall(text)
    if expected:
        expected_speakers: list[str] = []
        for speaker, _ in _dialogues(unit):
            if speaker not in expected_speakers:
                expected_speakers.append(speaker)
        subject_bindings = contract.get("speaker_subject_bindings") or {}
        if set(subject_bindings) != set(expected_speakers):
            failures.append(f"H3_REF2VA_SPEAKER_SUBJECT_BINDING_MISMATCH:{source_id}")
        for index, speaker in enumerate(expected_speakers, 1):
            subject = str(subject_bindings.get(speaker) or "")
            if not re.fullmatch(r"<Subject \d+>", subject):
                failures.append(f"H3_REF2VA_SPEAKER_SUBJECT_INVALID:{source_id}:{speaker}")
                continue
            if f"{subject} (S{index})" not in text:
                failures.append(f"H3_REF2VA_SPEAKER_ID_NOT_BOUND:{source_id}:{speaker}:S{index}")
        if "the original dialogue content" not in text or "not carried" not in text:
            failures.append(f"H3_REF2VA_AUDIO_ANTI_CARRYOVER_MISSING:{source_id}")
    else:
        if tagged:
            failures.append(f"H3_REF2VA_SILENT_UNIT_DIALOGUE_PRESENT:{source_id}")
        if speaker_ids:
            failures.append(f"H3_REF2VA_SILENT_UNIT_SPEAKER_ID_PRESENT:{source_id}")
        lowered = text.lower()
        if not re.search(r"produces? no speech", lowered) or "lips closed" not in lowered:
            failures.append(f"H3_REF2VA_SILENT_POSITIVE_STATE_MISSING:{source_id}")

    refs = unit.get("reference_images") or []
    for index in range(1, len(refs) + 1):
        if f"<Picture {index}>" not in text:
            failures.append(f"H3_REF2VA_PICTURE_REFERENCE_MISSING:{source_id}:{index}")
    if "blank and unmarked" not in text.lower():
        failures.append(f"H3_REF2VA_TEXT_FREE_POSITIVE_STATE_MISSING:{source_id}")
    if "non_diegetic_music:\nN/A" not in text:
        failures.append(f"H3_REF2VA_NON_DIEGETIC_MUSIC_NOT_NA:{source_id}")

    return {
        "policy": H3_OFFICIAL_REF2VA_POLICY,
        "profile": H3_OFFICIAL_REF2VA_PROFILE,
        "status": "PASS" if not failures else "FAIL",
        "source_id": source_id,
        "character_count": len(text),
        "detailed_english_word_count": english_word_count,
        "dialogue_count": len(tagged),
        "cjk_outside_dialogue_count": len(_CJK.findall(outside)),
        "reference_text_audit": reference_audit_summary,
        "failures": failures,
    }
