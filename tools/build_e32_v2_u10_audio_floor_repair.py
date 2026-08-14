#!/usr/bin/env python3
"""Repair only E32 U10's sub-two-second dialogue reference without slowing it."""

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
CONFIG = BASE / "E32_VIDEO_U10_AUDIO_FLOOR_REPAIR_V4.json"
PRECHECK = BASE / "qa/E32_VIDEO_U10_AUDIO_FLOOR_REPAIR_V4_PRECHECK.json"
SOURCE_AUDIO = ROOT / "working_assets/e32_dialogue_audio_refs_v2_20260723/wav/E32-DIA-013.wav"
TARGET_AUDIO = ROOT / "working_assets/e32_dialogue_audio_refs_v2_20260723/video_reference_wav_v4/E32-DIA-013-ROOMTONE-2S20.wav"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_audio() -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        bundled = list((ROOT / ".agentcut_env").glob("lib/python*/site-packages/agentcut/vendor/darwin-arm64/ffmpeg"))
        ffmpeg = str(bundled[0]) if bundled else None
    if not ffmpeg:
        raise SystemExit("ffmpeg unavailable")
    TARGET_AUDIO.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            ffmpeg, "-y", "-i", str(SOURCE_AUDIO),
            "-filter_complex",
            "[0:a]apad=whole_dur=2.20[a];anoisesrc=color=pink:amplitude=0.00006:d=2.20:r=48000[n];[a][n]amix=inputs=2:duration=longest:normalize=0",
            "-t", "2.20", "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(TARGET_AUDIO),
        ],
        check=True,
        capture_output=True,
    )


def main() -> int:
    build_audio()
    config = load(SOURCE_CONFIG)
    task = next(row for row in config["tasks"] if row["unit_id"] == "E32-CW-U10")
    task = json.loads(json.dumps(task, ensure_ascii=False))
    old_path = next(
        row["path"] for row in task["dialogue_audio_assets"] if row["dia_id"] == "E32-DIA-013"
    )
    task["reference_audios"] = [rel(TARGET_AUDIO) if value == old_path else value for value in task["reference_audios"]]
    for row in task["dialogue_audio_assets"]:
        if row["dia_id"] == "E32-DIA-013":
            row.update({
                "path": rel(TARGET_AUDIO),
                "sha256": sha(TARGET_AUDIO),
                "duration_seconds": 2.2,
                "local_transform": "PRESERVE_SPEECH_PLUS_MINUS_84DB_PINK_ROOMTONE_TO_2_20S",
            })
    task["task_key"] = "E32-CW-U10-PERFORMANCE-V4-AUDIO-FLOOR"
    task["batch_id"] = "E32-PERFORMANCE-V4-U10-AUDIO-FLOOR"
    task["generation_fingerprint"] = generation_fingerprint(task)

    config.update({
        "status": "READY_TARGETED_U10_AUDIO_FLOOR_REPAIR",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "targeted_unit_replacement": True,
        "concurrency": 1,
        "tasks": [task],
    })
    write(CONFIG, config)
    prompt_text = (ROOT / task["prompt_file"]).read_text(encoding="utf-8")
    checks = {
        "corrected_pipeline_quality": validate_corrected_pipeline_quality(config),
        "complete_video_prompt_manifest": validate_complete_video_prompt_manifest(config),
        "dialogue_manifest_coverage": validate_dialogue_manifest_coverage(config),
        "prompt_professionalism": evaluate_prompt_professionalism(config),
        "space_camera_constraint": evaluate_space_camera([task], {task["task_key"]: prompt_text}),
        "multimodal_character_binding": evaluate_bindings(config),
        "scene_authority": evaluate_scene_authority(config["scene_contract_ref"], config),
        "entity_reference_sequence": {"status": "PASS", "failures": validate_entity_reference_task(task)},
        "duration_policy": {"status": "PASS", "failures": validate_duration_task(task)},
        "generation_deduplication": {
            "status": "PASS",
            "existing_candidate": find_existing_paid_candidate("E32", task),
            "generation_fingerprint": task["generation_fingerprint"],
        },
        "current_workflow_credit_gate": evaluate_episode_credit_gate("E32", limit=6000),
    }
    for key in ("entity_reference_sequence", "duration_policy"):
        if checks[key]["failures"]:
            checks[key]["status"] = "FAIL"
    if checks["generation_deduplication"]["existing_candidate"] is not None:
        checks["generation_deduplication"]["status"] = "FAIL"
    writer_ok, writer_failures = validate_writer_agent_provenance(config)
    checks["writer_provenance"] = {"status": "PASS" if writer_ok else "FAIL", "failures": writer_failures}
    report = {
        "schema": "qingshan.e32_u10_audio_floor_precheck.v1",
        "episode": "E32",
        "status": "PASS" if all(row.get("status") == "PASS" for row in checks.values()) else "FAIL",
        "checks": checks,
        "config": rel(CONFIG),
        "source_failed_attempt_credit": 0,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    write(PRECHECK, report)
    print(json.dumps({"status": report["status"], "config": rel(CONFIG), "precheck": rel(PRECHECK)}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
