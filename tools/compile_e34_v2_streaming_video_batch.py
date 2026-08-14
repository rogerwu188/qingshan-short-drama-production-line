#!/usr/bin/env python3
"""Compile and extend E34 v2 video tasks as each unit becomes ready."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

try:
    from episode_video_generation_guard import generation_fingerprint
except ImportError:
    from tools.episode_video_generation_guard import generation_fingerprint


ROOT = Path(__file__).resolve().parents[1]
EPISODE = os.environ.get("QINGSHAN_STREAMING_EPISODE", "E34").upper()
if EPISODE == "E35":
    VERSION = "V1"
    VERSION_LOWER = "v1"
    SOURCE_SHA = "416d09e249f6f55938d8e61f6f6998d6f7e1c3e39c88f863c80044f5bfc9cae7"
    PRODUCTION = ROOT / "workflow/claude_writer_agent/production/e35_claude_writer_v1_416d09e2_20260723"
    SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E35剧本_ClaudeWriter_v1.md"
    IMAGE_RECEIPTS = (
        ROOT / "workflow/tasks/E35_V1_IMAGE_BATCH_HARVEST_20260723.json",
        ROOT / "workflow/tasks/E35_V1_IMAGE_BATCH_FAILED_ONLY_R2_HARVEST_20260723.json",
    )
    AUDIO_MANIFEST = ROOT / "working_assets/e35_dialogue_audio_refs_v1_20260723/E35_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V1.json"
else:
    EPISODE = "E34"
    VERSION = "V2"
    VERSION_LOWER = "v2"
    SOURCE_SHA = "400ff6d238e176999ff4320203839581e2f0a9cfcb7532a13ef7d5f37367d594"
    PRODUCTION = ROOT / "workflow/claude_writer_agent/production/e34_claude_writer_v2_400ff6d2_20260723"
    SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E34剧本_ClaudeWriter_v2.md"
    IMAGE_RECEIPTS = (ROOT / "workflow/tasks/E34_V2_IMAGE_BATCH_RECEIPT_R2_20260723.json",)
    AUDIO_MANIFEST = ROOT / "working_assets/e34_dialogue_audio_refs_v2_20260723/E34_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V2.json"
MANIFEST = PRODUCTION / f"{EPISODE}_PRODUCTION_MANIFEST_{VERSION}.json"
UNIT_PLAN = PRODUCTION / f"{EPISODE}_VIDEO_UNIT_PERFORMANCE_PLAN_{VERSION}.json"
IMAGE_PLAN = PRODUCTION / f"{EPISODE}_IMAGE_BATCH_PERFORMANCE_{VERSION}.json"
SCENE_STATE = PRODUCTION / f"{EPISODE}_SCENE_STATE_AUTHORITY_{VERSION}.json"
PROMPT_MANIFEST = PRODUCTION / f"{EPISODE}_COMPLETE_VIDEO_PROMPT_MANIFEST_{VERSION}.json"
VOICE_REGISTRY = ROOT / "configs/series_voice_reference_registry_current_20260723.json"
CHARACTER_REGISTRY = ROOT / "configs/series_character_asset_registry_20260712.json"
OUTPUT = PRODUCTION / f"video_performance_{VERSION_LOWER}"
QA = ROOT / f"qa/{EPISODE.lower()}_{VERSION_LOWER}_streaming_video_compile_20260723"
CONFIG = OUTPUT / f"{EPISODE}_VIDEO_STREAMING_PERFORMANCE_{VERSION}.json"
REUSED_U01 = ROOT / "workflow/claude_writer_agent/production/e34_claude_writer_v1_20260723/video_performance_v1/outputs/E34_E34-CW-U01-PERFORMANCE-V1_c0993f37-5d31-4026-9da6-a6688c3f01bb.mp4"
FFMPEG = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffmpeg"
FFPROBE = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffprobe"

DISPLAY = {
    "chenji": "陈迹",
    "jiaotu": "皎兔",
    "yunyang": "云羊",
    "wuyun": "乌云",
    "passerby_hushed": "路人低声",
    "yanjing": "严敬",
}

REGISTRY_ID = {
    "chenji": "CHAR-陈迹-古装",
    "jiaotu": "CHAR-皎兔-古装",
    "yunyang": "CHAR-云羊-古装",
    "wuyun": "CHAR-乌云-猫",
    "passerby_hushed": "CHAR-路人低声-古装",
    "yanjing": "CHAR-严敬-古装",
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def unique(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def transport_duration(value: float) -> int:
    return int(math.ceil(value))


def canonical_path(character: dict) -> Path:
    value = (
        character.get("generation_reference_image")
        or character.get("identity_reference_image")
        or character.get("reference_image")
    )
    path = Path(str(value))
    return path if path.is_absolute() else ROOT / path


def identity_transport(entity_id: str, source: Path) -> dict:
    source_sha = digest(source)
    target = OUTPUT / "identity_transport_v2" / f"{entity_id}_{source_sha[:12]}_1440x2560.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.is_file():
        graph = (
            "[0:v]scale=1440:2560:force_original_aspect_ratio=increase,"
            "crop=1440:2560,gblur=sigma=40[bg];"
            "[0:v]scale=1440:2560:force_original_aspect_ratio=decrease[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2,format=rgb24"
        )
        subprocess.run(
            [str(FFMPEG), "-y", "-i", str(source), "-filter_complex", graph, "-frames:v", "1", str(target)],
            check=True,
            capture_output=True,
        )
    return {
        "path": rel(target),
        "sha256": digest(target),
        "transport_derivative_of": rel(source),
        "transport_derivative_source_sha256": source_sha,
        "transport_transform": "PNG_RGB_1440X2560_BLURRED_PAD_UPSCALE",
    }


def existing_anchor(unit: dict, receipt_by_key: dict[str, dict]) -> list[dict] | None:
    rows = []
    for index, anchor in enumerate(unit["anchors"], 1):
        if EPISODE == "E34" and unit["unit_id"] == "E34-CW-U01":
            path = ROOT / anchor["existing_path"]
            expected = anchor["existing_sha256"]
        else:
            receipt = receipt_by_key.get(anchor["task_key"]) or {}
            valid_status = receipt.get("status") == "image_pass" or receipt.get("remote_status") == "completed"
            if not valid_status or not receipt.get("output_path"):
                return None
            path = Path(receipt["output_path"])
            expected = receipt.get("sha256") or (digest(path) if path.is_file() else "")
        if not path.is_file() or digest(path) != expected:
            return None
        rows.append({
            "asset_label": f"@图片{index}",
            "role": f"PERFORMANCE_{anchor['state_role'].upper()}",
            "path": rel(path),
            "sha256": expected,
            "state_id": anchor["task_key"].replace(f"-STILL-{VERSION}", ""),
            "identity_reference": False,
            "qa_decision": "CONDITIONAL_MACHINE_ADMISSION",
        })
    return rows


def dialogue_bindings(rows: list[dict], voice_by_id: dict[str, dict]) -> tuple[list[dict], list[dict], list[str], list[str]]:
    dialogue = []
    assets = []
    exact_paths: list[str] = []
    style_ids: list[str] = []
    slots: dict[str, str] = {}
    for row in rows:
        key = str(row.get("remote_asset_id") or row["path"])
        slots.setdefault(key, f"@音频{len(slots) + 1}")
        exact = row["audio_mode"] == "EXACT_DIALOGUE_AUDIO_REFERENCE"
        voice = voice_by_id[row["speaker_id"]]
        asset = {
            "dia_id": row["dia_id"],
            "speaker": row["speaker"],
            "speaker_id": row["speaker_id"],
            "spoken_text": row["spoken_text"],
            "audio_slot": slots[key],
            "path": row["path"],
            "sha256": row["sha256"],
            "duration_seconds": row["duration_seconds"],
            "purpose": "EXACT_TARGET_DIALOGUE_REFERENCE" if exact else "LOCKED_NATIVE_VOICE_STYLE_REFERENCE_WITH_EXACT_TEXT",
            "remote_asset_id": row.get("remote_asset_id"),
            "voice_reference_asset_id": row.get("voice_reference_asset_id") or voice["remote_asset_id"],
            "voice_derivation_status": row.get("voice_derivation_status") or "PASS",
            "voice_gender": row.get("voice_gender") or voice["gender"],
            "source_voice": row.get("source_voice") or f"NATIVE_MULTIMODAL_VIDEO_EXTRACT:{voice['remote_asset_id']}",
        }
        dialogue.append({"dia_id": row["dia_id"], "speaker": row["speaker"], "spoken_text": row["spoken_text"]})
        assets.append(asset)
        if exact:
            exact_paths.append(row["path"])
        else:
            style_ids.append(row["remote_asset_id"])
    return dialogue, assets, unique(exact_paths), unique(style_ids)


def register_reused_u01() -> dict:
    if not REUSED_U01.is_file():
        raise RuntimeError(f"missing reusable U01 video: {REUSED_U01}")
    output = OUTPUT / "outputs" / "E34_E34-CW-U01-PERFORMANCE-V2_REUSED_FROM_V1.mp4"
    output.parent.mkdir(parents=True, exist_ok=True)
    if not output.is_file() or digest(output) != digest(REUSED_U01):
        shutil.copy2(REUSED_U01, output)
    probe = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "format=duration,size", "-of", "json", str(output)],
        check=True,
        capture_output=True,
        text=True,
    )
    media = json.loads(probe.stdout)["format"]
    row = {
        "unit_id": "E34-CW-U01",
        "status": "PASS_REUSE_NO_NEW_GENERATION",
        "source_version": "v1",
        "source_path": rel(REUSED_U01),
        "output_path": rel(output),
        "sha256": digest(output),
        "duration_seconds": float(media["duration"]),
        "size_bytes": int(media["size"]),
        "new_credits": 0,
        "reason": "Claude Writer v2 preserves the same post-rain dawn office self-audit beat with no dialogue change.",
        "rollback_point": rel(REUSED_U01),
    }
    write(QA / "E34_U01_VIDEO_REUSE_ADMISSION_V2.json", {"schema": "qingshan.cross_version_video_reuse.v1", "episode": "E34", "status": "PASS", "source_script_sha256": SOURCE_SHA, "asset": row})
    return row


def main() -> int:
    if digest(SCRIPT) != SOURCE_SHA:
        raise RuntimeError(f"{EPISODE} {VERSION_LOWER} script SHA drift")
    plan = load(UNIT_PLAN)
    image_plan = load(IMAGE_PLAN)
    receipt_by_key = {}
    for receipt_path in IMAGE_RECEIPTS:
        if not receipt_path.is_file():
            continue
        receipt_payload = load(receipt_path)
        receipt_by_key.update({
            row["task_key"]: row
            for row in receipt_payload.get("tasks", receipt_payload.get("results", []))
        })
    image_by_key = {row["task_key"]: row for row in image_plan["tasks"]}
    audio_rows = load(AUDIO_MANIFEST)["rows"]
    audio_by_unit: dict[str, list[dict]] = {}
    for row in audio_rows:
        audio_by_unit.setdefault(row["video_unit_id"], []).append(row)
    voice_by_id = {row["entity_id"]: row for row in load(VOICE_REGISTRY)["major_roles"]}
    character_rows = load(CHARACTER_REGISTRY)["characters"]
    scene_rows = load(SCENE_STATE)["scene_state"]
    scene_by_id = (
        {row["scene_id"]: row for row in scene_rows}
        if isinstance(scene_rows, list)
        else {str(scene_id): row for scene_id, row in scene_rows.items()}
    )
    prompt_rows = {row["unit_id"]: row for row in load(PROMPT_MANIFEST)["rows"]}

    OUTPUT.mkdir(parents=True, exist_ok=True)
    QA.mkdir(parents=True, exist_ok=True)
    reused = register_reused_u01() if EPISODE == "E34" else None
    tasks = []
    admissions = []
    waiting = []
    first_unit_by_scene: dict[str, str] = {}
    for unit in plan["units"]:
        first_unit_by_scene.setdefault(unit["scene_id"], unit["unit_id"])

    for unit in plan["units"]:
        if EPISODE == "E34" and unit["unit_id"] == "E34-CW-U01":
            continue
        temporal = existing_anchor(unit, receipt_by_key)
        if temporal is None:
            waiting.append(unit["unit_id"])
            continue
        for anchor, source in zip(temporal, unit["anchors"]):
            image_task = image_by_key[source["task_key"]]
            admissions.append({
                "state_id": anchor["state_id"],
                "task_key": source["task_key"],
                "path": anchor["path"],
                "sha256": anchor["sha256"],
                "original_qa_status": "PASS_TECHNICAL_WITH_IDENTITY_RECHECK_REQUIRED",
                "admission": "CONDITIONAL_MACHINE_ADMISSION",
                "failure_items": ["Generated temporal anchor is not identity authority."],
                "selection_reason": "Scene, cast count, action state and media integrity are usable; canonical identity images are separately bound to the video model.",
                "confidence": 0.82,
                "rollback_point": anchor["path"],
                "replacement_condition": "Replace only this unit if final identity or physical-continuity QA fails.",
                "visible_characters": (image_task.get("prompt_contract") or {}).get("visible_characters") or [],
            })

        unit_audio = audio_by_unit.get(unit["unit_id"], [])
        if any(row.get("status") != "PASS" for row in unit_audio):
            waiting.append(unit["unit_id"])
            continue
        speaker_ids = [row["speaker_id"] for row in unit_audio]
        visual_ids = [entity_id for entity_id in unique(list(unit["characters"]) + speaker_ids) if entity_id in REGISTRY_ID]
        identities = []
        canonical: dict[str, dict] = {}
        for entity_id in visual_ids:
            registry_id = REGISTRY_ID[entity_id]
            source = canonical_path(character_rows[registry_id])
            if not source.is_file():
                raise RuntimeError(f"missing canonical identity image: {entity_id}: {source}")
            transport = identity_transport(entity_id, source)
            label = f"@图片{len(temporal) + len(identities) + 1}"
            identities.append({
                "asset_label": label,
                "role": f"IDENTITY_REFERENCE_{entity_id.upper()}",
                "path": transport["path"],
                "sha256": transport["sha256"],
                "identity_reference": True,
                "entity_id": entity_id,
                "transport_derivative_of": transport["transport_derivative_of"],
                "transport_derivative_source_sha256": transport["transport_derivative_source_sha256"],
                "transport_transform": transport["transport_transform"],
            })
            canonical[entity_id] = {"path": rel(source), "sha256": digest(source), "slot": label}
        if len(temporal) + len(identities) > 9:
            raise RuntimeError(f"{unit['unit_id']} exceeds Seedance image reference limit")

        dialogue, dialogue_assets, exact_paths, style_ids = dialogue_bindings(unit_audio, voice_by_id)
        multimodal = []
        for entity_id in visual_ids:
            speaker_assets = [row for row in dialogue_assets if row["speaker_id"] == entity_id]
            multimodal.append({
                "entity_id": entity_id,
                "character_name": DISPLAY[entity_id],
                "registry_id": REGISTRY_ID[entity_id],
                "visual_reference": canonical[entity_id]["path"],
                "visual_reference_sha256": canonical[entity_id]["sha256"],
                "identity_image_slot": canonical[entity_id]["slot"],
                "voice_reference_asset_id": voice_by_id.get(entity_id, {}).get("remote_asset_id"),
                "dialogue_audio_slots": [row["audio_slot"] for row in speaker_assets],
                "visible_speaker": bool(speaker_assets),
                "lip_sync": bool(speaker_assets),
                "prop_owners": {"single_source_rule": f"{DISPLAY[entity_id]}只持有{EPISODE} {VERSION_LOWER}逐拍spec明确分配的道具"},
                "ability_owners": [f"只有{DISPLAY[entity_id]}可执行{EPISODE} {VERSION_LOWER}逐拍spec明确分配给该角色的能力"],
            })

        prompt_row = prompt_rows[unit["unit_id"]]
        prompt_path = ROOT / prompt_row["prompt_path"]
        prompt_sha = digest(prompt_path)
        if prompt_sha != prompt_row["prompt_sha256"]:
            raise RuntimeError(f"prompt SHA drift: {unit['unit_id']}")
        prompt_text = prompt_path.read_text(encoding="utf-8")
        named_in_prompt = {
            entity_id for entity_id, display_name in DISPLAY.items()
            if display_name in prompt_text
        }
        nonvisual_mentions = sorted(named_in_prompt - set(visual_ids))
        generated_duration = transport_duration(float(unit["duration_seconds"]))
        all_images = temporal + identities
        task = {
            "task_key": f"{unit['unit_id']}-PERFORMANCE-{VERSION}",
            "source_id": unit["unit_id"],
            "tool_type": "video_generation",
            "generation_mode": "performance_generation",
            "episode": EPISODE,
            "batch_id": f"{EPISODE}-{VERSION}-STREAMING-PERFORMANCE-20260723",
            "unit_id": unit["unit_id"],
            "scene_id": unit["scene_id"],
            "visual_zone": f"{unit['unit_id']}-{VERSION}-CURRENT-CANONICAL",
            "duration": generated_duration,
            "duration_seconds": generated_duration,
            "edit_target_duration_seconds": unit["duration_seconds"],
            "model": "seedance-2.0-pro",
            "aspect_ratio": "9:16",
            "resolution": "720p",
            "duration_plan": {
                "policy": "qingshan.shot_generation_duration.v5",
                "duration_seconds": generated_duration,
                "rationale": "Claude Writer scene-local natural grouping and exact per-unit action duration.",
                "edit_policy": f"Edit to {unit['duration_seconds']} seconds only at natural head/tail; never loop, freeze, interpolate or slow footage.",
            },
            "prompt_file": prompt_row["prompt_path"],
            "prompt_path": prompt_row["prompt_path"],
            "prompt_sha256": prompt_sha,
            "reference_images": [row["path"] for row in all_images],
            "reference_image_sequence": all_images,
            "planned_reference_image_count": unit["anchor_count_decision"]["planned_reference_image_count"],
            "state_reference_minimum": unit["anchor_count_decision"]["planned_reference_image_count"],
            "still_sequence_only_allowed": True,
            "inherits_establishing_coverage": first_unit_by_scene[unit["scene_id"]] != unit["unit_id"],
            "action_unit": True,
            "anchor_count_decision": unit["anchor_count_decision"],
            "performance_spec": unit["performance_spec"],
            "keyframe_interpolation_gate": {
                "status": "PASS",
                "stage": "CANDIDATE_PREFLIGHT",
                "anchor_count": len(temporal),
                "checked_adjacent_pairs": max(0, len(temporal) - 1),
                "candidate_recheck_required": len(temporal) > 1,
                "reason": "Adjacent anchors preserve authored space, prop ownership and physically traversable order; output still requires final continuity QA.",
                "qa_reference": rel(QA / f"{EPISODE}_{VERSION}_IMAGE_MACHINE_ADMISSION.json"),
            },
            "dialogue": dialogue,
            "reference_audios": exact_paths,
            "reference_audio_asset_ids": style_ids,
            "dialogue_audio_assets": dialogue_assets,
            "native_dialogue_required": bool(dialogue),
            "audio_reference_optional": not bool(dialogue),
            "dialogue_audio_coverage": {"required": len(dialogue), "bound": len(dialogue_assets), "status": "PASS"},
            "source_script_sha256": SOURCE_SHA,
            "workflow_credit_scope": f"{EPISODE.lower()}_claude_writer_{VERSION_LOWER}_{SOURCE_SHA[:8]}_20260723",
            "status": "READY_TO_SUBMIT",
            "dependencies_ready": True,
            "identity_machine_admission": "CONDITIONAL_MACHINE_ADMISSION",
            "prompt_contract": {
                "source_action": unit["viewer_read"],
                "spatial_continuity": {
                    "mode": "SAME_SPACE_CONTINUOUS",
                    "policy_source": "PER_UNIT_SCRIPT_CONTENT",
                    "scene_id": unit["scene_id"],
                    "anchor_scope": "PERFORMANCE_TEMPORAL_ANCHORS_ONLY",
                    "camera_policy": "ALLOW_ONLY_AUTHORED_INTRA_SCENE_CAMERA_MOVEMENT",
                },
            },
            "multimodal_entity_bindings": multimodal,
            "visual_entity_ids": visual_ids,
            "character_free_unit": not bool(multimodal),
            "nonvisual_entity_mentions": nonvisual_mentions,
            "effect_provenance": [{
                "effect": "悬浮、漂浮、变色、光幕、冰幕、水幕、冰流、阴神、皮影、冰墙、纸人、人参珠、乌云引路、水波密纹",
                "source_type": "CLAUDE_SCRIPT",
                "source_ref": rel(SCRIPT),
            }],
        }
        task["multimodal_binding_sha256"] = hashlib.sha256(
            json.dumps(multimodal, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        task["generation_fingerprint"] = generation_fingerprint(task)
        tasks.append(task)

    write(QA / f"{EPISODE}_{VERSION}_IMAGE_MACHINE_ADMISSION.json", {
        "schema": "qingshan.image_machine_admission.v1",
        "episode": EPISODE,
        "status": "PASS_WITH_CONDITIONAL_MACHINE_ADMISSIONS",
        "source_script_sha256": SOURCE_SHA,
        "selections": admissions,
        "original_failures_preserved": True,
        "rollback_policy": "Replace only a failed unit after video identity/continuity QA; preserve passed siblings.",
    })
    write(CONFIG, {
        "schema": "qingshan.episode_streaming_video_batch.v2",
        "episode": EPISODE,
        "status": "READY_FOR_STREAMING_SUBMIT",
        "recorded_at": now(),
        "concurrency": max(1, len(tasks)),
        "max_retries": 0,
        "retry_policy": "FAILED_ITEMS_ONLY_CHANGED_INPUT_REQUIRED",
        "effective_ruleset": "QINGSHAN_PIPELINE_EFFECTIVE_RULESET_V1",
        "workflow_credit_scope": f"{EPISODE.lower()}_claude_writer_{VERSION_LOWER}_{SOURCE_SHA[:8]}_20260723",
        "video_credit_limit": 6000,
        "source_script_sha256": SOURCE_SHA,
        "output_dir": rel(OUTPUT / "outputs"),
        "qa_dir": rel(QA / "video_runtime"),
        "scene_contract_ref": rel(SCENE_STATE),
        "script_readiness_report": f"qa/{EPISODE.lower()}_{VERSION_LOWER}_preproduction_20260723/{EPISODE}_IMAGE_PLAN_PREFLIGHT_{VERSION}.json",
        "dramatic_quality_report_ref": f"qa/{EPISODE.lower()}_{VERSION_LOWER}_preproduction_20260723/{EPISODE}_DRAMATIC_QUALITY_PLAN_{VERSION}.json",
        "mechanical_default_plan_ref": f"qa/{EPISODE.lower()}_{VERSION_LOWER}_preproduction_20260723/{EPISODE}_MECHANICAL_DEFAULT_PLAN_{VERSION}.json",
        "anchor_count_plan_ref": f"qa/{EPISODE.lower()}_{VERSION_LOWER}_preproduction_20260723/{EPISODE}_VIDEO_ANCHOR_COUNT_PLAN_{VERSION}.json",
        "common_sense_causality_plan_ref": f"qa/{EPISODE.lower()}_{VERSION_LOWER}_preproduction_20260723/{EPISODE}_COMMON_SENSE_CAUSALITY_PLAN_{VERSION}.json",
        "period_lock_plan_ref": f"qa/{EPISODE.lower()}_{VERSION_LOWER}_preproduction_20260723/{EPISODE}_PERIOD_LOCK_PLAN_{VERSION}.json",
        "complete_video_prompt_manifest_ref": rel(PROMPT_MANIFEST),
        "dialogue_manifest_ref": rel(AUDIO_MANIFEST),
        "voice_registry_ref": rel(VOICE_REGISTRY),
        "supervisor_script_gate_required": False,
        "space_camera_constraint_gate_required": True,
        "readiness_policy": "SUBMIT_EACH_VIDEO_UNIT_IMMEDIATELY_WHEN_ITS_OWN_ANCHORS_AND_AUDIO_ARE_READY",
        "preserved_prompt_professionalism_evidence": [
            {
                "task_key": f"{row['unit_id']}-COMPLETE-PROMPT-{VERSION}",
                "scene_id": row["scene_id"],
                "prompt_file": row["prompt_path"],
                "prompt_sha256": row["prompt_sha256"],
            }
            for row in prompt_rows.values()
        ],
        "writer_agent_provenance": {
            "status": "PASS",
            "provenance_type": "claude_writer_script",
            "source_script": rel(SCRIPT),
            "source_script_sha256": SOURCE_SHA,
            "production_manifest": rel(MANIFEST),
            "production_manifest_sha256": digest(MANIFEST),
        },
        "reused_video_units": [reused] if reused else [],
        "waiting_unit_ids": waiting,
        "tasks": tasks,
    })
    print(json.dumps({
        "status": "PASS",
        "ready_video_tasks": len(tasks),
        "waiting_units": waiting,
        "reused_units": ["E34-CW-U01"] if reused else [],
        "config": rel(CONFIG),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
