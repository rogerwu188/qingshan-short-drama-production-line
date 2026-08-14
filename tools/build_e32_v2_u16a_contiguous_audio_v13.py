#!/usr/bin/env python3
"""Retry only E32 U16A with one contiguous, beat-aligned dialogue reference."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
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
SOURCE_CONFIG = BASE / "E32_VIDEO_U16_SPLIT_PERFORMANCE_V12.json"
CONFIG = BASE / "E32_VIDEO_U16A_CONTIGUOUS_AUDIO_V13.json"
PRECHECK = BASE / "qa/E32_VIDEO_U16A_CONTIGUOUS_AUDIO_V13_PRECHECK.json"
PROMPT = BASE / "prompts_v13_u16a_contiguous_audio/E32-CW-U16A-PERFORMANCE-V13-CONTIGUOUS-AUDIO.txt"
PROMPT_MANIFEST = BASE / "E32_ALL_18_VIDEO_PROMPT_MANIFEST_U16A_CONTIGUOUS_AUDIO_V13.json"
AUDIO = ROOT / "working_assets/e32_dialogue_audio_refs_v2_20260723/wav/E32-U16A-DIA-023-024-CONTIGUOUS-V13.wav"
NATURAL_SPLIT_CONTRACT = BASE / "E32_U16_NATURAL_SPLIT_STANDARD_CONTRACT_V1.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def absolute(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    source_config = load(SOURCE_CONFIG)
    source = next(task for task in source_config["tasks"] if task["unit_id"] == "E32-CW-U16A")
    task = deepcopy(source)
    source_prompt = absolute(source["prompt_file"]).read_text(encoding="utf-8")
    old_audio_block = """【原生对白与音频模态】视频模型必须按参考音频原生生成云羊的自然中文普通话、同步口型、气息、表情与起止时间；字幕仅后期烧录：
- E32-DIA-023｜云羊逐字说：“一个圈里，巡检线、景朝暗桩、内院私兵……”｜精确台词音频=@音频1
- E32-DIA-024｜云羊逐字说：“全挤一处。谁也不信谁。”｜精确台词音频=@音频2
"""
    new_audio_block = """【原生对白与音频模态】@音频1是一条不可拆分的连续表演参考音轨：0.0-1.0秒为落檐呼吸留白，1.0-7.304秒为DIA-023，7.304-7.704秒为自然停顿，7.704-10.704秒为DIA-024。视频模型必须按整条音轨原生生成云羊的自然中文普通话，同步口型、气息、表情与起止时间；禁止把两句分配给不同人物，字幕仅后期烧录：
- E32-DIA-023｜云羊逐字说：“一个圈里，巡检线、景朝暗桩、内院私兵……”｜连续参考音轨=@音频1前段
- E32-DIA-024｜云羊逐字说：“全挤一处。谁也不信谁。”｜连续参考音轨=@音频1后段
"""
    if old_audio_block not in source_prompt:
        raise SystemExit("U16A source audio block not found")
    prompt_text = source_prompt.replace(old_audio_block, new_audio_block).replace(
        "并随@音频2逐字说出台词",
        "并随@音频1后半段逐字说出台词",
    )
    PROMPT.parent.mkdir(parents=True, exist_ok=True)
    PROMPT.write_text(prompt_text, encoding="utf-8")
    audio_sha = sha(AUDIO)
    task.update({
        "task_key": "E32-CW-U16A-PERFORMANCE-V13-CONTIGUOUS-AUDIO",
        "batch_id": "E32-U16A-CONTIGUOUS-AUDIO-V13",
        "prompt_file": relative(PROMPT),
        "prompt_sha256": sha(PROMPT),
        "reference_audios": [relative(AUDIO)],
        "reference_audio_asset_ids": [],
        "generation_transport_revision": "U16A_CONTIGUOUS_DIALOGUE_AUDIO_V13",
        "status": "READY_TO_SUBMIT",
    })
    for row in task["dialogue_audio_assets"]:
        row.update({
            "audio_slot": "@音频1",
            "path": relative(AUDIO),
            "sha256": audio_sha,
            "duration_seconds": 10.70425,
            "purpose": "EXACT_TARGET_DIALOGUE_REFERENCE",
            "local_transform": "LEADING_SILENCE_1S_PLUS_LINES_WITH_0_4S_PAUSE",
        })
    task["multimodal_entity_bindings"][0]["dialogue_audio_slots"] = ["@音频1"]
    task["multimodal_binding_sha256"] = binding_digest(task["multimodal_entity_bindings"])
    for key in (
        "task_id", "remote_status", "output_path", "sha256", "credit_attempts", "submit_response",
        "resolved_reference_audio_asset_ids", "resolved_reference_video_asset_ids", "retry_count", "retry_after",
    ):
        task.pop(key, None)
    task["generation_fingerprint"] = generation_fingerprint(task)

    manifest = load(absolute(source_config["complete_video_prompt_manifest_ref"]))
    row = next(row for row in manifest["rows"] if row["unit_id"] == "E32-CW-U16A")
    row.update({"prompt_path": task["prompt_file"], "prompt_sha256": task["prompt_sha256"]})
    manifest.update({
        "schema": "qingshan.complete_video_prompt_manifest.u16a_contiguous_audio.v13",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "split_replacement_revision": "U16A_CONTIGUOUS_DIALOGUE_AUDIO_V13",
    })
    write(PROMPT_MANIFEST, manifest)

    config = deepcopy(source_config)
    config.update({
        "status": "READY_U16A_CONTIGUOUS_AUDIO_V13",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "batch_id": "E32-U16A-CONTIGUOUS-AUDIO-V13",
        "natural_split_gate_required": True,
        "natural_split_contract_ref": relative(NATURAL_SPLIT_CONTRACT),
        "complete_video_prompt_manifest_ref": relative(PROMPT_MANIFEST),
        "tasks": [task],
        "max_retries": 0,
    })
    write(CONFIG, config)

    prompt_texts = {task["task_key"]: prompt_text}
    checks = {
        "corrected_pipeline_quality": validate_corrected_pipeline_quality(config),
        "complete_video_prompt_manifest": validate_complete_video_prompt_manifest(config),
        "dialogue_manifest_coverage": validate_dialogue_manifest_coverage(config),
        "prompt_professionalism": evaluate_prompt_professionalism(config),
        "space_camera_constraint": evaluate_space_camera([task], prompt_texts),
        "multimodal_character_binding": evaluate_bindings(config),
        "scene_authority": evaluate_scene_authority(config["scene_contract_ref"], config),
        "entity_reference_sequence": {"status": "PASS", "failures": validate_entity_reference_task(task)},
        "duration_policy": {"status": "PASS", "failures": validate_duration_task(task)},
        "generation_deduplication": {"status": "PASS", "existing": find_existing_paid_candidate("E32", task)},
        "current_workflow_credit_gate": evaluate_episode_credit_gate("E32", limit=6000),
    }
    if checks["entity_reference_sequence"]["failures"]:
        checks["entity_reference_sequence"]["status"] = "FAIL"
    if checks["duration_policy"]["failures"]:
        checks["duration_policy"]["status"] = "FAIL"
    if checks["generation_deduplication"]["existing"] is not None:
        checks["generation_deduplication"]["status"] = "FAIL"
    writer_ok, writer_failures = validate_writer_agent_provenance(config)
    checks["writer_provenance"] = {"status": "PASS" if writer_ok else "FAIL", "failures": writer_failures}
    report = {
        "schema": "qingshan.e32_u16a_contiguous_audio_precheck.v13",
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
