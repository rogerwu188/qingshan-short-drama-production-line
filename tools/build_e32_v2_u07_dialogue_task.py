#!/usr/bin/env python3
"""Build E32 v2 U07 from the canonical prompt, still, and exact dialogue audio."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from episode_video_generation_guard import evaluate_episode_credit_gate, find_existing_paid_candidate, generation_fingerprint
from episode_parallel_batch_supervisor import (
    validate_complete_video_prompt_manifest,
    validate_dialogue_manifest_coverage,
    validate_duration_task,
    validate_entity_reference_task,
    validate_writer_agent_provenance,
)
from multimodal_character_binding_guard import binding_digest, evaluate_task as evaluate_binding
from scene_authority_lock import evaluate_batch as evaluate_scene_authority
from shot_prompt_professionalism_gate import evaluate_batch as evaluate_prompt_professionalism
from shot_space_camera_constraint_gate import evaluate_batch as evaluate_space_camera


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e32_claude_writer_v2_20260723"
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E32剧本_ClaudeWriter_v2.md"
MANIFEST = PROD / "E32_PRODUCTION_MANIFEST.json"
PLAN = PROD / "E32_VIDEO_UNIT_PERFORMANCE_PLAN_V2.json"
SCENE = PROD / "E32_SCENE_AUTHORITY_STATE_V2.json"
DIALOGUE_MANIFEST = ROOT / "working_assets/e32_dialogue_audio_refs_v2_20260723/E32_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V2.json"
BASE = PROD / "video_performance_v2"
COMPLETE_PROMPT_MANIFEST = BASE / "E32_ALL_17_VIDEO_PROMPT_MANIFEST_V2.json"
COMPILED_PROMPT = BASE / "prompts/E32-CW-U07-PERFORMANCE-V2-COMPILED.txt"
PROMPT = BASE / "prompts/E32-CW-U07-PERFORMANCE-V2.txt"
SPEC = BASE / "specs/E32-CW-U07-PERFORMANCE-SPEC-V2.json"
CONFIG = BASE / "E32_VIDEO_U07_EXACT_DIALOGUE_READY_V2.json"
PRECHECK = BASE / "qa/E32_VIDEO_U07_EXACT_DIALOGUE_PRECHECK_V2.json"
A1 = ROOT / "working_assets/e32_remake_v2_stills_20260723/candidates/E32-CW-U07-A1-STILL-V2_154eb586-9d3e-4a32-b568-0c9121cbce46.png"
CHENJI_IDENTITY = ROOT / "assets/reference/e10_20260709/characters/CHAR-chenji-young-apprentice-canonical-v2-20260709.jpg"
QISAN_IDENTITY = ROOT / "working_assets/e32_remake_v2_stills_20260723/candidates/E32-CW-U05-A1-STILL-V2_93e23a3a-87f4-43e5-8f19-c87ae983ee13.png"
PADDED_AUDIO_DIR = ROOT / "working_assets/e32_dialogue_audio_refs_v2_20260723/video_reference_wav"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def video_audio(row: dict) -> tuple[Path, float, str]:
    source = ROOT / row["path"]
    duration = float(row["duration_seconds"])
    if duration >= 2.0:
        return source, duration, "NONE"
    PADDED_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    target = PADDED_AUDIO_DIR / source.name
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        bundled = list((ROOT / ".agentcut_env").glob("lib/python*/site-packages/agentcut/vendor/darwin-arm64/ffmpeg"))
        ffmpeg = str(bundled[0]) if bundled else None
    if not ffmpeg:
        raise SystemExit("ffmpeg is required to pad a sub-2-second Seedance audio reference")
    subprocess.run(
        [ffmpeg, "-y", "-i", str(source), "-af", "apad=pad_dur=0.4", "-t", "2.15", "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(target)],
        check=True,
        capture_output=True,
    )
    return target, 2.15, "TRAILING_SILENCE_PADDING_TO_2_15S"


def main() -> int:
    required = (SCRIPT, MANIFEST, PLAN, SCENE, DIALOGUE_MANIFEST, COMPLETE_PROMPT_MANIFEST, COMPILED_PROMPT, A1, CHENJI_IDENTITY, QISAN_IDENTITY)
    for path in required:
        if not path.is_file():
            raise SystemExit(f"required input missing: {path}")

    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    unit = next(row for row in plan["units"] if row.get("unit_id") == "E32-CW-U07")
    if unit.get("planned_reference_image_count") != 1:
        raise SystemExit("U07 canonical design no longer authorizes one temporal anchor")

    prompt_manifest = json.loads(COMPLETE_PROMPT_MANIFEST.read_text(encoding="utf-8"))
    prompt_row = next(row for row in prompt_manifest["rows"] if row.get("unit_id") == "E32-CW-U07")
    if prompt_row.get("status") != "PROMPT_COMPILED" or prompt_row.get("blocked_exact_dialogue_audio_ids"):
        raise SystemExit("U07 canonical prompt is not ready for exact-dialogue submission")

    dialogue_manifest = json.loads(DIALOGUE_MANIFEST.read_text(encoding="utf-8"))
    dialogue_ids = prompt_row["dialogue_ids"]
    by_id = {row["dia_id"]: row for row in dialogue_manifest["rows"]}
    dialogues = [by_id[dia_id] for dia_id in dialogue_ids]
    if any(row.get("status") != "PASS" or row.get("audio_mode") != "EXACT_DIALOGUE_AUDIO_REFERENCE" for row in dialogues):
        raise SystemExit("U07 requires three PASS exact-line dialogue audio references")

    resolved_audio = [(row, *video_audio(row)) for row in dialogues]
    prompt_text = COMPILED_PROMPT.read_text(encoding="utf-8")
    PROMPT.write_text(prompt_text, encoding="utf-8")

    beats = [
        {"start_seconds": 0.0, "end_seconds": 3.3, "subject": "齐三与陈迹", "action": "齐三背抵案沿，双手摊开急切撇清，膝头因恐惧逐渐发软；陈迹站定不逼近", "contact_point": "齐三后腰与案沿、鞋底与地面", "direction": "齐三重心由脚掌向后移到案沿并缓慢下沉", "end_state": "齐三仍站立但膝头发软，陈迹保持原位", "intent": "观众看懂齐三开始供述而非继续逃跑", "visible_causality": "后腰抵住案沿限制退路，膝头随恐惧连续下沉而非瞬间跪地", "expression": "齐三赔笑转慌乱；陈迹目光不移", "viewer_read": "齐三开始撇清并准备供述"},
        {"start_seconds": 3.3, "end_seconds": 7.2, "subject": "齐三", "action": "右手颤抖抬起，越过三封信明确指向案角骨牌印，身体重心继续下沉", "contact_point": "右手指向与骨牌印的视线轴、后腰与案沿", "direction": "右手由胸前向案角前伸并停稳，重心竖直下沉", "end_state": "右指停在骨牌印上方不触碰，膝头接近地面", "intent": "观众听懂骨牌印属于巡检指挥席位", "visible_causality": "指向唯一骨牌印后才说出印的归属", "expression": "脸色煞白、孤注一掷", "viewer_read": "内鬼席位被指向巡检指挥"},
        {"start_seconds": 7.2, "end_seconds": 12.0, "subject": "齐三与陈迹", "action": "齐三膝头落地但双手仍可见，指尖从骨牌转向门外强调围令另有线路；陈迹只用眼神确认", "contact_point": "齐三双膝与地面、右指与门外方向的视线轴", "direction": "身体竖直落到跪姿，右指由案角转向门外", "end_state": "齐三跪稳并指向门外，陈迹冷静记下结论", "intent": "观众听懂围令不走云羊线", "visible_causality": "指向从印转到门外线路后才说出围令另线", "expression": "齐三声音发颤；陈迹冷静确认", "viewer_read": "围令来自越过云羊的另一条巡检线"},
    ]
    spec = {"schema": "qingshan.performance_generation_spec.v2", "episode": "E32", "unit_id": "E32-CW-U07", "duration_seconds": 12, "prop_ownership": {"三封信": "始终位于齐三身后的案面", "骨牌印": "始终位于案角，只被齐三指向，不被拿起"}, "motion_beats": beats}
    write_json(SPEC, spec)

    dialogue_assets = []
    for index, (row, path, duration, transform) in enumerate(resolved_audio, 1):
        dialogue_assets.append({"dia_id": row["dia_id"], "speaker": row["speaker"], "spoken_text": row["spoken_text"], "audio_slot": f"@音频{index}", "path": rel(path), "sha256": sha(path), "duration_seconds": duration, "purpose": "EXACT_TARGET_DIALOGUE_REFERENCE", "local_transform": transform, "source_voice": "AGENTCUT_SPEECH_GENERATION:clone_20251022_095814_035815", "voice_gender": "male", "voice_derivation_status": "PASS", "voice_reference_asset_id": "ubepnv100tm"})

    bindings = [
        {"entity_id": "chenji", "character_name": "陈迹", "registry_id": "CHAR-陈迹-古装", "visual_reference": rel(CHENJI_IDENTITY), "visual_reference_sha256": sha(CHENJI_IDENTITY), "identity_image_slot": "@图片2", "voice_reference_asset_id": "cypqud0bu7t", "dialogue_audio_slots": [], "visible_speaker": False, "lip_sync": False, "prop_owners": {}, "ability_owners": []},
        {"entity_id": "qisan", "character_name": "齐三", "registry_id": "CHAR-齐三-古装", "visual_reference": rel(QISAN_IDENTITY), "visual_reference_sha256": sha(QISAN_IDENTITY), "identity_image_slot": "@图片3", "voice_reference_asset_id": "ubepnv100tm", "dialogue_audio_slots": ["@音频1", "@音频2", "@音频3"], "visible_speaker": True, "lip_sync": True, "prop_owners": {"三封信": "齐三案面", "骨牌印": "齐三只指向不拿取"}, "ability_owners": []},
    ]
    task = {
        "task_key": "E32-CW-U07-PERFORMANCE-V2", "source_id": "E32-CW-U07", "tool_type": "video_generation", "generation_mode": "performance_generation", "episode": "E32", "batch_id": "E32-PERFORMANCE-V2", "unit_id": "E32-CW-U07", "scene_id": "E32-CW-S02", "visual_zone": "E32-CW-U07-DARK-TOWER-INTERROGATION", "duration": 12, "duration_seconds": 12, "model": "seedance-2.0-pro", "duration_plan": {"policy": "qingshan.shot_generation_duration.v5", "duration_seconds": 12, "rationale": "Claude v2 contiguous action plus measured exact dialogue and natural pauses.", "edit_policy": "End when Qisan finishes the third line and Chenji confirms; never pad, slow or loop."}, "aspect_ratio": "9:16", "resolution": "720p", "prompt_file": rel(PROMPT), "prompt_sha256": sha(PROMPT),
        "reference_images": [rel(A1), rel(CHENJI_IDENTITY), rel(QISAN_IDENTITY)],
        "reference_image_sequence": [
            {"asset_label": "@图片1", "role": "PERFORMANCE_START", "path": rel(A1), "sha256": sha(A1)},
            {"asset_label": "@图片2", "role": "IDENTITY_REFERENCE_CHENJI", "path": rel(CHENJI_IDENTITY), "sha256": sha(CHENJI_IDENTITY), "identity_reference": True},
            {"asset_label": "@图片3", "role": "IDENTITY_REFERENCE_QISAN", "path": rel(QISAN_IDENTITY), "sha256": sha(QISAN_IDENTITY), "identity_reference": True},
        ],
        "state_reference_minimum": 1, "planned_reference_image_count": 1, "still_sequence_only_allowed": True, "inherits_establishing_coverage": True, "action_unit": True, "performance_spec": spec, "keyframe_interpolation_gate": {"status": "PASS", "stage": "CANDIDATE_PREFLIGHT", "anchor_count": 1, "checked_adjacent_pairs": 0, "candidate_recheck_required": False, "reason": "One performance start anchor plus two non-temporal identity locks support the same-space interrogation."},
        "dialogue": [{"dia_id": row["dia_id"], "speaker": row["speaker"], "spoken_text": row["spoken_text"]} for row in dialogues], "reference_audios": [rel(path) for _, path, _, _ in resolved_audio], "dialogue_audio_assets": dialogue_assets, "native_dialogue_required": True, "audio_reference_optional": False, "dialogue_audio_coverage": {"required": 3, "bound": 3, "status": "PASS"}, "nonvisual_entity_mentions": ["yunyang"], "source_spec": rel(SPEC), "source_spec_sha256": sha(SPEC), "workflow_credit_scope": "e32_claude_writer_v2_20260723", "status": "READY_TO_SUBMIT", "prompt_contract": {"source_action": "齐三由撇清转为跪地供出巡检指挥印和另一条围令线路", "spatial_continuity": {"mode": "SAME_SPACE_CONTINUOUS", "policy_source": "PER_UNIT_SCRIPT_CONTENT", "scene_id": "E32-CW-S02-WEST-MARKET-DARK-TOWER", "anchor_scope": "ORIGIN_ONLY", "camera_policy": "ALLOW_AUTHORED_INTRA_SCENE_CAMERA_MOVEMENT"}}, "multimodal_entity_bindings": bindings, "multimodal_binding_sha256": binding_digest(bindings), "effect_provenance": [{"effect": "冰流", "source_type": "CANONICAL_ABILITY", "source_ref": "E32剧本_ClaudeWriter_v2.md#5-3"}],
    }
    task["generation_fingerprint"] = generation_fingerprint(task)
    config = {"schema": "qingshan.episode_parallel_batch.config.v1", "episode": "E32", "status": "READY_INCREMENTAL_UNITS", "recorded_at": datetime.now(timezone.utc).isoformat(), "targeted_unit_replacement": True, "concurrency": 1, "max_retries": 0, "retry_policy": "NO_AUTOMATIC_RETRY_WITH_UNCHANGED_INPUT", "workflow_credit_scope": "e32_claude_writer_v2_20260723", "video_credit_limit": 6000, "source_script_sha256": sha(SCRIPT), "dialogue_manifest_ref": rel(DIALOGUE_MANIFEST), "complete_video_prompt_manifest_ref": rel(COMPLETE_PROMPT_MANIFEST), "writer_agent_provenance": {"status": "PASS", "provenance_type": "claude_writer_script", "source_script": rel(SCRIPT), "source_script_sha256": sha(SCRIPT), "production_manifest": rel(MANIFEST), "production_manifest_sha256": sha(MANIFEST)}, "scene_contract_ref": rel(SCENE), "supervisor_script_gate_required": False, "space_camera_constraint_gate_required": True, "output_dir": rel(BASE / "outputs"), "qa_dir": rel(BASE / "qa"), "tasks": [task]}
    write_json(CONFIG, config)

    checks = {
        "complete_video_prompt_manifest": validate_complete_video_prompt_manifest(config),
        "dialogue_manifest_coverage": validate_dialogue_manifest_coverage(config),
        "prompt_professionalism": evaluate_prompt_professionalism(config),
        "space_camera_constraint": evaluate_space_camera(config["tasks"], {task["task_key"]: prompt_text}),
        "multimodal_character_binding": evaluate_binding(task),
        "scene_authority": evaluate_scene_authority(SCENE, config),
        "entity_reference_sequence": {"status": "PASS" if not (errors := validate_entity_reference_task(task)) else "FAIL", "failures": errors},
        "duration_policy": {"status": "PASS" if not (errors := validate_duration_task(task)) else "FAIL", "failures": errors},
        "generation_deduplication": {"status": "PASS" if (existing := find_existing_paid_candidate("E32", task)) is None else "FAIL", "existing_candidate": existing, "generation_fingerprint": task["generation_fingerprint"]},
        "current_workflow_credit_gate": evaluate_episode_credit_gate("E32", limit=6000),
    }
    writer_ok, writer_failures = validate_writer_agent_provenance(config)
    checks["writer_provenance"] = {"status": "PASS" if writer_ok else "FAIL", "failures": writer_failures}
    report = {"schema": "qingshan.e32_u07_exact_dialogue_video_precheck.v2", "episode": "E32", "unit_id": "E32-CW-U07", "status": "PASS" if all(row.get("status") == "PASS" for row in checks.values()) else "FAIL", "checks": checks, "config": rel(CONFIG), "recorded_at": datetime.now(timezone.utc).isoformat()}
    write_json(PRECHECK, report)
    print(json.dumps({"status": report["status"], "config": rel(CONFIG), "precheck": rel(PRECHECK), "generation_fingerprint": task["generation_fingerprint"]}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
