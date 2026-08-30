#!/usr/bin/env python3
"""Compile and validate fail-closed speaker/voice bindings for video tasks.

The video model is allowed to synthesize the final performance, but it may not
invent which visible character owns a line or which recurring voice that
character uses.  H3 and Seedance share this machine contract while retaining
their own prompt compilers.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VOICE_REGISTRY = ROOT / "configs/series_voice_reference_registry_current_20260723.json"
POLICY_VERSION = "qingshan.speaker_voice_contract.v1_canonical_reference_and_lip_owner"

# Script display names can differ from the long-lived series registry name.
# Aliases are explicit because guessing by surname or visual proximity is the
# exact class of mistake this contract prevents.
SPEAKER_ENTITY_ALIASES = {
    "姚老头": "yao_taiyi",
    "年轻姚老头": "yao_taiyi",
    "洛城递信人": "messenger",
}

PRODUCTION_READY_STATUSES = {
    "LOCKED_PRODUCTION_READY",
    "AGENTCUT_GENERATED_REGISTERED_PRODUCTION_READY",
}


def _dialogues(unit: dict[str, Any]) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for spec in unit.get("ordered_prompt_specs") or []:
        raw = str(spec.get("dialogue") or "").strip()
        if not raw:
            continue
        speaker, separator, spoken = raw.partition("：")
        if not separator or not speaker.strip() or not spoken.strip():
            raise ValueError(f"dialogue must use speaker：text format: {raw}")
        rows.append((speaker.strip(), spoken.strip()))
    return rows


def _visible_characters(unit: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for spec in unit.get("ordered_prompt_specs") or []:
        for row in spec.get("cast") or []:
            name = str(row.get("character") or "").strip()
            visibility = str(row.get("face_visibility") or "").upper()
            if name and visibility != "OFFSCREEN_VOICE_ONLY" and name not in result:
                result.append(name)
    return result


def _sha(path: str) -> str | None:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    try:
        return hashlib.sha256(candidate.read_bytes()).hexdigest()
    except OSError:
        return None


def _registry_rows() -> list[dict[str, Any]]:
    configured = os.environ.get("QINGSHAN_VOICE_REGISTRY", "").strip()
    registry = Path(configured).expanduser() if configured else DEFAULT_VOICE_REGISTRY
    if not registry.is_absolute():
        registry = ROOT / registry
    if not registry.is_file():
        return []
    payload = json.loads(registry.read_text(encoding="utf-8"))
    rows = payload.get("major_roles")
    if not isinstance(rows, list):
        raise ValueError(f"voice registry major_roles must be a list: {registry}")
    return rows


def _voice_authority(voice_bible: dict[str, Any] | None = None) -> tuple[dict[str, dict], dict[str, dict]]:
    rows = list((voice_bible or {}).get("characters") or (voice_bible or {}).get("speakers") or [])
    rows.extend(_registry_rows())
    by_name: dict[str, dict] = {}
    by_entity: dict[str, dict] = {}
    for row in rows:
        name = str(row.get("character") or row.get("speaker") or row.get("name") or "").strip()
        entity = str(row.get("entity_id") or row.get("speaker_entity_id") or "").strip()
        if name and name not in by_name:
            by_name[name] = row
        if entity and entity not in by_entity:
            by_entity[entity] = row
    return by_name, by_entity


def compile_speaker_voice_contract(
    unit: dict[str, Any], voice_bible: dict[str, Any] | None = None
) -> dict[str, Any]:
    dialogues = _dialogues(unit)
    speakers: list[str] = []
    for speaker, _ in dialogues:
        if speaker not in speakers:
            speakers.append(speaker)
    visible = _visible_characters(unit)
    by_name, by_entity = _voice_authority(voice_bible)
    bindings: list[dict[str, Any]] = []
    failures: list[str] = []
    for index, speaker in enumerate(speakers, start=1):
        entity_hint = SPEAKER_ENTITY_ALIASES.get(speaker)
        source = by_name.get(speaker) or (by_entity.get(entity_hint) if entity_hint else None)
        if not source:
            failures.append(f"SPEAKER_CANONICAL_VOICE_NOT_REGISTERED:{speaker}")
            continue
        entity_id = str(source.get("entity_id") or source.get("speaker_entity_id") or entity_hint or "").strip()
        asset_id = str(source.get("remote_asset_id") or source.get("voice_reference_asset_id") or "").strip()
        local_reference = str(source.get("local_reference") or source.get("voice_reference") or "").strip()
        remote_url = str(source.get("remote_url") or source.get("voice_reference_url") or "").strip()
        status = str(source.get("status") or "LOCKED_PRODUCTION_READY")
        sha256 = str(source.get("local_sha256") or source.get("voice_reference_sha256") or "").strip()
        actual_sha = _sha(local_reference) if local_reference else None
        if status not in PRODUCTION_READY_STATUSES:
            failures.append(f"SPEAKER_CANONICAL_VOICE_NOT_PRODUCTION_READY:{speaker}:{status}")
        if not entity_id:
            failures.append(f"SPEAKER_ENTITY_ID_MISSING:{speaker}")
        if not asset_id:
            failures.append(f"SPEAKER_VOICE_ASSET_ID_MISSING:{speaker}")
        if not local_reference and not remote_url:
            failures.append(f"SPEAKER_VOICE_REFERENCE_MISSING:{speaker}")
        if str(unit.get("model") or "").lower() in {"minimax-h3", "h3"} and not remote_url.startswith("https://"):
            failures.append(f"H3_SPEAKER_VOICE_PUBLIC_URL_MISSING:{speaker}")
        if local_reference and (not actual_sha or (sha256 and actual_sha != sha256)):
            failures.append(f"SPEAKER_VOICE_REFERENCE_SHA_MISMATCH:{speaker}")
        bindings.append({
            "speaker": speaker,
            "speaker_entity_id": entity_id,
            "voice_reference_asset_id": asset_id,
            "voice_reference": local_reference or None,
            "voice_reference_url": remote_url or None,
            "voice_reference_sha256": sha256 or actual_sha,
            "audio_slot": f"@音频{index}",
            "visible_speaker": speaker in visible,
            "offscreen_voice": speaker not in visible,
            "lip_sync": speaker in visible,
            "production_voice_status": status,
        })
    contract = {
        "schema": POLICY_VERSION,
        "status": "PASS" if not failures else "FAIL",
        "unit_id": unit.get("unit_id"),
        "bindings": bindings,
        "dialogue_speakers": speakers,
        "visible_characters": visible,
        "silent_visible_characters": [name for name in visible if name not in speakers],
        "multi_speaker_policy": "DISTINCT_CANONICAL_AUDIO_SLOT_PER_SPEAKER_AND_EXACT_LIP_OWNER",
        "postgen_required_evidence": [
            "speaker_diarization_verification",
            "visible_lip_owner_verification",
            "canonical_voice_similarity_verification",
        ],
        "failures": failures,
    }
    return contract


def validate_speaker_voice_contract(unit: dict[str, Any]) -> dict[str, Any]:
    expected = []
    for speaker, _ in _dialogues(unit):
        if speaker not in expected:
            expected.append(speaker)
    contract = unit.get("speaker_voice_contract") or {}
    bindings = contract.get("bindings") or []
    actual = [str(row.get("speaker") or "") for row in bindings]
    failures: list[str] = []
    if expected:
        if contract.get("schema") != POLICY_VERSION:
            failures.append("SPEAKER_VOICE_CONTRACT_SCHEMA_MISSING_OR_STALE")
        if contract.get("status") != "PASS":
            failures.append("SPEAKER_VOICE_CONTRACT_NOT_PASS")
        if actual != expected:
            failures.append(f"SPEAKER_VOICE_COVERAGE_MISMATCH:{expected}:{actual}")
        slots = [str(row.get("audio_slot") or "") for row in bindings]
        if len(slots) != len(set(slots)) or any(not value for value in slots):
            failures.append("SPEAKER_AUDIO_SLOTS_MISSING_OR_DUPLICATE")
        for row in bindings:
            speaker = str(row.get("speaker") or "MISSING")
            for field in ("speaker_entity_id", "voice_reference_asset_id", "audio_slot"):
                if not str(row.get(field) or "").strip():
                    failures.append(f"SPEAKER_VOICE_BINDING_FIELD_MISSING:{speaker}:{field}")
            if not str(row.get("voice_reference") or "").strip() and not str(row.get("voice_reference_url") or "").strip():
                failures.append(f"SPEAKER_VOICE_REFERENCE_MISSING:{speaker}")
    elif bindings:
        failures.append("SILENT_UNIT_HAS_SPEAKER_VOICE_BINDINGS")
    return {
        "schema": "qingshan.speaker_voice_contract_gate.v1",
        "status": "PASS" if not failures else "FAIL",
        "unit_id": unit.get("unit_id"),
        "expected_speakers": expected,
        "actual_speakers": actual,
        "failures": failures,
    }


def attach_speaker_voice_contract(
    unit: dict[str, Any], voice_bible: dict[str, Any] | None = None
) -> dict[str, Any]:
    contract = compile_speaker_voice_contract(unit, voice_bible)
    if contract["status"] != "PASS":
        raise ValueError(";".join(contract["failures"]))
    unit["speaker_voice_contract"] = contract
    return contract


def speaker_voice_prompt_block(unit: dict[str, Any], *, model_family: str) -> str:
    report = validate_speaker_voice_contract(unit)
    if report["status"] != "PASS":
        raise ValueError(";".join(report["failures"]))
    contract = unit.get("speaker_voice_contract") or {}
    bindings = contract.get("bindings") or []
    if not bindings:
        return "本单元无对白，无需声线参考；所有可见人物闭口。"
    rows = []
    for row in bindings:
        speaker = row["speaker"]
        slot = row["audio_slot"]
        lip_rule = "仅该角色口型与其台词同步" if row.get("visible_speaker") else "仅作为画外声且画内人物不得代替张口"
        rows.append(f"{slot}只锁定{speaker}的固定音色、年龄与说话质感，{lip_rule}")
    silent = contract.get("silent_visible_characters") or []
    if silent:
        rows.append("以下可见角色全程不得代说或张口：" + "、".join(silent))
    rows.append("不得按画面位置、性别或上一句声线猜测说话人；不同角色不得共用声线")
    prefix = "H3发声实体锁" if model_family == "minimax-h3" else "SD2发声实体锁"
    return prefix + "：" + "；".join(rows) + "。"


def task_voice_transport(unit: dict[str, Any], dialogue_rows: list[dict[str, Any]]) -> dict[str, Any]:
    report = validate_speaker_voice_contract(unit)
    if report["status"] != "PASS":
        raise ValueError(";".join(report["failures"]))
    bindings = (unit.get("speaker_voice_contract") or {}).get("bindings") or []
    by_speaker = {row["speaker"]: row for row in bindings}
    local_refs: list[str] = []
    asset_ids: list[str] = []
    public_urls: list[str] = []
    audio_assets: list[dict[str, Any]] = []
    for binding in bindings:
        local = str(binding.get("voice_reference") or "")
        asset = str(binding.get("voice_reference_asset_id") or "")
        public_url = str(binding.get("voice_reference_url") or "")
        if local and local not in local_refs:
            local_refs.append(local)
        if asset and asset not in asset_ids:
            asset_ids.append(asset)
        if public_url and public_url not in public_urls:
            public_urls.append(public_url)
    for dialogue in dialogue_rows:
        binding = by_speaker[dialogue["speaker"]]
        audio_assets.append({
            "dia_id": dialogue["dia_id"],
            "speaker": dialogue["speaker"],
            "spoken_text": dialogue["spoken_text"],
            "speaker_id": binding["speaker_entity_id"],
            "audio_slot": binding["audio_slot"],
            "path": binding.get("voice_reference"),
            "sha256": binding.get("voice_reference_sha256"),
            "remote_asset_id": binding["voice_reference_asset_id"],
            "url": binding.get("voice_reference_url"),
            "voice_reference_asset_id": binding["voice_reference_asset_id"],
            "purpose": "LOCKED_NATIVE_VOICE_STYLE_REFERENCE_WITH_EXACT_TEXT",
            "audio_mode": "CANONICAL_NATIVE_VOICE_STYLE_REFERENCE_WITH_EXACT_TEXT_PROMPT",
        })
    is_h3 = str(unit.get("model") or "").lower() in {"minimax-h3", "h3"}
    return {
        "reference_audios": local_refs,
        "reference_audio_asset_ids": [] if is_h3 else asset_ids,
        "reference_audio_urls": public_urls if is_h3 else [],
        "dialogue_audio_assets": audio_assets,
        "speaker_voice_bindings": bindings,
        "speaker_voice_contract": unit.get("speaker_voice_contract"),
    }
