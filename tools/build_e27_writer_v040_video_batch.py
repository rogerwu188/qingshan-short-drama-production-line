#!/usr/bin/env python3
"""Build the E27 Writer Agent v0.4 24-shot concurrent video batch."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path("/Users/rogerwu/qingshan_short_drama")
REVIEW = ROOT / "workflow/writer_agent/e27_agent_native_v040_20260720/review/E27_VIDEO_GENERATION_PROMPTS_24_REVIEW.json"
DEST = ROOT / "workflow/writer_agent/e27_agent_native_v040_20260720/production/video_batch_v1"
GENERATED = Path("/Users/rogerwu/Documents/Codex/2026-07-20/qingshan-professional-writer-agent/outputs/qingshan-writer-agent/examples/e27.agent-native.generated.json")
COMPILED = Path("/Users/rogerwu/Documents/Codex/2026-07-20/qingshan-professional-writer-agent/outputs/qingshan-writer-agent/examples/e27.agent-native.compiled.json")
FAILED_AUDIO_MIN_DURATION_SHOTS = {"E27-N06", "E27-N09", "E27-N12", "E27-N16", "E27-N22"}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative_or_absolute(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def main() -> int:
    review = load(REVIEW)
    items = review.get("items") or []
    if len(items) != 24:
        raise SystemExit(f"expected 24 review items, got {len(items)}")

    tasks = []
    selection = []
    seen = set()
    for item in items:
        shot_id = item["shot_id"]
        if shot_id in seen:
            raise SystemExit(f"duplicate shot_id: {shot_id}")
        seen.add(shot_id)

        prompt_path = Path(item["prompt_file"])
        source = item["source_image"]
        source_path = Path(source["path"])
        if not prompt_path.is_file() or sha256(prompt_path) != item["prompt_sha256"]:
            raise SystemExit(f"prompt SHA drift: {shot_id}")
        if not source_path.is_file() or sha256(source_path) != source["sha256"]:
            raise SystemExit(f"source image SHA drift: {shot_id}")

        audio_bindings = item.get("audio_bindings") or []
        audio_asset_ids = []
        for binding in audio_bindings:
            asset_id = binding.get("voice_asset_id") or binding.get("asset_id")
            if asset_id and asset_id not in audio_asset_ids:
                audio_asset_ids.append(asset_id)
        duration = int(item["duration_seconds"])
        tasks.append({
            "task_key": f"{shot_id}-WRITER-AGENT-V040-VIDEO-V1",
            "tool_type": "video_generation",
            "source_id": shot_id,
            "shot_id": shot_id,
            "scene_id": item["scene_id"],
            "visual_zone": f"{item['scene_id']}::{shot_id}",
            "duration": duration,
            "duration_seconds": duration,
            "duration_plan": {
                "policy": "qingshan.shot_generation_duration.v4",
                "duration_seconds": duration,
                "rationale": (
                    f"Writer Agent v0.4 contract assigns {duration}s to {shot_id} from its exact "
                    "dialogue, action, reaction and within-shot camera plan; no fixed-duration normalization."
                ),
                "edit_policy": "Generate the full contract performance; AgentCut may trim only at real speech and action boundaries.",
            },
            "model": "seedance-2.0-pro",
            "aspect_ratio": "9:16",
            "resolution": "720p",
            "prompt_file": relative_or_absolute(prompt_path),
            "prompt_sha256": item["prompt_sha256"],
            "reference_images": [str(source_path)],
            "source_image_sha256": source["sha256"],
            "source_admission": source["admission"],
            "source_review_id": source["review_id"],
            "reference_audio_asset_ids": audio_asset_ids,
            "audio_slot_bindings": audio_bindings,
            "audio_binding_status": (
                "PASS_IMMUTABLE_ASSET_BOUND" if audio_asset_ids
                else "UNSUPPORTED_NATIVE_CANDIDATE_REQUIRES_VOICE_PROFILE_QA"
            ),
            "camera_motion": item.get("camera_motion"),
            "status": "READY_CONCURRENT_SUBMIT",
        })
        selection.append(source)

    config = {
        "schema": "qingshan.episode_parallel_batch.config.v1",
        "episode": "E27",
        "status": "READY_24_VIDEO_CONCURRENT_SUBMIT",
        "concurrency": 24,
        "max_retries": 1,
        "output_dir": "working_assets/e27_writer_agent_v040_video_v1_20260720/candidates",
        "qa_dir": "qa/e27_writer_agent_v040_video_v1_20260720",
        "scene_contract_ref": "workflow/writer_agent/e27_agent_native_v030_20260720/production/scene_state.json",
        "script_readiness_report": "workflow/writer_agent/e27_agent_native_v030_20260720/production/script_readiness.json",
        "writer_agent_provenance": {
            "status": "PASS",
            "agent_version": "0.4.0",
            "schema_version": "1.3.0",
            "generated_script": str(GENERATED),
            "generated_script_sha256": sha256(GENERATED),
            "compiled_script": str(COMPILED),
            "compiled_script_sha256": sha256(COMPILED),
        },
        "still_gate": "workflow/tasks/E27_WRITER_AGENT_V030_FINAL_STILL_GATE_STATUS_20260720.json",
        "conditional_admission": "workflow/tasks/E27_N09_CONDITIONAL_MACHINE_ADMISSION_20260720.json",
        "voice_registry": "configs/e27_voice_binding_registry_v1_20260720.json",
        "review_gate": "qa/e27_writer_agent_v040_video_prompt_review_20260720/E27_VIDEO_PROMPT_REVIEW_GATE.json",
        "base_batch_note": (
            "Submit all 24 Writer Agent v0.4 video contracts concurrently. Preserve passed results; "
            "repair and resubmit only failed items. The v0.3 batch remains rollback evidence only."
        ),
        "tasks": tasks,
    }

    DEST.mkdir(parents=True, exist_ok=True)
    config_path = DEST / "video_batch_v1.json"
    selection_path = DEST / "source_selection_24.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    selection_path.write_text(json.dumps({
        "schema": "qingshan.writer_agent_video_source_selection.v1",
        "episode": "E27",
        "status": "PASS_23_EXACT_PLUS_1_CONDITIONAL_MACHINE_ADMISSION",
        "count": len(selection),
        "items": selection,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    recovery_config = dict(config)
    recovery_config.update({
        "status": "READY_5_FAILED_ONLY_CONCURRENT_RESUBMIT",
        "concurrency": 5,
        "max_retries": 1,
        "output_dir": "working_assets/e27_writer_agent_v040_video_v1_audiofix_r1_20260720/candidates",
        "qa_dir": "qa/e27_writer_agent_v040_video_v1_audiofix_r1_20260720",
        "base_batch_note": (
            "Targeted retry for the five tasks rejected at submission because the prior Jiaotu audio asset was 1.58s. "
            "Use replacement immutable asset mf94pbbsymr (2.20s); do not resubmit the 19 accepted tasks."
        ),
        "tasks": [task for task in tasks if task["shot_id"] in FAILED_AUDIO_MIN_DURATION_SHOTS],
    })
    recovery_path = DEST / "video_batch_audiofix_r1_failed_only.json"
    recovery_path.write_text(json.dumps(recovery_config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PASS",
        "tasks": len(tasks),
        "audio_bound_tasks": sum(bool(task["reference_audio_asset_ids"]) for task in tasks),
        "config": relative_or_absolute(config_path),
        "config_sha256": sha256(config_path),
        "source_selection": relative_or_absolute(selection_path),
        "failed_only_recovery_config": relative_or_absolute(recovery_path),
        "failed_only_recovery_config_sha256": sha256(recovery_path),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
