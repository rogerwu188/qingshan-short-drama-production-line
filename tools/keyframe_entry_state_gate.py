#!/usr/bin/env python3
"""Fail-closed admission for keyframes: a still represents entry, never completion."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


FORBIDDEN_ENTRY_WORDS = ("持续", "保持", "连续")
STATE_DELTA_DIMENSIONS = ("POSITION", "POSTURE", "CONTACT", "POSSESSION", "INTEGRITY", "MOMENTUM")


def keyframe_entry_contract_required(task: dict[str, Any], episode: str | None = None) -> bool:
    """Return whether the prospective E51 entry-only contract applies."""
    if not (task.get("video_unit_id") or task.get("semantic_video_unit")):
        return False
    if task.get("pipeline_rectification_version") == "E51_V1":
        return True
    probe = " ".join(
        str(value or "")
        for value in (
            episode,
            task.get("episode"),
            task.get("task_key"),
            task.get("video_unit_id"),
        )
    ).upper()
    match = re.search(r"(?:^|[^A-Z])E(\d+)", probe)
    return bool(match and int(match.group(1)) >= 51)


def compile_keyframe_state_contract(action: dict[str, Any], *, base: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Project an authored action into image-entry and separate comparison data.

    There is deliberately no fallback to frame_content, first_frame_motion_state,
    or completion_state: missing start_state is an authoring failure.
    """
    entry = str(action.get("start_state") or action.get("entry_state") or "").strip()
    if not entry:
        raise ValueError("KEYFRAME_ENTRY_STATE_MISSING_NO_FALLBACK")
    source = dict(base or {})
    source["entry_state"] = entry
    source.pop("completion_state", None)
    target = {
        "state_delta_dimensions": list(action.get("state_delta_dimensions") or []),
        "state_delta_evidence": action.get("state_delta_evidence") or {},
    }
    probe = {"source_shot_contract": source, "target_completion_state": target}
    report = evaluate_task(probe)
    if report["status"] != "PASS":
        raise ValueError(";".join(report["failures"]))
    return source, target


def evaluate_task(task: dict[str, Any]) -> dict[str, Any]:
    task_id = str(task.get("task_id") or task.get("task_key") or task.get("shot_id") or "UNKNOWN")
    source = task.get("source_shot_contract")
    failures: list[str] = []
    if not isinstance(source, dict):
        source = {}
        failures.append(f"KEYFRAME_SOURCE_CONTRACT_MISSING:{task_id}")
    if "completion_state" in source:
        failures.append(f"KEYFRAME_SOURCE_COMPLETION_STATE_FORBIDDEN:{task_id}")
    entry = str(source.get("entry_state") or "").strip()
    if not entry:
        failures.append(f"KEYFRAME_ENTRY_STATE_MISSING:{task_id}")
    for word in FORBIDDEN_ENTRY_WORDS:
        if word in entry:
            failures.append(f"KEYFRAME_ENTRY_STATE_EXTEND_WORD_FORBIDDEN:{task_id}:{word}")

    # Completion is retained outside source_shot_contract solely for a
    # deterministic before/after check; it is never sent to image generation.
    target = task.get("target_completion_state") or {}
    dimensions = list(target.get("state_delta_dimensions") or []) if isinstance(target, dict) else []
    evidence = target.get("state_delta_evidence") or {} if isinstance(target, dict) else {}
    if not dimensions:
        failures.append(f"KEYFRAME_TARGET_STATE_DELTA_MISSING:{task_id}")
    changed = False
    for dimension in dimensions:
        if dimension not in STATE_DELTA_DIMENSIONS:
            failures.append(f"KEYFRAME_STATE_DELTA_DIMENSION_INVALID:{task_id}:{dimension}")
            continue
        row = evidence.get(dimension) or {}
        before = str(row.get("entry") or row.get("entry_code") or "").strip()
        after = str(row.get("exit") or row.get("exit_code") or "").strip()
        if before and after and before != after:
            changed = True
    if dimensions and not changed:
        failures.append(f"KEYFRAME_ENTRY_COMPLETION_NOT_DISTINCT:{task_id}")
    return {
        "task_id": task_id,
        "status": "PASS" if not failures else "FAIL",
        "entry_state": entry,
        "checked_state_delta_dimensions": dimensions,
        "failures": failures,
    }


def evaluate_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    tasks = manifest.get("tasks") or manifest.get("items") or []
    rows = [evaluate_task(task) for task in tasks]
    failures = [failure for row in rows for failure in row["failures"]]
    return {
        "schema": "qingshan.keyframe_entry_state_gate.v1",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if rows and not failures else "FAIL",
        "policy": "KEYFRAME_SOURCE_USES_ENTRY_STATE_ONLY_NEVER_COMPLETION_STATE",
        "tasks_checked": len(rows),
        "rows": rows,
        "failures": failures or ([] if rows else ["KEYFRAME_TASKS_MISSING"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate_manifest(json.loads(args.manifest.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "tasks": report["tasks_checked"], "failures": len(report["failures"])}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
