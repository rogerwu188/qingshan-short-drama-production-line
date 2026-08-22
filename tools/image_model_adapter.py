#!/usr/bin/env python3
"""Provider-neutral keyframe contract and fail-closed image model routing."""

from __future__ import annotations

import json
import hashlib
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "configs/IMAGE_MODEL_CAPABILITY_REGISTRY_v1.json"
IDENTITY_GATE_ID = "CHARACTER-IDENTITY-ADMISSION"
FLAT_IDENTITY_MODE = "LABELED_FLAT_REFERENCE_WITH_EXACT_OUTPUT_GATE"
NATIVE_LOCK_MODE = "PROVIDER_NATIVE_IDENTITY_LOCK"
IDENTITY_PLATE_MODE = "IDENTITY_ONLY_PLATE"


def compile_labeled_flat_identity_transport(
    task_key: str, reference_bindings: list[dict[str, Any]], prompt_body: str
) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    """Compile a provider-flat sequence without pretending it is a hard lock."""
    sequence: list[dict[str, Any]] = []
    authority_map: dict[str, str] = {}
    authority_lines: list[str] = []
    digest_seed: list[str] = [task_key]
    for index, source in enumerate(reference_bindings, 1):
        row = dict(source)
        label = f"@图片{index}"
        row["asset_label"] = label
        role = str(row.get("role") or "").lower()
        entity_id = str(row.get("entity_id") or "")
        is_identity = role in {"character", "identity", "character_reference"} or entity_id.startswith("CHAR-")
        if is_identity:
            row["identity_authority"] = "PRIMARY_NATIVE_REGISTRY"
            authority_map[entity_id] = label
            authority_lines.append(
                f"{label} 是 {entity_id} 的唯一人物身份权威，只定义该人物的脸型、五官比例、年龄与稳定身份；不得与其他参考平均、混脸或重塑。"
            )
        else:
            authority_lines.append(
                f"{label} 的作用仅为 {role or 'non_identity'} / {entity_id or 'UNSCOPED'}，不得定义或改变任何人物脸。"
            )
        digest_seed.extend([label, entity_id, str(row.get("sha256") or "")])
        sequence.append(row)
    token = "IDENTITY-AUTHORITY-" + hashlib.sha256("|".join(digest_seed).encode("utf-8")).hexdigest()[:16]
    block = "\n".join([
        f"【身份权威参考映射 {token}】",
        *authority_lines,
        "注意：本接口只传输扁平参考图，上述映射是生成约束而不是身份准入证明；最终输出必须另做 exact-SHA InsightFace 身份比对。",
    ])
    contract = {
        "schema": "qingshan.identity_reference_transport.v1",
        "mode": FLAT_IDENTITY_MODE,
        "transport_guarantee": "SOFT_REFERENCE_REQUIRES_EXACT_OUTPUT_GATE",
        "output_identity_verification_method": "INSIGHTFACE_COSINE_V1",
        "exact_output_sha_required": True,
        "authority_map": authority_map,
        "authority_prompt_token": token,
    }
    return sequence, contract, f"{block}\n\n{prompt_body}"


def load_registry(path: Path = DEFAULT_REGISTRY) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_profile(task: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any] | None:
    requested = str(task.get("image_model_profile_id") or "").lower()
    model = str(task.get("model") or "").lower()
    family = str(task.get("image_model_family") or "").lower()
    for profile in registry.get("profiles") or []:
        if requested and requested == str(profile.get("profile_id") or "").lower():
            return profile
        if family and family == str(profile.get("family") or "").lower():
            return profile
        if model and model in {str(value).lower() for value in profile.get("aliases") or []}:
            return profile
    return None


def _canonical_characters(task: dict[str, Any]) -> set[str]:
    contract = task.get("prompt_contract") or {}
    values = set(map(str, task.get("canonical_characters") or []))
    values.update(map(str, task.get("visible_characters") or []))
    values.update(map(str, contract.get("visible_characters") or []))
    for key in ("blocking", "action_end_blocking"):
        for row in (task.get(key) or {}).get("characters") or []:
            if isinstance(row, dict) and row.get("character_id"):
                values.add(str(row["character_id"]))
    return {value for value in values if value}


