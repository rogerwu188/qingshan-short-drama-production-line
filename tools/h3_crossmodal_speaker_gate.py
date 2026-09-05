#!/usr/bin/env python3
"""Fail-closed H3 character/image/speaker/audio binding.

MiniMax-H3 sees image, speaker and audio references as independently numbered
inputs. A prompt must never rely on ordinal coincidence between those lists.
Each spoken line is resolved through the canonical character id. H3 speaker
changes are paid generation-task boundaries. Seedance is deliberately outside
this gate so its established named voice grammar remains unchanged.
"""

from __future__ import annotations

import re
from typing import Any


POLICY = "qingshan.h3_crossmodal_speaker_gate.v1_atomic_speaker_turn"
_AUDIO_SLOT = re.compile(r"^@(?:音频|Audio)(\d+)$", re.IGNORECASE)
_SUBJECT = re.compile(r"^SUBJECT_(\d+)$")


def _is_h3(unit: dict[str, Any]) -> bool:
    return str(unit.get("model") or "").strip().lower() in {"minimax-h3", "h3"}


def _dialogue_speakers(unit: dict[str, Any]) -> list[str]:
    speakers: list[str] = []
    for spec in unit.get("ordered_prompt_specs") or []:
        raw = str(spec.get("dialogue") or "").strip()
        if not raw:
            continue
        speaker, separator, words = raw.partition("：")
        if not separator or not speaker.strip() or not words.strip():
            raise ValueError(f"H3_DIALOGUE_SPEAKER_FORMAT_INVALID:{raw}")
        if speaker.strip() not in speakers:
            speakers.append(speaker.strip())
    return speakers


def evaluate(unit: dict[str, Any]) -> dict[str, Any]:
    source_id = str(unit.get("unit_id") or unit.get("task_key") or "UNKNOWN")
    if not _is_h3(unit):
        return {
            "schema": POLICY,
            "source_id": source_id,
            "status": "NOT_APPLICABLE",
            "bindings": [],
            "failures": [],
        }

    failures: list[str] = []
    speakers = _dialogue_speakers(unit)
    if len(speakers) > 1:
        failures.append(
            f"H3_SPEAKER_CHANGE_REQUIRES_ATOMIC_VIDEO_UNIT:{source_id}:"
            + ",".join(speakers)
        )

    voice_contract = unit.get("speaker_voice_contract") or {}
    names = [str(row.get("speaker") or "").strip() for row in voice_contract.get("bindings") or []]
    if len(set(names)) != len(names):
        failures.append(f"H3_DUPLICATE_SPEAKER_VOICE_BINDING:{source_id}")
    voice_by_speaker = {
        str(row.get("speaker") or "").strip(): row
        for row in voice_contract.get("bindings") or []
        if str(row.get("speaker") or "").strip()
    }
    subject_map = unit.get("provider_entity_token_map") or {}
    identity_rows = (
        (unit.get("provider_scope_projection") or {}).get("reference_identity_bindings")
        or []
    )
    bindings: list[dict[str, Any]] = []
    used_image_slots: set[str] = set()
    used_audio_slots: set[str] = set()
    used_subjects: set[str] = set()

    for speaker in speakers:
        voice = voice_by_speaker.get(speaker)
        if not voice:
            failures.append(
                f"H3_SPEAKER_VOICE_CONTRACT_BINDING_MISSING:{source_id}:{speaker}"
            )
            continue
        character_id = str(voice.get("character_id") or "").strip()
        if not character_id:
            failures.append(f"H3_SPEAKER_CHARACTER_ID_MISSING:{source_id}:{speaker}")
            continue

        raw_audio_slot = str(voice.get("audio_slot") or "").strip()
        audio_match = _AUDIO_SLOT.fullmatch(raw_audio_slot)
        if not audio_match or int(audio_match.group(1)) < 1:
            failures.append(
                f"H3_SPEAKER_AUDIO_SLOT_INVALID:{source_id}:{speaker}:{raw_audio_slot}"
            )
            continue
        audio_index = int(audio_match.group(1))
        audio_slot = f"@Audio{audio_index}"
        speaker_slot = f"SPEAKER_{audio_index}"

        subject = str(subject_map.get(speaker) or "").strip()
        if not _SUBJECT.fullmatch(subject):
            failures.append(f"H3_SPEAKER_SUBJECT_BINDING_MISSING:{source_id}:{speaker}")
            continue

        matches = [
            row for row in identity_rows
            if str(row.get("entity_id") or "").strip() == character_id
        ]
        if len(matches) != 1:
            failures.append(
                f"H3_SPEAKER_IMAGE_BINDING_COUNT:{source_id}:{speaker}:{character_id}:{len(matches)}"
            )
            continue
        reference_index = matches[0].get("reference_index")
        if type(reference_index) is not int or reference_index < 1:
            failures.append(
                f"H3_SPEAKER_IMAGE_SLOT_INVALID:{source_id}:{speaker}:"
                f"{matches[0].get('reference_index')}"
            )
            continue
        if "reference_images" in unit and reference_index > len(unit["reference_images"]):
            failures.append(f"H3_SPEAKER_IMAGE_SLOT_OUT_OF_RANGE:{source_id}:{speaker}")
            continue
        if "reference_audio_urls" in unit and audio_index > len(unit["reference_audio_urls"]):
            failures.append(f"H3_SPEAKER_AUDIO_SLOT_OUT_OF_RANGE:{source_id}:{speaker}")
            continue
        image_slot = f"@Image{reference_index}"
        label = str(
            matches[0].get("provider_entity_label")
            or matches[0].get("canonical_name")
            or speaker
        ).strip()

        for slot, used, code in (
            (image_slot, used_image_slots, "IMAGE"),
            (audio_slot, used_audio_slots, "AUDIO"),
            (subject, used_subjects, "SUBJECT"),
        ):
            if slot in used:
                failures.append(f"H3_SPEAKER_{code}_SLOT_DUPLICATE:{source_id}:{slot}")
            used.add(slot)

        bindings.append({
            "speaker": speaker,
            "character_id": character_id,
            "provider_entity_label": label,
            "subject_token": subject,
            "image_slot": image_slot,
            "speaker_slot": speaker_slot,
            "audio_slot": audio_slot,
            "voice_reference_asset_id": voice.get("voice_reference_asset_id"),
            "visible_speaker": bool(voice.get("visible_speaker")),
            "lip_sync": bool(voice.get("lip_sync")),
        })

    if len(bindings) != len(speakers):
        failures.append(
            f"H3_CROSSMODAL_SPEAKER_COVERAGE_MISMATCH:{source_id}:"
            f"{len(bindings)}:{len(speakers)}"
        )
    return {
        "schema": POLICY,
        "source_id": source_id,
        "status": "PASS" if not failures else "FAIL",
        "policy": "ONE_NAMED_SPEAKING_IDENTITY_PER_H3_GENERATION_TASK",
        "dialogue_speakers": speakers,
        "bindings": bindings,
        "failures": failures,
    }


def require(unit: dict[str, Any]) -> dict[str, Any]:
    report = evaluate(unit)
    if report["status"] == "FAIL":
        raise ValueError(";".join(report["failures"]))
    return report
