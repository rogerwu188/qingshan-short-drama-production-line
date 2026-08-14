#!/usr/bin/env python3
"""Build E32 failed-only retries that send verified public image URLs."""

from __future__ import annotations

import hashlib
import json
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
SOURCE = BASE / "E32_VIDEO_MINIMAL_REFERENCE_REPAIR_V7.json"
SOURCE_RECEIPT = ROOT / "workflow/tasks/E32_VIDEO_MINIMAL_REFERENCE_REPAIR_V7_SUPERVISOR.json"
CONFIG = BASE / "E32_VIDEO_DIRECT_URL_REPAIR_V8.json"
PRECHECK = BASE / "qa/E32_VIDEO_DIRECT_URL_REPAIR_V8_PRECHECK.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def file_sha(path: str) -> str:
    source = Path(path)
    if not source.is_absolute():
        source = ROOT / source
    return hashlib.sha256(source.read_bytes()).hexdigest()


def main() -> int:
    config = load(SOURCE)
    source_receipt = load(SOURCE_RECEIPT)
    registry = source_receipt.get("local_reference_asset_registry") or {}
    tasks = []
    for source in config["tasks"]:
        task = json.loads(json.dumps(source, ensure_ascii=False))
        urls = []
        for path in task.get("reference_images") or []:
            entry = registry.get(file_sha(path)) or {}
            url = entry.get("url")
            if not url:
                raise SystemExit(f"missing registered public URL for {path}")
            urls.append(url)
        task["reference_image_transport"] = "direct_url"
        task["reference_image_urls"] = urls
        task["resolved_reference_image_asset_ids"] = []
        task.pop("reference_image_asset_ids", None)
        task["generation_transport_revision"] = "DIRECT_IMAGE_URL_V1"
        task["task_key"] = f"{task['unit_id']}-PERFORMANCE-V8-DIRECT-URL"
        task["batch_id"] = "E32-PERFORMANCE-V8-DIRECT-URL"
        task["status"] = "READY_TO_SUBMIT"
        task["generation_fingerprint"] = generation_fingerprint(task)
        tasks.append(task)
    config.update({
        "status": "READY_CHANGED_TRANSPORT_DIRECT_URL_REPAIR",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "targeted_unit_replacement": True,
        "streaming_submission_policy": "SUBMIT_EACH_UNIT_IMMEDIATELY_WHEN_ITS_OWN_DEPENDENCIES_PASS",
        "max_retries": 0,
        "tasks": tasks,
    })
    write(CONFIG, config)

    prompts = {task["task_key"]: (ROOT / task["prompt_file"]).read_text(encoding="utf-8") for task in tasks}
    checks = {
        "corrected_pipeline_quality": validate_corrected_pipeline_quality(config),
        "complete_video_prompt_manifest": validate_complete_video_prompt_manifest(config),
        "dialogue_manifest_coverage": validate_dialogue_manifest_coverage(config),
        "prompt_professionalism": evaluate_prompt_professionalism(config),
        "space_camera_constraint": evaluate_space_camera(tasks, prompts),
        "multimodal_character_binding": evaluate_bindings(config),
        "scene_authority": evaluate_scene_authority(config["scene_contract_ref"], config),
        "entity_reference_sequence": {"status": "PASS", "results": []},
        "duration_policy": {"status": "PASS", "results": []},
        "generation_deduplication": {"status": "PASS", "results": []},
        "direct_url_coverage": {"status": "PASS", "results": []},
        "current_workflow_credit_gate": evaluate_episode_credit_gate("E32", limit=6000),
    }
    for task in tasks:
        entity_failures = validate_entity_reference_task(task)
        duration_failures = validate_duration_task(task)
        existing = find_existing_paid_candidate("E32", task)
        coverage_ok = len(task["reference_image_urls"]) == len(task.get("reference_images") or [])
        checks["entity_reference_sequence"]["results"].append({"task_key": task["task_key"], "failures": entity_failures})
        checks["duration_policy"]["results"].append({"task_key": task["task_key"], "failures": duration_failures})
        checks["generation_deduplication"]["results"].append({"task_key": task["task_key"], "existing": existing})
        checks["direct_url_coverage"]["results"].append({"task_key": task["task_key"], "status": "PASS" if coverage_ok else "FAIL"})
        if entity_failures:
            checks["entity_reference_sequence"]["status"] = "FAIL"
        if duration_failures:
            checks["duration_policy"]["status"] = "FAIL"
        if existing is not None:
            checks["generation_deduplication"]["status"] = "FAIL"
        if not coverage_ok:
            checks["direct_url_coverage"]["status"] = "FAIL"
    writer_ok, writer_failures = validate_writer_agent_provenance(config)
    checks["writer_provenance"] = {"status": "PASS" if writer_ok else "FAIL", "failures": writer_failures}
    report = {
        "schema": "qingshan.e32_direct_url_repair_precheck.v1",
        "episode": "E32",
        "status": "PASS" if all(row.get("status") == "PASS" for row in checks.values()) else "FAIL",
        "checks": checks,
        "config": str(CONFIG.relative_to(ROOT)),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    write(PRECHECK, report)
    print(json.dumps({"status": report["status"], "config": report["config"], "precheck": str(PRECHECK.relative_to(ROOT))}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
