#!/usr/bin/env python3
"""Repository-owned fail-closed gate for the paid video entry point.

This is intentionally provider-neutral. Model selection is explicit per
episode/task and is validated by the versioned capability registry; no hidden
machine-local BacklotOS installation is required by a clean clone.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

try:
    from tools.action_video_prompt_compiler import validate_action_contract
    from tools.performance_tempo_gate import evaluate_batch as evaluate_performance_tempo
    from tools.video_model_adapter import validate_model_contract
except ModuleNotFoundError:
    from action_video_prompt_compiler import validate_action_contract
    from performance_tempo_gate import evaluate_batch as evaluate_performance_tempo
    from video_model_adapter import validate_model_contract


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def evaluate_manifest(
    manifest: dict[str, Any],
    *,
    root: str | Path,
    manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    tasks = list(manifest.get("tasks") or [])
    failures: list[dict[str, Any]] = []
    if not tasks:
        failures.append({"code": "CURRENT_MANIFEST_TASKS_MISSING"})
    for task in tasks:
        key = str(task.get("task_key") or "UNKNOWN")
        prompt_value = task.get("prompt_file")
        if not prompt_value:
            failures.append({"code": "CURRENT_PROMPT_FILE_MISSING", "task_key": key})
        else:
            prompt = _resolve(root_path, prompt_value)
            if not prompt.is_file():
                failures.append({"code": "CURRENT_PROMPT_FILE_MISSING", "task_key": key, "path": str(prompt_value)})
            elif _sha256(prompt) != task.get("prompt_sha256"):
                failures.append({"code": "CURRENT_PROMPT_SHA_MISMATCH", "task_key": key})
        model = validate_model_contract(task, episode=manifest.get("episode"), mode="PAID_SUBMIT")
        failures.extend({"code": code, "task_key": key} for code in model.get("failures") or [])
        if task.get("action_unit") is True or task.get("combat_or_chase") is True:
            failures.extend({"code": code, "task_key": key} for code in validate_action_contract(task))
        roles = set(map(str, task.get("reference_roles") or []))
        if "EXACT_FIRST_FRAME" in roles:
            failures.append({
                "code": "EXACT_FIRST_FRAME_NOT_SUPPORTED_BY_STANDARD_MULTI_REFERENCE_ENTRYPOINT",
                "task_key": key,
            })
    tempo = evaluate_performance_tempo(tasks)
    failures.extend(tempo.get("failures") or [])
    manifest_sha = None
    if manifest_path is not None:
        path = _resolve(root_path, manifest_path)
        if path.is_file():
            manifest_sha = _sha256(path)
        else:
            failures.append({"code": "CURRENT_MANIFEST_FILE_MISSING", "path": str(manifest_path)})
    gate_path = Path(__file__).resolve()
    registry = root_path / "configs" / "VIDEO_MODEL_CAPABILITY_REGISTRY_v1.json"
    return {
        "schema": "qingshan.production_video_submission_gate.v1",
        "status": "PASS" if not failures else "FAIL",
        "manifest_sha256": manifest_sha,
        "task_keys": [str(task.get("task_key") or "UNKNOWN") for task in tasks],
        "performance_tempo": tempo,
        "failures": failures,
        "runtime_binding": {
            "gate_path": str(gate_path),
            "gate_sha256": _sha256(gate_path),
            "model_registry_path": str(registry),
            "model_registry_sha256": _sha256(registry) if registry.is_file() else None,
        },
        "policy": "Current manifest and prompt hashes are checked at the paid boundary. SD2 and H3 are selected explicitly through the repository model registry. Exact-I2V is excluded from the standard multi-reference entry point.",
    }
