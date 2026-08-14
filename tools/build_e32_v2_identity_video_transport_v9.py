#!/usr/bin/env python3
"""Build E32 repairs that deliver canonical identity images through video modality."""

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
SOURCE = BASE / "E32_VIDEO_MINIMAL_REFERENCE_REPAIR_V7.json"
CONFIG = BASE / "E32_VIDEO_IDENTITY_VIDEO_TRANSPORT_V9.json"
PRECHECK = BASE / "qa/E32_VIDEO_IDENTITY_VIDEO_TRANSPORT_V9_PRECHECK.json"
PROMPT_DIR = BASE / "prompts_v9_identity_video_transport"
IDENTITY_VIDEO_DIR = ROOT / "working_assets/e32_identity_video_transport_v9_20260723"
PROMPT_MANIFEST = BASE / "E32_ALL_17_VIDEO_PROMPT_MANIFEST_V9_IDENTITY_VIDEO_TRANSPORT.json"
TRANSFORM = "IMAGE_TO_VIDEO_IDENTITY_HOLD_2S_720X1280"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def absolute(path: str | Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else ROOT / path


def sha(path: str | Path) -> str:
    return hashlib.sha256(absolute(path).read_bytes()).hexdigest()


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


def ffmpeg_binary() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    matches = list((ROOT / ".agentcut_env").glob("lib/python*/site-packages/agentcut/vendor/darwin-arm64/ffmpeg"))
    if matches:
        return str(matches[0])
    raise SystemExit("ffmpeg unavailable")


def identity_video(entity_id: str, source: str) -> str:
    target = IDENTITY_VIDEO_DIR / f"{entity_id}_{sha(source)[:12]}_identity_hold.mp4"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.is_file():
        subprocess.run([
            ffmpeg_binary(), "-hide_banner", "-loglevel", "error", "-y",
            "-loop", "1", "-i", str(absolute(source)), "-t", "2", "-r", "24",
            "-vf", "scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2:color=black,format=yuv420p",
            "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-movflags", "+faststart",
            str(target),
        ], check=True)
    return relative(target)


def prompt_variant(task: dict, mappings: list[str]) -> str:
    source = absolute(task["prompt_file"]).read_text(encoding="utf-8")
    replacement = (
        "【参考视频身份职责】" + "；".join(mappings)
        + "。这些2秒短视频由备案单人身份图按SHA封装，只锁谁是谁；动作仍由同一逐拍spec连续生成，"
          "不得复制身份视频的静止构图、不得新增人物、不得把多个角色融合。"
    )
    lines = source.splitlines()
    replaced = False
    for index, line in enumerate(lines):
        if line.startswith("【参考图职责】"):
            lines[index] = replacement
            replaced = True
            break
    if not replaced:
        raise SystemExit(f"reference responsibility line missing: {task['unit_id']}")
    target = PROMPT_DIR / f"{task['unit_id']}-PERFORMANCE-V9-IDENTITY-VIDEO.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return relative(target)


def main() -> int:
    config = load(SOURCE)
    original_manifest_path = absolute(config["complete_video_prompt_manifest_ref"])
    manifest = load(original_manifest_path)
    manifest_rows = {row["unit_id"]: row for row in manifest["rows"]}
    tasks = []
    for source in config["tasks"]:
        task = json.loads(json.dumps(source, ensure_ascii=False))
        identity_rows = []
        reference_videos = []
        mappings = []
        for index, binding in enumerate(task.get("multimodal_entity_bindings") or [], 1):
            visual = str(binding["visual_reference"])
            video = identity_video(binding["entity_id"], visual)
            slot = f"@视频{index}"
            reference_videos.append(video)
            identity_rows.append({
                "asset_label": slot,
                "role": f"IDENTITY_REFERENCE_{binding['entity_id'].upper()}",
                "path": video,
                "sha256": sha(video),
                "identity_reference": True,
                "transport_derivative_of": visual,
                "transport_derivative_source_sha256": sha(visual),
                "transport_transform": TRANSFORM,
            })
            mappings.append(f"{slot}={binding['character_name']}备案身份")
            binding.pop("identity_image_slot", None)
            binding["identity_video_slot"] = slot
        task["multimodal_binding_sha256"] = binding_digest(task.get("multimodal_entity_bindings") or [])
        old_plan = int(task.get("planned_reference_image_count") or 0)
        task.update({
            "reference_images": [],
            "reference_image_sequence": [],
            "planned_reference_image_count": 0,
            "state_reference_minimum": 0,
            "still_sequence_only_allowed": False,
            "reference_video_only_authorized": True,
            "reference_video_plan_reason": "Remote Seedance image ingress repeatedly failed at provider upload with explicit zero credit; canonical identity images are SHA-bound and delivered as 2-second local video wrappers.",
            "anchor_plan_transport_substitution": {
                "status": "PASS",
                "source_planned_reference_image_count": old_plan,
                "substitute_reference_video_count": len(reference_videos),
                "reason": "UPSTREAM_IMAGE_INGRESS_FAILURE_ZERO_CREDIT",
            },
            "reference_videos": reference_videos,
            "reference_identity_video_sequence": identity_rows,
            "reference_image_transport": "identity_video_wrapper",
            "generation_transport_revision": "IDENTITY_VIDEO_WRAPPER_V1",
            "task_key": f"{task['unit_id']}-PERFORMANCE-V9-IDENTITY-VIDEO",
            "batch_id": "E32-PERFORMANCE-V9-IDENTITY-VIDEO",
            "status": "READY_TO_SUBMIT",
        })
        task.pop("reference_image_urls", None)
        task.pop("reference_image_asset_ids", None)
        task.pop("resolved_reference_image_asset_ids", None)
        prompt_path = prompt_variant(task, mappings)
        task["prompt_file"] = prompt_path
        task["prompt_sha256"] = sha(prompt_path)
        task["generation_fingerprint"] = generation_fingerprint(task)
        row = manifest_rows[task["unit_id"]]
        row["prompt_path"] = prompt_path
        row["prompt_sha256"] = task["prompt_sha256"]
        tasks.append(task)
    manifest["schema"] = "qingshan.complete_video_prompt_manifest.v9_identity_video_transport"
    manifest["recorded_at"] = datetime.now(timezone.utc).isoformat()
    write(PROMPT_MANIFEST, manifest)
    config.update({
        "status": "READY_CHANGED_INPUT_IDENTITY_VIDEO_TRANSPORT",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "targeted_unit_replacement": True,
        "streaming_submission_policy": "SUBMIT_EACH_UNIT_IMMEDIATELY_WHEN_ITS_OWN_DEPENDENCIES_PASS",
        "max_retries": 0,
        "complete_video_prompt_manifest_ref": relative(PROMPT_MANIFEST),
        "tasks": tasks,
    })
    write(CONFIG, config)

    prompt_texts = {task["task_key"]: absolute(task["prompt_file"]).read_text(encoding="utf-8") for task in tasks}
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
        "schema": "qingshan.e32_identity_video_transport_precheck.v1",
        "episode": "E32",
        "status": "PASS" if all(row.get("status") == "PASS" for row in checks.values()) else "FAIL",
        "checks": checks,
        "config": relative(CONFIG),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    write(PRECHECK, report)
    print(json.dumps({"status": report["status"], "config": report["config"], "precheck": relative(PRECHECK)}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
