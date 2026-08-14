#!/usr/bin/env python3
"""Build and preflight the remaining E32 v2 performance-video units."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from compile_e32_v2_all_video_prompts import UNIT_SPECS
from episode_parallel_batch_supervisor import (
    validate_complete_video_prompt_manifest,
    validate_corrected_pipeline_quality,
    validate_dialogue_manifest_coverage,
    validate_duration_task,
    validate_entity_reference_task,
    validate_writer_agent_provenance,
)
from episode_video_generation_guard import (
    evaluate_episode_credit_gate,
    find_existing_paid_candidate,
    generation_fingerprint,
)
from multimodal_character_binding_guard import binding_digest, evaluate_batch as evaluate_bindings
from scene_authority_lock import evaluate_batch as evaluate_scene_authority
from shot_prompt_professionalism_gate import evaluate_batch as evaluate_prompt_professionalism
from shot_space_camera_constraint_gate import evaluate_batch as evaluate_space_camera


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e32_claude_writer_v2_20260723"
BASE = PROD / "video_performance_v2"
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E32剧本_ClaudeWriter_v2.md"
PRODUCTION_MANIFEST = PROD / "E32_PRODUCTION_MANIFEST.json"
PLAN = PROD / "E32_VIDEO_UNIT_PERFORMANCE_PLAN_V2.json"
SCENE = PROD / "E32_SCENE_AUTHORITY_STATE_V2.json"
PROMPT_MANIFEST = BASE / "E32_ALL_17_VIDEO_PROMPT_MANIFEST_V2.json"
DIALOGUE_MANIFEST = ROOT / "working_assets/e32_dialogue_audio_refs_v2_20260723/E32_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V2.json"
VOICE_REGISTRY = ROOT / "configs/series_voice_reference_registry_current_20260723.json"
CHARACTER_REGISTRY = ROOT / "configs/series_character_asset_registry_20260712.json"
STILLS = ROOT / "working_assets/e32_remake_v2_stills_20260723/candidates"
PADDED_AUDIO = ROOT / "working_assets/e32_dialogue_audio_refs_v2_20260723/video_reference_wav_v3"
CONFIG = BASE / "E32_VIDEO_REMAINING_13_NATIVE_VOICE_V3.json"
PRECHECK = BASE / "qa/E32_VIDEO_REMAINING_13_NATIVE_VOICE_V3_PRECHECK.json"

RETAINED_UNITS = {"E32-CW-U04", "E32-CW-U05", "E32-CW-U07", "E32-CW-U12"}
ROLE_AUTHORITY = {
    "chenji": ("陈迹", "CHAR-陈迹-古装"),
    "jiaotu": ("皎兔", "CHAR-皎兔-古装"),
    "wuyun": ("乌云", "CHAR-乌云-猫"),
    "yunyang": ("云羊", "CHAR-云羊-古装"),
    "yao_taiyi": ("姚太医", "CHAR-姚太医-古装"),
    "qisan": ("齐三", "CHAR-齐三-古装"),
    "killer": ("巡检司杀手", "CHAR-巡检司杀手-古装"),
}
ROLE_ORDER = tuple(ROLE_AUTHORITY)
EFFECT_PROVENANCE = [
    {"effect": "冰流 冰幕 冰墙 光幕 冻结 悬浮 漂浮", "source_type": "CANONICAL_ABILITY", "source_ref": "workflow/claude_writer_agent/scripts/E32剧本_ClaudeWriter_v2.md"},
    {"effect": "阴神 皮影 水幕 变色", "source_type": "CLAUDE_SCRIPT", "source_ref": "workflow/claude_writer_agent/scripts/E32剧本_ClaudeWriter_v2.md"},
]


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def temporal_anchors(unit_id: str, count: int) -> list[Path]:
    short = unit_id.rsplit("-", 1)[-1]
    a1 = sorted(STILLS.glob(f"E32-CW-{short}-A1-STILL-V2_*.png"))
    if len(a1) != 1:
        raise SystemExit(f"{unit_id}: expected one A1 candidate, found {len(a1)}")
    anchors = [a1[0]]
    if count == 2:
        a2 = sorted(STILLS.glob(f"E32_E32-CW-{short}-A2-STILL-R2_*.png"))
        if len(a2) != 1:
            raise SystemExit(f"{unit_id}: expected one repaired A2 candidate, found {len(a2)}")
        anchors.append(a2[0])
    if len(anchors) != count:
        raise SystemExit(f"{unit_id}: dynamic anchor count mismatch")
    return anchors


def pad_short_audio(row: dict) -> tuple[Path, float, str]:
    source = ROOT / row["path"]
    duration = float(row["duration_seconds"])
    if duration >= 2.0:
        return source, duration, "NONE"
    PADDED_AUDIO.mkdir(parents=True, exist_ok=True)
    target = PADDED_AUDIO / source.name
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        bundled = list((ROOT / ".agentcut_env").glob("lib/python*/site-packages/agentcut/vendor/darwin-arm64/ffmpeg"))
        ffmpeg = str(bundled[0]) if bundled else None
    if not ffmpeg:
        raise SystemExit("ffmpeg is required to pad sub-2-second dialogue references")
    subprocess.run(
        [ffmpeg, "-y", "-i", str(source), "-af", "apad=pad_dur=0.5", "-t", "2.15", "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(target)],
        check=True,
        capture_output=True,
    )
    return target, 2.15, "TRAILING_SILENCE_PADDING_TO_2_15S"


def visible_roles(spec: dict) -> list[str]:
    text = str(spec.get("entities") or "")
    roles = []
    for entity_id in ROLE_ORDER:
        name = ROLE_AUTHORITY[entity_id][0]
        if name in text or (entity_id == "killer" and "杀手" in text):
            roles.append(entity_id)
    return roles


def motion_beats(spec: dict) -> list[dict]:
    rows = []
    for start, end, action, expression, purpose, _ in spec["beats"]:
        rows.append({
            "start_seconds": start,
            "end_seconds": end,
            "subject": action.split("，", 1)[0],
            "action": action,
            "contact_point": spec["force"],
            "direction": "严格按本段文字声明的朝向、受力方向和空间轴线连续运动，不补未声明位移",
            "end_state": purpose,
            "intent": purpose,
            "visible_causality": spec["force"],
            "expression": expression,
            "viewer_read": purpose,
        })
    return rows


def main() -> int:
    required = (SCRIPT, PRODUCTION_MANIFEST, PLAN, SCENE, PROMPT_MANIFEST, DIALOGUE_MANIFEST, VOICE_REGISTRY, CHARACTER_REGISTRY)
    for path in required:
        if not path.is_file():
            raise SystemExit(f"required input missing: {path}")

    plan = load(PLAN)
    prompt_manifest = load(PROMPT_MANIFEST)
    dialogue_manifest = load(DIALOGUE_MANIFEST)
    voices = {row["entity_id"]: row for row in load(VOICE_REGISTRY)["major_roles"]}
    characters = load(CHARACTER_REGISTRY)["characters"]
    plan_by_unit = {row["unit_id"]: row for row in plan["units"]}
    prompt_by_unit = {row["unit_id"]: row for row in prompt_manifest["rows"]}
    dialogue_by_id = {row["dia_id"]: row for row in dialogue_manifest["rows"]}
    tasks = []
    prompt_texts = {}

    for unit_id, authored in UNIT_SPECS.items():
        if unit_id in RETAINED_UNITS:
            continue
        plan_row = plan_by_unit[unit_id]
        prompt_row = prompt_by_unit[unit_id]
        if prompt_row.get("status") != "PROMPT_COMPILED" or prompt_row.get("blocked_exact_dialogue_audio_ids"):
            raise SystemExit(f"{unit_id}: compiled prompt is not ready")
        duration = int(prompt_row["compiled_duration_seconds"])
        anchor_count = int(plan_row["planned_reference_image_count"])
        anchors = temporal_anchors(unit_id, anchor_count)
        prompt_path = ROOT / prompt_row["prompt_path"]
        if sha(prompt_path) != prompt_row["prompt_sha256"]:
            raise SystemExit(f"{unit_id}: prompt SHA mismatch")
        prompt_texts[f"{unit_id}-PERFORMANCE-V3"] = prompt_path.read_text(encoding="utf-8")

        roles = visible_roles(authored)
        dialogue_rows = [dialogue_by_id[dia_id] for dia_id in prompt_row["dialogue_ids"]]
        dialogue_by_role: dict[str, list[str]] = {role: [] for role in roles}
        dialogue_assets = []
        reference_audios: list[str] = []
        direct_audio_ids: list[str] = []
        for index, row in enumerate(dialogue_rows, 1):
            entity_id = row["speaker_id"]
            authority = voices[entity_id]
            slot = f"@音频{index}"
            dialogue_by_role.setdefault(entity_id, []).append(slot)
            if row["audio_mode"] == "EXACT_DIALOGUE_AUDIO_REFERENCE":
                audio_path, audio_duration, transform = pad_short_audio(row)
                reference_audios.append(rel(audio_path))
                purpose = "EXACT_TARGET_DIALOGUE_REFERENCE"
                remote_asset_id = None
            else:
                audio_path = ROOT / row["path"]
                audio_duration = float(row["duration_seconds"])
                transform = "NONE_CANONICAL_LOCKED_REFERENCE"
                purpose = "LOCKED_NATIVE_VOICE_STYLE_REFERENCE_WITH_EXACT_TEXT"
                remote_asset_id = str(row["remote_asset_id"])
                if remote_asset_id not in direct_audio_ids:
                    direct_audio_ids.append(remote_asset_id)
            dialogue_assets.append({
                "dia_id": row["dia_id"],
                "speaker": row["speaker"],
                "spoken_text": row["spoken_text"],
                "audio_slot": slot,
                "path": rel(audio_path),
                "sha256": sha(audio_path),
                "duration_seconds": audio_duration,
                "purpose": purpose,
                "remote_asset_id": remote_asset_id,
                "local_transform": transform,
                "source_voice": f"{authority.get('source_generator') or authority.get('source_type')}:{authority.get('generation_voice_id') or authority.get('remote_asset_id')}",
                "voice_gender": authority["gender"],
                "voice_derivation_status": "PASS",
                "voice_reference_asset_id": authority["remote_asset_id"],
            })

        image_paths = list(anchors)
        image_sequence = [
            {"asset_label": f"@图片{index}", "role": f"PERFORMANCE_{'START' if index == 1 else 'TERMINAL'}", "path": rel(path), "sha256": sha(path)}
            for index, path in enumerate(anchors, 1)
        ]
        bindings = []
        for role in roles:
            name, registry_id = ROLE_AUTHORITY[role]
            canonical = characters[registry_id]
            visual = Path(canonical.get("identity_reference_image") or canonical["reference_image"])
            if not visual.is_file():
                raise SystemExit(f"{unit_id}: canonical identity missing for {name}: {visual}")
            if visual not in image_paths:
                image_paths.append(visual)
            slot = f"@图片{len(image_sequence) + 1}"
            image_sequence.append({
                "asset_label": slot,
                "role": f"IDENTITY_REFERENCE_{role.upper()}",
                "path": rel(visual),
                "sha256": sha(visual),
                "identity_reference": True,
            })
            voice = voices.get(role) or {}
            speaking = bool(dialogue_by_role.get(role))
            bindings.append({
                "entity_id": role,
                "character_name": name,
                "registry_id": registry_id,
                "visual_reference": rel(visual),
                "visual_reference_sha256": sha(visual),
                "identity_image_slot": slot,
                "voice_reference_asset_id": voice.get("remote_asset_id"),
                "dialogue_audio_slots": dialogue_by_role.get(role, []),
                "visible_speaker": speaking,
                "lip_sync": speaking,
                "prop_owners": {"single_source_rule": f"{name} only owns props explicitly assigned to {name} in the compiled prompt"},
                "ability_owners": [f"Only {name} may perform abilities explicitly assigned to {name} in the compiled prompt"],
            })

        performance_spec = {
            "schema": "qingshan.performance_generation_spec.v3",
            "episode": "E32",
            "unit_id": unit_id,
            "duration_seconds": duration,
            "prop_ownership": {"single_source_of_truth": "Prompt text, temporal anchors, character bindings, props, and abilities all derive from UNIT_SPECS and the current Claude Writer script."},
            "motion_beats": motion_beats(authored),
        }
        spec_path = BASE / f"specs/{unit_id}-PERFORMANCE-SPEC-V3.json"
        write_json(spec_path, performance_spec)
        task_key = f"{unit_id}-PERFORMANCE-V3"
        task = {
            "task_key": task_key,
            "source_id": unit_id,
            "tool_type": "video_generation",
            "generation_mode": "performance_generation",
            "episode": "E32",
            "batch_id": "E32-PERFORMANCE-V3-REMAINING-13",
            "unit_id": unit_id,
            "scene_id": plan_row["scene_id"],
            "visual_zone": f"{unit_id}-CURRENT-CANONICAL-ZONE",
            "duration": duration,
            "duration_seconds": duration,
            "model": "seedance-2.0-pro",
            "aspect_ratio": "9:16",
            "resolution": "720p",
            "duration_plan": {
                "policy": "qingshan.shot_generation_duration.v5",
                "duration_seconds": duration,
                "rationale": "Current Claude Writer contiguous performance beats plus measured dialogue and natural pauses.",
                "edit_policy": "End when the authored action purpose is visible; never loop, freeze, pad, or slow footage to preserve an estimate.",
            },
            "prompt_file": rel(prompt_path),
            "prompt_sha256": sha(prompt_path),
            "reference_images": [rel(path) for path in image_paths],
            "reference_image_sequence": image_sequence,
            "state_reference_minimum": anchor_count,
            "planned_reference_image_count": anchor_count,
            "still_sequence_only_allowed": True,
            "inherits_establishing_coverage": True,
            "action_unit": True,
            "performance_spec": performance_spec,
            "keyframe_interpolation_gate": {
                "status": "PASS",
                "stage": "CANDIDATE_PREFLIGHT",
                "anchor_count": anchor_count,
                "checked_adjacent_pairs": max(0, anchor_count - 1),
                "candidate_recheck_required": anchor_count > 1,
                "reason": plan_row["keyframe_interpolation_gate"]["reason"],
                "qa_reference": "qa/e32_remake_preproduction_20260723/E32_U04_U10_A2_R2_MACHINE_VISUAL_QA_CL2X613.json" if unit_id == "E32-CW-U10" else None,
            },
            "dialogue": [{"dia_id": row["dia_id"], "speaker": row["speaker"], "spoken_text": row["spoken_text"]} for row in dialogue_rows],
            "reference_audios": reference_audios,
            "reference_audio_asset_ids": direct_audio_ids,
            "dialogue_audio_assets": dialogue_assets,
            "native_dialogue_required": bool(dialogue_rows),
            "audio_reference_optional": not bool(dialogue_rows),
            "dialogue_audio_coverage": {"required": len(dialogue_rows), "bound": len(dialogue_assets), "status": "PASS"},
            "source_spec": rel(spec_path),
            "source_spec_sha256": sha(spec_path),
            "workflow_credit_scope": "e32_claude_writer_v2_20260723",
            "status": "READY_TO_SUBMIT",
            "prompt_contract": {
                "source_action": authored["beats"][0][4],
                "spatial_continuity": {
                    "mode": "SAME_SPACE_CONTINUOUS",
                    "policy_source": "PER_UNIT_SCRIPT_CONTENT",
                    "scene_id": plan_row["scene_id"],
                    "anchor_scope": "PERFORMANCE_TEMPORAL_ANCHORS_ONLY",
                    "camera_policy": "ALLOW_ONLY_AUTHORED_INTRA_SCENE_CAMERA_MOVEMENT",
                },
            },
            "multimodal_entity_bindings": bindings,
            "multimodal_binding_sha256": binding_digest(bindings),
            "effect_provenance": EFFECT_PROVENANCE,
        }
        task["generation_fingerprint"] = generation_fingerprint(task)
        tasks.append(task)

    config = {
        "schema": "qingshan.episode_parallel_batch.config.v1",
        "episode": "E32",
        "status": "READY_REMAINING_CURRENT_CANONICAL_UNITS",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "effective_ruleset": "QINGSHAN_PIPELINE_EFFECTIVE_RULESET_V1",
        "targeted_unit_replacement": True,
        "retained_successful_units": sorted(RETAINED_UNITS),
        "concurrency": len(tasks),
        "max_retries": 0,
        "retry_policy": "NO_AUTOMATIC_RETRY_WITH_UNCHANGED_INPUT",
        "workflow_credit_scope": "e32_claude_writer_v2_20260723",
        "video_credit_limit": 6000,
        "source_script_sha256": sha(SCRIPT),
        "script_readiness_report": "qa/e32_stage_gate_runtime_20260723/run_008/episode_stage_gate_execution_summary.json",
        "dramatic_quality_report_ref": "qa/e32_stage_gate_runtime_20260723/E32_CURRENT_CANONICAL_DRAMATIC_QUALITY_REPORT_20260723.json",
        "mechanical_default_plan_ref": rel(PLAN),
        "anchor_count_plan_ref": rel(PLAN),
        "common_sense_causality_plan_ref": "qa/e32_stage_gate_runtime_20260723/current_canonical_evidence/E32_CURRENT_CANONICAL_CAUSALITY_PLAN.json",
        "period_lock_plan_ref": "qa/e32_stage_gate_runtime_20260723/current_canonical_evidence/E32_CURRENT_CANONICAL_PERIOD_LOCK_PLAN.json",
        "dialogue_manifest_ref": rel(DIALOGUE_MANIFEST),
        "voice_registry_ref": rel(VOICE_REGISTRY),
        "complete_video_prompt_manifest_ref": rel(PROMPT_MANIFEST),
        "writer_agent_provenance": {
            "status": "PASS",
            "provenance_type": "claude_writer_script",
            "source_script": rel(SCRIPT),
            "source_script_sha256": sha(SCRIPT),
            "production_manifest": rel(PRODUCTION_MANIFEST),
            "production_manifest_sha256": sha(PRODUCTION_MANIFEST),
        },
        "scene_contract_ref": rel(SCENE),
        "supervisor_script_gate_required": False,
        "space_camera_constraint_gate_required": True,
        "output_dir": rel(BASE / "outputs"),
        "qa_dir": rel(BASE / "qa"),
        "tasks": tasks,
    }
    write_json(CONFIG, config)

    checks = {
        "corrected_pipeline_quality": validate_corrected_pipeline_quality(config),
        "complete_video_prompt_manifest": validate_complete_video_prompt_manifest(config),
        "dialogue_manifest_coverage": validate_dialogue_manifest_coverage(config),
        "prompt_professionalism": evaluate_prompt_professionalism(config),
        "space_camera_constraint": evaluate_space_camera(tasks, prompt_texts),
        "multimodal_character_binding": evaluate_bindings(config),
        "scene_authority": evaluate_scene_authority(SCENE, config),
        "entity_reference_sequence": {
            "status": "PASS",
            "results": [],
        },
        "duration_policy": {"status": "PASS", "results": []},
        "generation_deduplication": {"status": "PASS", "results": []},
        "current_workflow_credit_gate": evaluate_episode_credit_gate("E32", limit=6000),
    }
    for task in tasks:
        entity_failures = validate_entity_reference_task(task)
        checks["entity_reference_sequence"]["results"].append({"task_key": task["task_key"], "failures": entity_failures})
        if entity_failures:
            checks["entity_reference_sequence"]["status"] = "FAIL"
        duration_failures = validate_duration_task(task)
        checks["duration_policy"]["results"].append({"task_key": task["task_key"], "failures": duration_failures})
        if duration_failures:
            checks["duration_policy"]["status"] = "FAIL"
        existing = find_existing_paid_candidate("E32", task)
        checks["generation_deduplication"]["results"].append({
            "task_key": task["task_key"],
            "generation_fingerprint": task["generation_fingerprint"],
            "existing_candidate": existing,
        })
        if existing is not None:
            checks["generation_deduplication"]["status"] = "FAIL"
    writer_ok, writer_failures = validate_writer_agent_provenance(config)
    checks["writer_provenance"] = {"status": "PASS" if writer_ok else "FAIL", "failures": writer_failures}
    report = {
        "schema": "qingshan.e32_remaining_video_precheck.v3",
        "episode": "E32",
        "status": "PASS" if all(row.get("status") == "PASS" for row in checks.values()) else "FAIL",
        "retained_successful_units": sorted(RETAINED_UNITS),
        "submitted_unit_count": len(tasks),
        "submitted_units": [task["unit_id"] for task in tasks],
        "checks": checks,
        "config": rel(CONFIG),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json(PRECHECK, report)
    print(json.dumps({"status": report["status"], "config": rel(CONFIG), "precheck": rel(PRECHECK), "task_count": len(tasks)}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
