#!/usr/bin/env python3
"""Build E32 failed-only repairs using one ordered identity/state reel per unit."""

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
CONFIG = BASE / "E32_VIDEO_IDENTITY_STATE_REEL_TRANSPORT_V10.json"
PRECHECK = BASE / "qa/E32_VIDEO_IDENTITY_STATE_REEL_TRANSPORT_V10_PRECHECK.json"
PROMPT_DIR = BASE / "prompts_v10_identity_state_reel_transport"
REEL_DIR = ROOT / "working_assets/e32_identity_state_reel_transport_v10_20260723"
PROMPT_MANIFEST = BASE / "E32_ALL_17_VIDEO_PROMPT_MANIFEST_V10_IDENTITY_STATE_REEL_TRANSPORT.json"
TRANSFORM = "IMAGE_SEQUENCE_TO_VIDEO_IDENTITY_REEL_2S_PER_IMAGE_720X1280"
TARGET_UNITS = {"E32-CW-U10", "E32-CW-U15", "E32-CW-U16", "E32-CW-U17"}
SEGMENT_SECONDS = 2.0


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
    helper = ROOT / "tools/find_ffmpeg.sh"
    if helper.is_file():
        result = subprocess.run([str(helper)], check=True, capture_output=True, text=True)
        found = result.stdout.strip()
        if found:
            return found
    raise SystemExit("ffmpeg unavailable")


def sequence_path(row: dict) -> str:
    return str(row.get("path") or row.get("asset_path") or row.get("local_path") or "")


def reference_reel(unit_id: str, rows: list[dict]) -> str:
    digest = hashlib.sha256("\n".join(sha(sequence_path(row)) for row in rows).encode("ascii")).hexdigest()[:12]
    target = REEL_DIR / f"{unit_id}_{digest}_identity_state_reel.mp4"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        return relative(target)
    command = [ffmpeg_binary(), "-hide_banner", "-loglevel", "error", "-y"]
    for row in rows:
        command.extend(["-loop", "1", "-t", str(SEGMENT_SECONDS), "-i", str(absolute(sequence_path(row)))])
    filters = []
    labels = []
    for index in range(len(rows)):
        label = f"v{index}"
        filters.append(
            f"[{index}:v]scale=720:1280:force_original_aspect_ratio=decrease,"
            f"pad=720:1280:(ow-iw)/2:(oh-ih)/2:color=black,fps=24,format=yuv420p,"
            f"trim=duration={SEGMENT_SECONDS},setpts=PTS-STARTPTS[{label}]"
        )
        labels.append(f"[{label}]")
    filters.append(f"{''.join(labels)}concat=n={len(rows)}:v=1:a=0[outv]")
    command.extend([
        "-filter_complex", ";".join(filters), "-map", "[outv]", "-an",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-movflags", "+faststart",
        str(target),
    ])
    subprocess.run(command, check=True)
    return relative(target)


def prompt_variant(task: dict, rows: list[dict], reel_path: str) -> str:
    source = absolute(task["prompt_file"]).read_text(encoding="utf-8")
    mappings = []
    for index, row in enumerate(rows):
        start = index * SEGMENT_SECONDS
        end = start + SEGMENT_SECONDS
        role = str(row.get("role") or f"REFERENCE_{index + 1}")
        mappings.append(f"{start:.1f}-{end:.1f}秒={role}")
    replacement = (
        "【参考视频身份与状态职责】@视频1是本单元唯一的备案参考卷，按原始参考图上传顺序逐张展示："
        + "；".join(mappings)
        + "。各时间段只锁对应人物身份、场景或不可插值状态；必须按时间段读取，禁止融合角色、"
          "禁止复制参考卷的静止构图，连续表演仍完全服从同一逐拍spec。"
    )
    lines = source.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("【参考图职责】"):
            lines[index] = replacement
            break
    else:
        raise SystemExit(f"reference responsibility line missing: {task['unit_id']}")
    lines.insert(1, "【参考卷文件】@视频1=本单元唯一备案参考卷；不得把参考卷当作成片动作来源。")
    target = PROMPT_DIR / f"{task['unit_id']}-PERFORMANCE-V10-IDENTITY-STATE-REEL.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return relative(target)


