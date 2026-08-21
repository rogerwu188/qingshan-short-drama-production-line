#!/usr/bin/env python3
"""Provider-neutral video contract and fail-closed model capability routing."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "configs/VIDEO_MODEL_CAPABILITY_REGISTRY_v1.json"


def load_registry(path: Path = DEFAULT_REGISTRY) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_profile(task: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any] | None:
    requested = str(task.get("model_profile_id") or "").lower()
    model = str(task.get("model") or "").lower()
    family = str(task.get("model_family") or "").lower()
    for profile in registry.get("profiles") or []:
        if requested and requested == str(profile.get("profile_id") or "").lower():
            return profile
        if family and family == str(profile.get("family") or "").lower():
            return profile
        if model and model in {str(value).lower() for value in profile.get("aliases") or []}:
            return profile
    return None


def validate_model_contract(
    task: dict[str, Any],
    *,
    episode: str | None = None,
    mode: str = "COMPATIBILITY_CHECK",
    registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    registry = registry or load_registry()
    failures: list[str] = []
    profile = resolve_profile(task, registry)
    if profile is None:
        failures.append("VIDEO_MODEL_PROFILE_UNKNOWN")
        return {"status": "FAIL", "failures": failures, "profile": None}
    aliases = {
        "prompt": task.get("prompt") or task.get("prompt_path") or task.get("prompt_file"),
        "duration_seconds": task.get("duration_seconds") or task.get("duration"),
    }
    missing = [
        field for field in registry.get("portable_required_fields") or []
        if not (aliases.get(field) if field in aliases else task.get(field))
    ]
    if missing:
        failures.extend(f"PORTABLE_VIDEO_FIELD_MISSING:{field}" for field in missing)
    status = str(profile.get("adapter_status") or "")
    if mode == "PAID_SUBMIT":
        if status != "DEPLOYED" or not profile.get("provider_model_id"):
            failures.append("MODEL_ADAPTER_NOT_DEPLOYED_FOR_PAID_SUBMIT")
        match = re.match(r"E(\d+)", str(episode or task.get("episode") or "").upper())
        policy = registry.get("active_execution_policy") or {}
        effective = re.match(r"E(\d+)", str(policy.get("effective_from_episode") or "E999999"))
        if match and effective and int(match.group(1)) >= int(effective.group(1)):
            if profile.get("profile_id") not in set(policy.get("allowed_paid_profile_ids") or []):
                failures.append("MODEL_NOT_AUTHORIZED_BY_ACTIVE_EPISODE_POLICY")
    limits = profile.get("provider_limits") or {}
    if status == "DEPLOYED":
        duration = task.get("duration_seconds") or task.get("duration")
        if isinstance(duration, (int, float)):
            if duration < limits.get("duration_seconds_min", duration) or duration > limits.get("duration_seconds_max", duration):
                failures.append("MODEL_DURATION_OUTSIDE_PROVIDER_LIMITS")
        for field, key in (("resolution", "resolution_values"), ("aspect_ratio", "aspect_ratio_values")):
            allowed = limits.get(key) or []
            if allowed and task.get(field) not in allowed:
                failures.append(f"MODEL_{field.upper()}_OUTSIDE_PROVIDER_LIMITS")
    result_status = "FAIL" if failures else "PASS"
    if not failures and status != "DEPLOYED":
        result_status = "PASS_PORTABLE_CONTRACT_PROVIDER_CONFIG_REQUIRED"
    return {
        "schema": "qingshan.video_model_adapter_preflight.v1",
        "status": result_status,
        "mode": mode,
        "profile_id": profile.get("profile_id"),
        "family": profile.get("family"),
        "provider": profile.get("provider"),
        "adapter_status": status,
        "failures": failures,
    }


def require_paid_model_contract(task: dict[str, Any], episode: str | None = None) -> dict[str, Any]:
    result = validate_model_contract(task, episode=episode, mode="PAID_SUBMIT")
    if result["status"] != "PASS":
        raise ValueError("VIDEO_MODEL_ADAPTER_GATE:" + ",".join(result["failures"]))
    return result
