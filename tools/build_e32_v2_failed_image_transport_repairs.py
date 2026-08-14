#!/usr/bin/env python3
"""Build changed-input retries for E32 units whose remote image upload failed."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from episode_parallel_batch_supervisor import (
    validate_complete_video_prompt_manifest,
    validate_corrected_pipeline_quality,
    validate_dialogue_manifest_coverage,
    validate_duration_task,
    validate_entity_reference_task,
    validate_writer_agent_provenance,
)
from episode_video_generation_guard import evaluate_episode_credit_gate, find_existing_paid_candidate, generation_fingerprint
from multimodal_character_binding_guard import evaluate_batch as evaluate_bindings
from scene_authority_lock import evaluate_batch as evaluate_scene_authority
from shot_prompt_professionalism_gate import evaluate_batch as evaluate_prompt_professionalism
from shot_space_camera_constraint_gate import evaluate_batch as evaluate_space_camera


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e32_claude_writer_v2_20260723/video_performance_v2"
SOURCE_CONFIG = BASE / "E32_VIDEO_REMAINING_13_NATIVE_VOICE_V3.json"
SOURCE_RECEIPT = ROOT / "workflow/tasks/E32_VIDEO_REMAINING_13_NATIVE_VOICE_V3_SUPERVISOR_R2.json"
CONFIG = BASE / "E32_VIDEO_FAILED_IMAGE_TRANSPORT_REPAIR_V5.json"
PRECHECK = BASE / "qa/E32_VIDEO_FAILED_IMAGE_TRANSPORT_REPAIR_V5_PRECHECK.json"
REPAIR_DIR = ROOT / "working_assets/e32_remake_v2_stills_20260723/video_transport_reencode_v5"
FAILED_UNITS = ("E32-CW-U09", "E32-CW-U15", "E32-CW-U16", "E32-CW-U17")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def reencode(source: Path, unit_id: str) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        bundled = list((ROOT / ".agentcut_env").glob("lib/python*/site-packages/agentcut/vendor/darwin-arm64/ffmpeg"))
        ffmpeg = str(bundled[0]) if bundled else None
    if not ffmpeg:
        raise SystemExit("ffmpeg unavailable")
    REPAIR_DIR.mkdir(parents=True, exist_ok=True)
    target = REPAIR_DIR / f"{unit_id}-A1-LOSSLESS-TRANSPORT-R1.png"
    subprocess.run(
        [ffmpeg, "-y", "-i", str(source), "-frames:v", "1", "-compression_level", "4", str(target)],
        check=True,
        capture_output=True,
    )
    if sha(source) == sha(target):
        raise SystemExit(f"{unit_id}: re-encoding did not change input bytes")
    return target


def main() -> int:
    source = load(SOURCE_CONFIG)
    receipt = load(SOURCE_RECEIPT)
    remote_failures = {
        row["unit_id"]: row for row in receipt["tasks"] if row.get("state") == "remote_failed_terminal"
    }
    if set(remote_failures) != set(FAILED_UNITS):
        raise SystemExit(f"remote failure set changed: {sorted(remote_failures)}")
    for row in remote_failures.values():
        attempts = row.get("credit_attempts") or []
        if not attempts or any(attempt.get("actual_charged_credits") != 0 for attempt in attempts):
            raise SystemExit(f"{row['unit_id']}: failure is not explicitly zero-credit")

    tasks = []
    prompt_texts = {}
    for original in source["tasks"]:
        if original["unit_id"] not in FAILED_UNITS:
            continue
        task = json.loads(json.dumps(original, ensure_ascii=False))
        temporal = next(
            row for row in task["reference_image_sequence"]
            if "IDENTITY" not in str(row.get("role") or "").upper()
        )
        old = ROOT / temporal["path"]
        repaired = reencode(old, task["unit_id"])
        task["reference_images"] = [rel(repaired) if value == temporal["path"] else value for value in task["reference_images"]]
        temporal.update({"path": rel(repaired), "sha256": sha(repaired), "transport_reencode_of": rel(old)})
        task["task_key"] = f"{task['unit_id']}-PERFORMANCE-V5-IMAGE-TRANSPORT"
        task["batch_id"] = "E32-PERFORMANCE-V5-FAILED-IMAGE-TRANSPORT"
        task["generation_fingerprint"] = generation_fingerprint(task)
        tasks.append(task)
        prompt_texts[task["task_key"]] = (ROOT / task["prompt_file"]).read_text(encoding="utf-8")

    config = json.loads(json.dumps(source, ensure_ascii=False))
    config.update({
        "status": "READY_FAILED_IMAGE_TRANSPORT_CHANGED_INPUT",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "targeted_unit_replacement": True,
        "concurrency": len(tasks),
        "tasks": tasks,
    })
    write(CONFIG, config)
    checks = {
        "corrected_pipeline_quality": validate_corrected_pipeline_quality(config),
        "complete_video_prompt_manifest": validate_complete_video_prompt_manifest(config),
        "dialogue_manifest_coverage": validate_dialogue_manifest_coverage(config),
        "prompt_professionalism": evaluate_prompt_professionalism(config),
        "space_camera_constraint": evaluate_space_camera(tasks, prompt_texts),
        "multimodal_character_binding": evaluate_bindings(config),
        "scene_authority": evaluate_scene_authority(config["scene_contract_ref"], config),
        "entity_reference_sequence": {"status": "PASS", "results": []},
        "duration_policy": {"status": "PASS", "results": []},
        "generation_deduplication": {"status": "PASS", "results": []},
        "current_workflow_credit_gate": evaluate_episode_credit_gate("E32", limit=6000),
    }
    for task in tasks:
        entity_failures = validate_entity_reference_task(task)
        checks["entity_reference_sequence"]["results"].append({"task_key": task["task_key"], "failures": entity_failures})
        if entity_failures:
            checks["entity_reference_sequence"]["status"] = "FAIL"
        duration_failures = validate_duration_task(task)
        checks["duration_policy"]["results"].append({"task_key": task["task_key"], "failures": duration_failures})
        if duration_failures:
            checks["duration_policy"]["status"] = "FAIL"
        existing = find_existing_paid_candidate("E32", task)
        checks["generation_deduplication"]["results"].append({"task_key": task["task_key"], "existing": existing})
        if existing is not None:
            checks["generation_deduplication"]["status"] = "FAIL"
    writer_ok, writer_failures = validate_writer_agent_provenance(config)
    checks["writer_provenance"] = {"status": "PASS" if writer_ok else "FAIL", "failures": writer_failures}
    report = {
        "schema": "qingshan.e32_failed_image_transport_precheck.v1",
        "episode": "E32",
        "status": "PASS" if all(row.get("status") == "PASS" for row in checks.values()) else "FAIL",
        "source_remote_failures": [
            {"unit_id": unit_id, "task_id": remote_failures[unit_id]["task_id"], "actual_charged_credits": 0}
            for unit_id in FAILED_UNITS
        ],
        "checks": checks,
        "config": rel(CONFIG),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    write(PRECHECK, report)
    print(json.dumps({"status": report["status"], "config": rel(CONFIG), "precheck": rel(PRECHECK), "units": list(FAILED_UNITS)}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