def validate_identity_reference_transport(
    task: dict[str, Any], profile: dict[str, Any], *, prompt_text: str | None = None
) -> dict[str, Any]:
    """Reject the false equation "reference bytes sent == identity locked".

    Giggle's current image endpoint accepts a flat image array.  A visible
    character may still use it, but only under an explicit soft-transport
    contract plus exact-output identity QA.  A task may claim hard identity
    lock only when the selected provider profile actually implements it.
    """
    characters = _canonical_characters(task)
    if not characters:
        return {"status": "PASS", "gate_id": IDENTITY_GATE_ID, "mode": "NO_CANONICAL_CHARACTER"}
    failures: list[str] = []
    contract = task.get("identity_reference_transport") or {}
    if contract.get("schema") != "qingshan.identity_reference_transport.v1":
        failures.append("IDENTITY_REFERENCE_TRANSPORT_NOT_DECLARED")
    mode = str(contract.get("mode") or "")
    supports = profile.get("supports") or {}
    bindings = task.get("reference_image_sequence") or task.get("reference_bindings") or []
    character_rows = [
        row for row in bindings if isinstance(row, dict) and (
            str(row.get("role") or "").lower() in {"character", "identity", "character_reference"}
            or str(row.get("entity_id") or "").startswith("CHAR-")
        )
    ]
    bound_ids = {str(row.get("entity_id") or "") for row in character_rows}
    missing = sorted(characters - bound_ids)
    if missing:
        failures.append("IDENTITY_AUTHORITY_MISSING_FOR_CANONICAL_CHARACTER:" + ",".join(missing))

    if mode == NATIVE_LOCK_MODE:
        if not supports.get("provider_native_identity_lock") or not supports.get("semantic_role_transport"):
            failures.append("PROVIDER_NATIVE_IDENTITY_LOCK_NOT_IMPLEMENTED")
    elif mode == IDENTITY_PLATE_MODE:
        if task.get("generation_stage") != "IDENTITY_PLATE":
            failures.append("IDENTITY_PLATE_STAGE_NOT_DECLARED")
        non_identity = [row for row in bindings if row not in character_rows]
        if non_identity:
            failures.append("IDENTITY_PLATE_MIXES_SCENE_SPACE_OR_PROP_REFERENCES")
        if len(bound_ids) != 1:
            failures.append("IDENTITY_PLATE_REQUIRES_EXACTLY_ONE_CHARACTER")
    elif mode == FLAT_IDENTITY_MODE:
        if not supports.get("flat_reference_images"):
            failures.append("FLAT_REFERENCE_TRANSPORT_UNSUPPORTED")
        if contract.get("transport_guarantee") != "SOFT_REFERENCE_REQUIRES_EXACT_OUTPUT_GATE":
            failures.append("FLAT_REFERENCE_FALSELY_CLAIMS_IDENTITY_LOCK")
        if contract.get("output_identity_verification_method") != "INSIGHTFACE_COSINE_V1":
            failures.append("EXACT_OUTPUT_IDENTITY_VERIFIER_NOT_DECLARED")
        if contract.get("exact_output_sha_required") is not True:
            failures.append("EXACT_OUTPUT_SHA_IDENTITY_BINDING_NOT_REQUIRED")
        if not task.get("reference_image_sequence"):
            failures.append("LABELED_REFERENCE_SEQUENCE_REQUIRED")
        authority_map = contract.get("authority_map") or {}
        for entity_id in sorted(characters):
            row = next((item for item in character_rows if str(item.get("entity_id")) == entity_id), None)
            label = str((row or {}).get("asset_label") or "")
            if not label or authority_map.get(entity_id) != label:
                failures.append(f"IDENTITY_AUTHORITY_LABEL_MISMATCH:{entity_id}")
            if (row or {}).get("identity_authority") != "PRIMARY_NATIVE_REGISTRY":
                failures.append(f"IDENTITY_AUTHORITY_NOT_PRIMARY_NATIVE:{entity_id}")
        token = str(contract.get("authority_prompt_token") or "")
        if not token:
            failures.append("IDENTITY_AUTHORITY_PROMPT_TOKEN_MISSING")
        elif prompt_text is not None and token not in prompt_text:
            failures.append("IDENTITY_AUTHORITY_PROMPT_BLOCK_NOT_TRANSMITTED")
    elif mode:
        failures.append("IDENTITY_REFERENCE_TRANSPORT_MODE_UNKNOWN")

    if supports.get("semantic_role_transport") is False and mode not in {
        FLAT_IDENTITY_MODE, IDENTITY_PLATE_MODE,
    }:
        failures.append("IDENTITY_AUTHORITY_LOST_IN_FLAT_REFERENCE_TRANSPORT")
    return {
        "schema": "qingshan.identity_reference_transport_gate.v1",
        "gate_id": IDENTITY_GATE_ID,
        "status": "FAIL" if failures else "PASS",
        "mode": mode,
        "canonical_characters": sorted(characters),
        "failures": failures,
        "provider_semantic_role_transport": supports.get("semantic_role_transport"),
        "provider_native_identity_lock": supports.get("provider_native_identity_lock"),
    }