def main() -> int:
    source_config = load(SOURCE)
    manifest = load(absolute(source_config["complete_video_prompt_manifest_ref"]))
    manifest_rows = {row["unit_id"]: row for row in manifest["rows"]}
    tasks = []
    for source in source_config["tasks"]:
        if source["unit_id"] not in TARGET_UNITS:
            continue
        task = json.loads(json.dumps(source, ensure_ascii=False))
        rows = list(task.get("reference_image_sequence") or [])
        if not rows or any(not sequence_path(row) for row in rows):
            raise SystemExit(f"reference sequence incomplete: {task['unit_id']}")
        reel = reference_reel(task["unit_id"], rows)
        reel_sha = sha(reel)
        identity_rows = []
        state_rows = []
        for index, row in enumerate(rows):
            source_path = sequence_path(row)
            start = index * SEGMENT_SECONDS
            end = start + SEGMENT_SECONDS
            label = f"@视频1[{start:.1f}-{end:.1f}秒]"
            matching_bindings = [
                binding for binding in task.get("multimodal_entity_bindings") or []
                if absolute(str(binding.get("visual_reference") or "")).resolve() == absolute(source_path).resolve()
            ]
            transported = {
                "asset_label": label,
                "role": row.get("role"),
                "path": reel,
                "sha256": reel_sha,
                "identity_reference": bool(matching_bindings) or "IDENTITY_REFERENCE" in str(row.get("role") or "").upper(),
                "transport_derivative_of": source_path,
                "transport_derivative_source_sha256": sha(source_path),
                "transport_transform": TRANSFORM,
                "segment_start_seconds": start,
                "segment_end_seconds": end,
            }
            if transported["identity_reference"]:
                identity_rows.append(transported)
            else:
                state_rows.append(transported)
            for binding in matching_bindings:
                binding.pop("identity_image_slot", None)
                binding["identity_video_slot"] = label
        task["multimodal_binding_sha256"] = binding_digest(task.get("multimodal_entity_bindings") or [])
        old_plan = int(task.get("planned_reference_image_count") or 0)
        task.update({
            "reference_images": [],
            "reference_image_sequence": [],
            "planned_reference_image_count": 0,
            "state_reference_minimum": 0,
            "still_sequence_only_allowed": False,
            "reference_video_only_authorized": True,
            "reference_video_plan_reason": "Provider image ingress failed repeatedly with explicit zero charge; all original ordered images are preserved in one SHA-audited time-segmented reference reel.",
            "anchor_plan_transport_substitution": {
                "status": "PASS",
                "source_planned_reference_image_count": old_plan,
                "source_reference_sequence_count": len(rows),
                "substitute_reference_video_count": 1,
                "reason": "UPSTREAM_IMAGE_INGRESS_FAILURE_ZERO_CREDIT_AND_REFERENCE_VIDEO_CAP",
            },
            "reference_videos": [reel],
            "reference_identity_video_sequence": identity_rows,
            "reference_state_video_sequence": state_rows,
            "reference_image_transport": "identity_state_reel",
            "generation_transport_revision": "IDENTITY_STATE_REEL_V1",
            "task_key": f"{task['unit_id']}-PERFORMANCE-V10-IDENTITY-STATE-REEL",
            "batch_id": "E32-PERFORMANCE-V10-IDENTITY-STATE-REEL",
            "status": "READY_TO_SUBMIT",
        })
        task.pop("reference_image_urls", None)
        task.pop("reference_image_asset_ids", None)
        task.pop("resolved_reference_image_asset_ids", None)
        prompt_path = prompt_variant(task, rows, reel)
        task["prompt_file"] = prompt_path
        task["prompt_sha256"] = sha(prompt_path)
        task["generation_fingerprint"] = generation_fingerprint(task)
        manifest_rows[task["unit_id"]]["prompt_path"] = prompt_path
        manifest_rows[task["unit_id"]]["prompt_sha256"] = task["prompt_sha256"]
        tasks.append(task)

    manifest["schema"] = "qingshan.complete_video_prompt_manifest.v10_identity_state_reel_transport"
    manifest["recorded_at"] = datetime.now(timezone.utc).isoformat()
    write(PROMPT_MANIFEST, manifest)
    config = json.loads(json.dumps(source_config, ensure_ascii=False))
    config.update({
        "status": "READY_CHANGED_INPUT_IDENTITY_STATE_REEL_TRANSPORT",
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
        "schema": "qingshan.e32_identity_state_reel_transport_precheck.v1",
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
