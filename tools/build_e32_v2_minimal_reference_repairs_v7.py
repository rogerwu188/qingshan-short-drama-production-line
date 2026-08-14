#!/usr/bin/env python3
"""Build E32 changed-input repairs with only unit-required clean references."""

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
from multimodal_character_binding_guard import binding_digest, evaluate_batch as evaluate_bindings
from scene_authority_lock import evaluate_batch as evaluate_scene_authority
from shot_prompt_professionalism_gate import evaluate_batch as evaluate_prompt_professionalism
from shot_space_camera_constraint_gate import evaluate_batch as evaluate_space_camera


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e32_claude_writer_v2_20260723/video_performance_v2"
MAIN = BASE / "E32_VIDEO_REMAINING_13_NATIVE_VOICE_V3.json"
V5 = BASE / "E32_VIDEO_FAILED_IMAGE_TRANSPORT_REPAIR_V5.json"
U10 = BASE / "E32_VIDEO_U10_AUDIO_FLOOR_REPAIR_V4.json"
CONFIG = BASE / "E32_VIDEO_MINIMAL_REFERENCE_REPAIR_V7.json"
PRECHECK = BASE / "qa/E32_VIDEO_MINIMAL_REFERENCE_REPAIR_V7_PRECHECK.json"
FRAME_DIR = ROOT / "working_assets/e32_remake_v2_stills_20260723/video_continuity_frames_v7"
U08_VIDEO = BASE / "outputs/E32_E32-CW-U08-PERFORMANCE-V3_85b01d6a-ce87-47ae-b74c-7f1bd9e41c7c.mp4"

REFS = {
    "chenji": "working_assets/e32_reference_single_subject_20260723/chenji_front_single.jpg",
    "jiaotu": "working_assets/e32_reference_single_subject_20260723/jiaotu_front_single.jpg",
    "yunyang": "working_assets/e32_reference_single_subject_20260723/yunyang_front_single.jpg",
    "wuyun": "ref_images/cat_wuyun_reference.jpg",
    "qisan": "working_assets/e32_remake_v2_stills_20260723/candidates/E32-CW-U05-A1-STILL-V2_93e23a3a-87f4-43e5-8f19-c87ae983ee13.png",
    "killer": "working_assets/e28_u09_fixed_input_reference_20260722/E28-CW-U09-INSTRUCTOR-MASKED-SINGLE-REF.png",
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(value: str | Path) -> str:
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def extract_u08_frame(seconds: float, label: str) -> str:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        candidates = list((ROOT / ".agentcut_env").glob("lib/python*/site-packages/agentcut/vendor/darwin-arm64/ffmpeg"))
        ffmpeg = str(candidates[0]) if candidates else None
    if not ffmpeg:
        raise SystemExit("ffmpeg unavailable")
    FRAME_DIR.mkdir(parents=True, exist_ok=True)
    target = FRAME_DIR / f"E32-U08-{label}-{seconds:.1f}s.jpg"
    subprocess.run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-ss", str(seconds),
        "-i", str(U08_VIDEO), "-frames:v", "1", "-q:v", "2", str(target),
    ], check=True)
    return rel(target)


def sequence_row(label: str, role: str, path: str, *, identity: bool = False) -> dict:
    row = {"asset_label": label, "role": role, "path": path, "sha256": sha(path)}
    if identity:
        row["identity_reference"] = True
    return row