def validate_image_model_contract(
    task: dict[str, Any], *, episode: str | None = None,
    mode: str = "COMPATIBILITY_CHECK", registry: dict[str, Any] | None = None,
    prompt_text: str | None = None,
) -> dict[str, Any]:
    registry = registry or load_registry()
    failures: list[str] = []
    profile = resolve_profile(task, registry)
    if profile is None:
        return {"status": "FAIL", "failures": ["IMAGE_MODEL_PROFILE_UNKNOWN"], "profile": None}
    aliases = {
        "prompt": task.get("prompt") or task.get("prompt_path") or task.get("prompt_file"),
        "canonical_entity_declaration": (
            task.get("canonical_characters") or task.get("visible_characters")
            or task.get("canonical_props") or task.get("blocking")
        ),
    }
    missing = [
        field for field in registry.get("portable_required_fields") or []
        if not (aliases.get(field) if field in aliases else task.get(field))
    ]
    failures.extend(f"PORTABLE_IMAGE_FIELD_MISSING:{field}" for field in missing)
    status = str(profile.get("adapter_status") or "")
    if mode == "PAID_SUBMIT":
        if status != "DEPLOYED" or not profile.get("provider_model_id"):
            failures.append("IMAGE_MODEL_ADAPTER_NOT_DEPLOYED_FOR_PAID_SUBMIT")
        match = re.match(r"E(\d+)", str(episode or task.get("episode") or "").upper())
        policy = registry.get("active_execution_policy") or {}
        effective = re.match(r"E(\d+)", str(policy.get("effective_from_episode") or "E999999"))
        if match and effective and int(match.group(1)) >= int(effective.group(1)):
            if profile.get("profile_id") not in set(policy.get("allowed_paid_profile_ids") or []):
                failures.append("IMAGE_MODEL_NOT_AUTHORIZED_BY_ACTIVE_EPISODE_POLICY")
    limits = profile.get("provider_limits") or {}
    if status == "DEPLOYED":
        for field, key in (("resolution", "resolution_values"), ("aspect_ratio", "aspect_ratio_values")):
            allowed = limits.get(key) or []
            if allowed and task.get(field) not in allowed:
                failures.append(f"IMAGE_MODEL_{field.upper()}_OUTSIDE_PROVIDER_LIMITS")
    identity_transport = validate_identity_reference_transport(task, profile, prompt_text=prompt_text)
    failures.extend(identity_transport.get("failures") or [])
    result_status = "FAIL" if failures else "PASS"
    if not failures and status != "DEPLOYED":
        result_status = "PASS_PORTABLE_CONTRACT_PROVIDER_CONFIG_REQUIRED"
    return {
        "schema": "qingshan.image_model_adapter_preflight.v1",
        "status": result_status,
        "mode": mode,
        "profile_id": profile.get("profile_id"),
        "family": profile.get("family"),
        "adapter_status": status,
        "failures": failures,
        "identity_reference_transport": identity_transport,
    }


def require_paid_image_model_contract(
    task: dict[str, Any], episode: str | None = None, *, prompt_text: str | None = None
) -> dict[str, Any]:
    result = validate_image_model_contract(
        task, episode=episode, mode="PAID_SUBMIT", prompt_text=prompt_text
    )
    if result["status"] != "PASS":
        raise ValueError("IMAGE_MODEL_ADAPTER_GATE:" + ",".join(result["failures"]))
    return result
