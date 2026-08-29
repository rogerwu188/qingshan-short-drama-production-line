#!/usr/bin/env python3
"""Compile a writer audio contract into the one permitted postproduction profile.

The writer/director owns the creative BGM decision. This module makes that
decision executable: AgentCut builders must not choose an audio profile by
hand once ``audio_contract.bgm`` exists in the generation contract.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

try:
    from tools.audio_postproduction_contract import PROFILE_CONFIG, load_profiles
except ModuleNotFoundError:  # Direct execution from tools/.
    from audio_postproduction_contract import PROFILE_CONFIG, load_profiles  # type: ignore


PROFILE_BY_CREATIVE_MODE = {
    "FORBIDDEN": "NATIVE_MULTIMODAL_NO_EXTERNAL_BGM",
    "SELECTIVE": "NATIVE_MULTIMODAL_SELECTIVE_BGM",
    "REQUIRED": "LAYERED_POST_WITH_BGM",
}
PROFILE_CONTRACT_REF = str(PROFILE_CONFIG.relative_to(PROFILE_CONFIG.parents[1]))


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def classify_bgm_declaration(declaration: Any) -> str:
    """Return FORBIDDEN, SELECTIVE or REQUIRED; reject ambiguous prose."""
    if isinstance(declaration, dict):
        explicit_mode = str(declaration.get("mode") or declaration.get("usage_mode") or "").upper()
        if explicit_mode in {"NONE", "FORBIDDEN", "NO_BGM"} or declaration.get("used") is False:
            return "FORBIDDEN"
        if explicit_mode in {"SELECTIVE", "SELECTIVE_NARRATIVE_CUES"}:
            return "SELECTIVE"
        if explicit_mode in {"REQUIRED", "WHOLE_EPISODE", "LAYERED"}:
            return "REQUIRED"
        if declaration.get("used") is True and declaration.get("windows"):
            return "SELECTIVE"
        raise ValueError(f"ambiguous audio_contract.bgm object: {declaration!r}")

    text = str(declaration or "").strip()
    upper = text.upper()
    if not text:
        raise ValueError("audio_contract.bgm is required")
    if upper.startswith("NONE") or upper in {"FORBIDDEN", "NO_BGM"}:
        return "FORBIDDEN"
    if (
        "ONLY" in upper
        or "SELECTIVE" in upper
        or "只在" in text
        or "仅在" in text
        or "唯一一次" in text
    ):
        return "SELECTIVE"
    if upper in {"REQUIRED", "REQUIRED_WHOLE_EPISODE", "WHOLE_EPISODE_BGM", "LAYERED_POST_WITH_BGM"}:
        return "REQUIRED"
    raise ValueError(f"unrecognized audio_contract.bgm declaration: {text!r}")


def compile_audio_profile_binding(generation_contract: dict, *, contract_path: Path | None = None) -> dict:
    audio_contract = generation_contract.get("audio_contract")
    if not isinstance(audio_contract, dict):
        raise ValueError("generation contract must contain audio_contract")
    if "bgm" not in audio_contract:
        raise ValueError("generation contract audio_contract must contain bgm")

    declaration = audio_contract["bgm"]
    creative_mode = classify_bgm_declaration(declaration)
    profile_id = PROFILE_BY_CREATIVE_MODE[creative_mode]
    profiles = load_profiles().get("profiles") or {}
    profile = profiles.get(profile_id)
    if not profile:
        raise ValueError(f"resolved audio profile is not registered: {profile_id}")

    return {
        "schema": "qingshan.audio_profile_binding.v1",
        "episode": generation_contract.get("episode"),
        "generation_contract": str(contract_path.resolve()) if contract_path else None,
        "generation_contract_sha256": _file_sha256(contract_path) if contract_path else None,
        "bgm_declaration": declaration,
        "bgm_declaration_sha256": _canonical_sha256(declaration),
        "creative_bgm_mode": creative_mode,
        "resolved_audio_profile_id": profile_id,
        "profile_contract": PROFILE_CONTRACT_REF,
        "automatic": True,
    }


def apply_audio_profile_binding(project: dict, generation_contract: dict, *, contract_path: Path) -> dict:
    binding = compile_audio_profile_binding(generation_contract, contract_path=contract_path)
    profile_id = binding["resolved_audio_profile_id"]
    profile = (load_profiles().get("profiles") or {})[profile_id]
    metadata = project.setdefault("metadata", {})

    metadata["audio_profile_binding"] = binding
    metadata["audio_profile_id"] = profile_id
    metadata["audio_profile_contract"] = PROFILE_CONTRACT_REF
    metadata["source_audio_policy"] = profile["source_audio_policy"]
    metadata["audio_policy"] = (
        "PRESERVE_NATIVE_MULTIMODAL_DIALOGUE_SFX_AMBIENCE_NO_EXTERNAL_BGM"
        if profile_id == "NATIVE_MULTIMODAL_NO_EXTERNAL_BGM"
        else "PRESERVE_NATIVE_MULTIMODAL_DIALOGUE_SFX_AMBIENCE_WITH_SELECTIVE_BGM_BY_CUE"
        if profile_id == "NATIVE_MULTIMODAL_SELECTIVE_BGM"
        else "LAYERED_POSTPRODUCTION_WITH_REQUIRED_BGM"
    )
    sound_contract = metadata.setdefault("sound_design_contract", {})
    sound_contract["mode"] = profile["sound_design_mode"]
    sound_contract["external_bgm_allowed"] = profile["external_bgm_allowed"]
    return binding


def validate_audio_profile_binding(project: dict) -> list[str]:
    metadata = project.get("metadata") or {}
    binding = metadata.get("audio_profile_binding")
    if not isinstance(binding, dict):
        return ["AUDIO_PROFILE_AUTOMATIC_BINDING_REQUIRED"]
    failures: list[str] = []
    if binding.get("automatic") is not True:
        failures.append("AUDIO_PROFILE_BINDING_MUST_BE_AUTOMATIC")
    try:
        expected_mode = classify_bgm_declaration(binding.get("bgm_declaration"))
    except ValueError:
        failures.append("AUDIO_PROFILE_BINDING_BGM_DECLARATION_INVALID")
        return failures
    expected_profile = PROFILE_BY_CREATIVE_MODE[expected_mode]
    if binding.get("creative_bgm_mode") != expected_mode:
        failures.append("AUDIO_PROFILE_BINDING_CREATIVE_MODE_MISMATCH")
    if binding.get("resolved_audio_profile_id") != expected_profile:
        failures.append("AUDIO_PROFILE_BINDING_RESOLVED_PROFILE_MISMATCH")
    if metadata.get("audio_profile_id") != expected_profile:
        failures.append("AUDIO_PROFILE_ID_GENERATION_CONTRACT_MISMATCH")
    if binding.get("bgm_declaration_sha256") != _canonical_sha256(binding.get("bgm_declaration")):
        failures.append("AUDIO_PROFILE_BINDING_BGM_DECLARATION_SHA_MISMATCH")

    contract_value = str(binding.get("generation_contract") or "")
    contract_path = Path(contract_value) if contract_value else None
    if not contract_path or not contract_path.is_file():
        failures.append("AUDIO_PROFILE_BINDING_GENERATION_CONTRACT_MISSING")
        return failures
    if binding.get("generation_contract_sha256") != _file_sha256(contract_path):
        failures.append("AUDIO_PROFILE_BINDING_GENERATION_CONTRACT_SHA_MISMATCH")
        return failures
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        recomputed = compile_audio_profile_binding(contract, contract_path=contract_path)
    except (OSError, ValueError, json.JSONDecodeError):
        failures.append("AUDIO_PROFILE_BINDING_GENERATION_CONTRACT_INVALID")
        return failures
    for field in ("episode", "bgm_declaration_sha256", "creative_bgm_mode", "resolved_audio_profile_id"):
        if binding.get(field) != recomputed.get(field):
            failures.append(f"AUDIO_PROFILE_BINDING_RECOMPUTE_MISMATCH:{field}")
    if metadata.get("episode") and metadata.get("episode") != recomputed.get("episode"):
        failures.append("AUDIO_PROFILE_BINDING_EPISODE_MISMATCH")
    return failures