def rebuild_task(task: dict, temporal: list[str], identities: list[str]) -> dict:
    task = json.loads(json.dumps(task, ensure_ascii=False))
    unit = task["unit_id"]
    sequence = []
    references = []
    slot_by_entity = {}
    for path in temporal:
        label = f"@图片{len(sequence) + 1}"
        identity_entity = next((entity for entity in identities if REFS[entity] == path), None)
        sequence.append(sequence_row(label, "PERFORMANCE_START" if len(sequence) == 0 else "PERFORMANCE_CONTINUATION", path, identity=bool(identity_entity)))
        references.append(path)
        if identity_entity:
            slot_by_entity[identity_entity] = label
    for entity in identities:
        if entity in slot_by_entity:
            continue
        path = REFS[entity]
        label = f"@图片{len(sequence) + 1}"
        sequence.append(sequence_row(label, f"IDENTITY_REFERENCE_{entity.upper()}", path, identity=True))
        references.append(path)
        slot_by_entity[entity] = label
    task["reference_images"] = references
    task["reference_image_sequence"] = sequence
    task["planned_reference_image_count"] = len(temporal)
    task["state_reference_minimum"] = len(temporal)
    task.pop("reference_image_transport", None)
    task.pop("reference_image_asset_ids", None)
    task.pop("resolved_reference_image_asset_ids", None)
    for binding in task.get("multimodal_entity_bindings", []):
        entity = binding["entity_id"]
        if entity in slot_by_entity:
            binding["visual_reference"] = REFS[entity]
            binding["visual_reference_sha256"] = sha(REFS[entity])
            binding["identity_image_slot"] = slot_by_entity[entity]
    task["multimodal_binding_sha256"] = binding_digest(task.get("multimodal_entity_bindings") or [])
    task["task_key"] = f"{unit}-PERFORMANCE-V7-MINIMAL-REFERENCE"
    task["batch_id"] = "E32-PERFORMANCE-V7-MINIMAL-REFERENCE"
    task["status"] = "READY_TO_SUBMIT"
    task["generation_fingerprint"] = generation_fingerprint(task)
    return task


def main() -> int:
    main = load(MAIN)
    v5 = load(V5)
    u10_config = load(U10)
    by_unit = {
        task["unit_id"]: task
        for config in (main, v5, u10_config)
        for task in config["tasks"]
    }
    u08_a = extract_u08_frame(10.5, "A")
    u08_b = extract_u08_frame(12.0, "B")
    plans = {
        "E32-CW-U02": ([REFS["chenji"]], ["chenji", "jiaotu"]),
        "E32-CW-U09": ([REFS["yunyang"]], ["yunyang", "killer"]),
        "E32-CW-U10": ([u08_a, u08_b], ["chenji", "yunyang", "qisan", "killer"]),
        "E32-CW-U15": ([REFS["chenji"]], ["chenji", "jiaotu", "wuyun", "yunyang"]),
        "E32-CW-U16": ([REFS["chenji"]], ["chenji", "jiaotu", "wuyun", "yunyang"]),
        "E32-CW-U17": ([REFS["chenji"]], ["chenji", "jiaotu", "wuyun", "yunyang"]),
    }
    tasks = [rebuild_task(by_unit[unit], *plans[unit]) for unit in plans]
    config = json.loads(json.dumps(main, ensure_ascii=False))
    config.update({
        "status": "READY_CHANGED_INPUT_MINIMAL_REFERENCE_REPAIR",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "targeted_unit_replacement": True,
        "streaming_submission_policy": "SUBMIT_EACH_UNIT_IMMEDIATELY_WHEN_ITS_OWN_DEPENDENCIES_PASS",
        "tasks": tasks,
    })
    write(CONFIG, config)
    prompt_texts = {task["task_key"]: (ROOT / task["prompt_file"]).read_text(encoding="utf-8") for task in tasks}
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
        ef = validate_entity_reference_task(task)
        df = validate_duration_task(task)
        existing = find_existing_paid_candidate("E32", task)
        checks["entity_reference_sequence"]["results"].append({"task_key": task["task_key"], "failures": ef})
        checks["duration_policy"]["results"].append({"task_key": task["task_key"], "failures": df})
        checks["generation_deduplication"]["results"].append({"task_key": task["task_key"], "existing": existing})
        if ef:
            checks["entity_reference_sequence"]["status"] = "FAIL"
        if df:
            checks["duration_policy"]["status"] = "FAIL"
        if existing is not None:
            checks["generation_deduplication"]["status"] = "FAIL"
    writer_ok, writer_failures = validate_writer_agent_provenance(config)
    checks["writer_provenance"] = {"status": "PASS" if writer_ok else "FAIL", "failures": writer_failures}
    report = {
        "schema": "qingshan.e32_minimal_reference_repair_precheck.v1",
        "episode": "E32",
        "status": "PASS" if all(row.get("status") == "PASS" for row in checks.values()) else "FAIL",
        "checks": checks,
        "config": rel(CONFIG),
        "units": list(plans),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    write(PRECHECK, report)
    print(json.dumps({"status": report["status"], "config": rel(CONFIG), "precheck": rel(PRECHECK), "units": report["units"]}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
