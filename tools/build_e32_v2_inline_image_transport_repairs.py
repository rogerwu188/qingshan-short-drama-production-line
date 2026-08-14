#!/usr/bin/env python3
"""Build changed-input inline-image retries for E32 U09/U10/U15/U16/U17."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageOps

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
V5_CONFIG = BASE / "E32_VIDEO_FAILED_IMAGE_TRANSPORT_REPAIR_V5.json"
V5_RECEIPT = ROOT / "workflow/tasks/E32_VIDEO_FAILED_IMAGE_TRANSPORT_REPAIR_V5_SUPERVISOR.json"
U10_CONFIG = BASE / "E32_VIDEO_U10_AUDIO_FLOOR_REPAIR_V4.json"
U10_RECEIPT = ROOT / "workflow/tasks/E32_VIDEO_U10_AUDIO_FLOOR_REPAIR_V4_SUPERVISOR.json"
CONFIG = BASE / "E32_VIDEO_INLINE_IMAGE_TRANSPORT_REPAIR_V6.json"
PRECHECK = BASE / "qa/E32_VIDEO_INLINE_IMAGE_TRANSPORT_REPAIR_V6_PRECHECK.json"
IMAGE_DIR = ROOT / "working_assets/e32_remake_v2_stills_20260723/inline_jpeg_transport_v6"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def verify_zero_credit_failure(receipt_path: Path) -> None:
    for task in load(receipt_path).get("tasks", []):
        attempts = task.get("credit_attempts") or []
        if task.get("state") != "remote_failed_terminal" or not attempts:
            raise SystemExit(f"{task.get('unit_id')}: source attempt is not a settled remote failure")
        if any(row.get("actual_charged_credits") != 0 for row in attempts):
            raise SystemExit(f"{task.get('unit_id')}: source failure is not explicit zero-credit")


def jpeg_copy(source: Path, unit_id: str, index: int) -> Path:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    target = IMAGE_DIR / f"{unit_id}-R{index:02d}-INLINE-Q92.jpg"
    image = ImageOps.exif_transpose(Image.open(source)).convert("RGB")
    image.thumbnail((1440, 2560), Image.Resampling.LANCZOS)
    image.save(target, "JPEG", quality=92, optimize=True, progressive=False, subsampling=0)
    if sha(source) == sha(target):
        raise SystemExit(f"{unit_id}: inline transport conversion did not change bytes")
    return target


def convert_task(task: dict) -> dict:
    task = json.loads(json.dumps(task, ensure_ascii=False))
    replacements = {}
    converted = []
    for index, value in enumerate(task.get("reference_images", []), start=1):
        old = ROOT / value
        new = jpeg_copy(old, task["unit_id"], index)
        replacements[value] = rel(new)
        converted.append(rel(new))
    task["reference_images"] = converted
    for row in task.get("reference_image_sequence", []):
        old = row.get("path")
        if old in replacements:
            new = ROOT / replacements[old]
            row.update({
                "path": rel(new),
                "sha256": sha(new),
                "transport_derivative_of": old,
                "transport_derivative_source_sha256": sha(ROOT / old),
                "transport_transform": "JPEG_Q92_S444_MAX_1440X2560",
                "transport": "INLINE_BASE64",
            })
    # Identity bindings remain pointed at the canonical registry sources. The
    # submitted JPEGs are byte-transport derivatives, not new identity refs.
    task["reference_image_transport"] = "inline_base64"
    task.pop("reference_image_asset_ids", None)
    task.pop("resolved_reference_image_asset_ids", None)
    task["task_key"] = f"{task['unit_id']}-PERFORMANCE-V6-INLINE-IMAGE-TRANSPORT"
    task["batch_id"] = "E32-PERFORMANCE-V6-INLINE-IMAGE-TRANSPORT"
    task["status"] = "READY_TO_SUBMIT"
    task["generation_fingerprint"] = generation_fingerprint(task)
    return task


def main() -> int:
    verify_zero_credit_failure(V5_RECEIPT)
    verify_zero_credit_failure(U10_RECEIPT)
    v5 = load(V5_CONFIG)
    u10 = load(U10_CONFIG)
    source_tasks = [*v5["tasks"], *u10["tasks"]]
    tasks = [convert_task(task) for task in source_tasks]
    config = json.loads(json.dumps(v5, ensure_ascii=False))
    config.update({
        "status": "READY_INLINE_IMAGE_TRANSPORT_CHANGED_INPUT",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "targeted_unit_replacement": True,
        "streaming_submission_policy": "SUBMIT_EACH_UNIT_IMMEDIATELY_WHEN_ITS_OWN_DEPENDENCIES_PASS",
        "concurrency": len(tasks),
        "tasks": tasks,
    })
    write(CONFIG, config)
    prompt_texts = {
        task["task_key"]: (ROOT / task["prompt_file"]).read_text(encoding="utf-8")
        for task in tasks
    }
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
        duration_failures = validate_duration_task(task)
        existing = find_existing_paid_candidate("E32", task)
        checks["entity_reference_sequence"]["results"].append({"task_key": task["task_key"], "failures": entity_failures})
        checks["duration_policy"]["results"].append({"task_key": task["task_key"], "failures": duration_failures})
        checks["generation_deduplication"]["results"].append({"task_key": task["task_key"], "existing": existing})
        if entity_failures:
            checks["entity_reference_sequence"]["status"] = "FAIL"
        if duration_failures:
            checks["duration_policy"]["status"] = "FAIL"
        if existing is not None:
            checks["generation_deduplication"]["status"] = "FAIL"
    writer_ok, writer_failures = validate_writer_agent_provenance(config)
    checks["writer_provenance"] = {"status": "PASS" if writer_ok else "FAIL", "failures": writer_failures}
    report = {
        "schema": "qingshan.e32_inline_image_transport_precheck.v1",
        "episode": "E32",
        "status": "PASS" if all(row.get("status") == "PASS" for row in checks.values()) else "FAIL",
        "source_failed_attempt_credits": 0,
        "checks": checks,
        "config": rel(CONFIG),
        "units": [task["unit_id"] for task in tasks],
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    write(PRECHECK, report)
    print(json.dumps({"status": report["status"], "config": rel(CONFIG), "precheck": rel(PRECHECK), "units": report["units"]}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
