#!/usr/bin/env python3
"""Build the changed-input, failed-only E32 U16 V11 retry."""

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
SOURCE = BASE / "E32_VIDEO_IDENTITY_STATE_REEL_TRANSPORT_V10.json"
CONFIG = BASE / "E32_VIDEO_U16_FAILED_ONLY_V11.json"
PRECHECK = BASE / "qa/E32_VIDEO_U16_FAILED_ONLY_V11_PRECHECK.json"
PROMPT = BASE / "prompts_v11_u16_failed_only/E32-CW-U16-PERFORMANCE-V11-FAILED-ONLY.txt"
MANIFEST = BASE / "E32_ALL_17_VIDEO_PROMPT_MANIFEST_V11_U16_FAILED_ONLY.json"


def absolute(value: str | Path) -> Path:
    value = Path(value)
    return value if value.is_absolute() else ROOT / value


def relative(value: Path) -> str:
    return str(value.relative_to(ROOT))


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path: str | Path) -> str:
    return hashlib.sha256(absolute(path).read_bytes()).hexdigest()


def main() -> int:
    config = load(SOURCE)
    task = next(json.loads(json.dumps(row, ensure_ascii=False)) for row in config["tasks"] if row["unit_id"] == "E32-CW-U16")
    source_prompt = absolute(task["prompt_file"]).read_text(encoding="utf-8")
    revision = (
        "【U16失败项定向输入修订】@视频1的四段必须依次且独立读取：0-2秒陈迹、2-4秒皎兔、"
        "4-6秒乌云、6-8秒云羊；四个身份不得融合或互换。参考卷只锁人物身份，屋脊对话、"
        "巡检灯网合围和陈迹反制判断完全按下方逐拍脚本连续表演。"
    )
    lines = source_prompt.splitlines()
    lines.insert(2, revision)
    PROMPT.parent.mkdir(parents=True, exist_ok=True)
    PROMPT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    task.update({
        "task_key": "E32-CW-U16-PERFORMANCE-V11-FAILED-ONLY",
        "batch_id": "E32-PERFORMANCE-V11-U16-FAILED-ONLY",
        "prompt_file": relative(PROMPT),
        "prompt_sha256": sha(PROMPT),
        "generation_transport_revision": "IDENTITY_STATE_REEL_V1_U16_MAPPING_REVISION",
        "status": "READY_TO_SUBMIT",
    })
    task["generation_fingerprint"] = generation_fingerprint(task)

    manifest = load(absolute(config["complete_video_prompt_manifest_ref"]))
    for row in manifest["rows"]:
        if row["unit_id"] == "E32-CW-U16":
            row["prompt_path"] = relative(PROMPT)
            row["prompt_sha256"] = task["prompt_sha256"]
    manifest["schema"] = "qingshan.complete_video_prompt_manifest.v11_u16_failed_only"
    manifest["recorded_at"] = datetime.now(timezone.utc).isoformat()
    write(MANIFEST, manifest)

    config.update({
        "status": "READY_CHANGED_INPUT_U16_FAILED_ONLY",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "batch_id": "E32-PERFORMANCE-V11-U16-FAILED-ONLY",
        "targeted_unit_replacement": True,
        "retry_policy": "FAILED_ITEMS_ONLY_CHANGED_INPUT",
        "streaming_submission_policy": "SUBMIT_EACH_UNIT_IMMEDIATELY_WHEN_ITS_OWN_DEPENDENCIES_PASS",
        "max_retries": 0,
        "complete_video_prompt_manifest_ref": relative(MANIFEST),
        "tasks": [task],
    })
    write(CONFIG, config)

    prompt_texts = {task["task_key"]: PROMPT.read_text(encoding="utf-8")}
    entity_failures = validate_entity_reference_task(task)
    duration_failures = validate_duration_task(task)
    checks = {
        "corrected_pipeline_quality": validate_corrected_pipeline_quality(config),
        "complete_video_prompt_manifest": validate_complete_video_prompt_manifest(config),
        "dialogue_manifest_coverage": validate_dialogue_manifest_coverage(config),
        "prompt_professionalism": evaluate_prompt_professionalism(config),
        "space_camera_constraint": evaluate_space_camera([task], prompt_texts),
        "multimodal_character_binding": evaluate_bindings(config),
        "scene_authority": evaluate_scene_authority(config["scene_contract_ref"], config),
        "entity_reference_sequence": {"status": "PASS" if not entity_failures else "FAIL", "failures": entity_failures},
        "duration_policy": {"status": "PASS" if not duration_failures else "FAIL", "failures": duration_failures},
        "generation_deduplication": {
            "status": "PASS" if find_existing_paid_candidate("E32", task) is None else "FAIL",
            "existing": find_existing_paid_candidate("E32", task),
        },
        "current_workflow_credit_gate": evaluate_episode_credit_gate("E32", limit=6000),
    }
    writer_ok, writer_failures = validate_writer_agent_provenance(config)
    checks["writer_provenance"] = {"status": "PASS" if writer_ok else "FAIL", "failures": writer_failures}
    report = {
        "schema": "qingshan.e32_u16_failed_only_precheck.v1",
        "episode": "E32",
        "unit_id": "E32-CW-U16",
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
