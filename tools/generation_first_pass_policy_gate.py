#!/usr/bin/env python3
"""Enforce learned prompt failures and tiered remake policy before paid generation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CORE_THRESHOLD = 80.0
NON_CORE_THRESHOLD = 60.0


def _resolve(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _load_bound(config: dict[str, Any], ref_key: str, sha_key: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    failures: list[dict[str, Any]] = []
    ref = config.get(ref_key)
    expected_sha = config.get(sha_key)
    if not ref or not expected_sha:
        return None, [{"check": ref_key, "error": "path_or_sha256_missing"}]
    path = _resolve(ref)
    if not path.is_file():
        return None, [{"check": ref_key, "error": "file_missing", "path": str(path)}]
    actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual_sha != expected_sha:
        failures.append({"check": sha_key, "expected": expected_sha, "actual": actual_sha})
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        failures.append({"check": ref_key, "error": str(exc)})
        return None, failures
    return payload, failures


def evaluate(config: dict[str, Any]) -> dict[str, Any]:
    policy, failures = _load_bound(
        config,
        "generation_first_pass_policy_ref",
        "generation_first_pass_policy_sha256",
    )
    memory, memory_failures = _load_bound(
        config,
        "generation_prompt_failure_memory_ref",
        "generation_prompt_failure_memory_sha256",
    )
    failures.extend(memory_failures)
    if policy and policy.get("status") != "APPROVED_STANDING_POLICY":
        failures.append({"check": "policy_status", "actual": policy.get("status")})
    if memory and memory.get("status") != "ACTIVE_PRE_SUBMIT_INPUT":
        failures.append({"check": "failure_memory_status", "actual": memory.get("status")})

    known_ids = {str(row.get("id")) for row in (memory or {}).get("rules", []) if row.get("id")}
    results = []
    for task in config.get("tasks", []):
        if task.get("tool_type") not in {"image_generation", "video_generation"}:
            continue
        task_failures: list[dict[str, Any]] = []
        tier = str(task.get("visual_tier") or "").upper()
        expected_threshold = CORE_THRESHOLD if tier == "CORE" else NON_CORE_THRESHOLD if tier == "NON_CORE" else None
        if expected_threshold is None:
            task_failures.append({"check": "visual_tier", "expected": ["CORE", "NON_CORE"], "actual": tier or "MISSING"})
        elif float(task.get("minimum_score_100", -1)) != expected_threshold:
            task_failures.append({
                "check": "minimum_score_100",
                "expected": expected_threshold,
                "actual": task.get("minimum_score_100"),
            })

        applied = {str(value) for value in task.get("prompt_failure_modes_applied", [])}
        not_applicable = {str(value) for value in task.get("prompt_failure_modes_not_applicable", [])}
        overlap = sorted(applied & not_applicable)
        considered = applied | not_applicable
        if overlap:
            task_failures.append({"check": "failure_mode_disposition_overlap", "ids": overlap})
        if considered != known_ids:
            task_failures.append({
                "check": "failure_mode_disposition_complete",
                "missing": sorted(known_ids - considered),
                "unknown": sorted(considered - known_ids),
            })
        if not applied:
            task_failures.append({"check": "prompt_failure_modes_applied", "error": "at_least_one_known_rule_must_be_compiled"})
        results.append({
            "task_key": task.get("task_key"),
            "visual_tier": tier or None,
            "minimum_score_100": expected_threshold,
            "applied_failure_modes": sorted(applied),
            "not_applicable_failure_modes": sorted(not_applicable),
            "status": "PASS" if not task_failures else "BLOCK_SUBMIT",
            "failures": task_failures,
        })
        failures.extend({"task_key": task.get("task_key"), **row} for row in task_failures)

    if not results:
        return {"schema": "qingshan.generation_first_pass_policy_gate.v1", "status": "NOT_APPLICABLE", "failures": failures, "results": []}
    return {
        "schema": "qingshan.generation_first_pass_policy_gate.v1",
        "status": "PASS" if not failures else "FAIL",
        "policy": {"core_min_score_100": CORE_THRESHOLD, "non_core_min_score_100": NON_CORE_THRESHOLD},
        "known_failure_mode_ids": sorted(known_ids),
        "failures": failures,
        "results": results,
    }

