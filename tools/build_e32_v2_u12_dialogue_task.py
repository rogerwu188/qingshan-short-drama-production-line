#!/usr/bin/env python3
"""Build E32 v2 U12 from its canonical prompt, still, identities, and exact dialogue."""

from __future__ import annotations

import hashlib
import json
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
COMPILED_PROMPT = BASE / "prompts/E32-CW-U12-PERFORMANCE-V2-COMPILED.txt"
PROMPT = BASE / "prompts/E32-CW-U12-PERFORMANCE-V2.txt"
SPEC = BASE / "specs/E32-CW-U12-PERFORMANCE-SPEC-V2.json"
CONFIG = BASE / "E32_VIDEO_U12_EXACT_DIALOGUE_READY_V2.json"
PRECHECK = BASE / "qa/E32_VIDEO_U12_EXACT_DIALOGUE_PRECHECK_V2.json"
A1 = ROOT / "working_assets/e32_remake_v2_stills_20260723/candidates/E32-CW-U12-A1-STILL-V2_c20adc83-fe69-4c4d-9d50-5f70f055bbe9.png"
CHENJI_IDENTITY = ROOT / "assets/reference/e10_20260709/characters/CHAR-chenji-young-apprentice-canonical-v2-20260709.jpg"
YAO_IDENTITY = ROOT / "assets/reference/e08_api_fallback_20260709/characters/CHAR-yao-taiyi-card-clean-20260709.jpg"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    required = (SCRIPT, MANIFEST, PLAN, SCENE, DIALOGUE_MANIFEST, COMPLETE_PROMPT_MANIFEST, COMPILED_PROMPT, A1, CHENJI_IDENTITY, YAO_IDENTITY)
    for path in required:
        if not path.is_file():
            raise SystemExit(f"required input missing: {path}")

    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    unit = next(row for row in plan["units"] if row.get("unit_id") == "E32-CW-U12")
    if unit.get("planned_reference_image_count") != 1:
        raise SystemExit("U12 canonical design no longer authorizes one temporal anchor")

    prompt_manifest = json.loads(COMPLETE_PROMPT_MANIFEST.read_text(encoding="utf-8"))
    prompt_row = next(row for row in prompt_manifest["rows"] if row.get("unit_id") == "E32-CW-U12")
    if prompt_row.get("status") != "PROMPT_COMPILED" or prompt_row.get("blocked_exact_dialogue_audio_ids"):
        raise SystemExit("U12 canonical prompt is not ready for exact-dialogue submission")

    dialogue_manifest = json.loads(DIALOGUE_MANIFEST.read_text(encoding="utf-8"))
    by_id = {row["dia_id"]: row for row in dialogue_manifest["rows"]}
    dialogues = [by_id[dia_id] for dia_id in prompt_row["dialogue_ids"]]
    if len(dialogues) != 2 or any(row.get("status") != "PASS" or row.get("audio_mode") != "EXACT_DIALOGUE_AUDIO_REFERENCE" for row in dialogues):
        raise SystemExit("U12 requires two PASS exact-line dialogue audio references")

    prompt_text = COMPILED_PROMPT.read_text(encoding="utf-8")
    PROMPT.write_text(prompt_text, encoding="utf-8")

    beats = [
        {"start_seconds": 0.0, "end_seconds": 3.0, "subject": "姚太医与陈迹", "action": "姚太医把验过的骨牌印放回案面，食指停在印记旁；陈迹站在案侧不触碰证物", "contact_point": "姚太医指腹与案面、骨牌印底面与案面", "direction": "骨牌印竖直落回案面，姚太医食指由印面移到旁侧", "end_state": "骨牌印静止在案面，姚太医抬眼看向陈迹", "intent": "观众先看懂杀牙人是为了逼出这枚印", "visible_causality": "姚太医完成验印后才给出第一句判断", "expression": "姚太医沉稳严肃；陈迹冷静凝神", "viewer_read": "敌人用牙人之死诱导骨牌印现身"},
        {"start_seconds": 3.0, "end_seconds": 7.0, "subject": "姚太医", "action": "姚太医说出第一句后，用食指从骨牌印沿案面划出一条短线，再停在陈迹面前，强调诱导路径", "contact_point": "姚太医食指与案面", "direction": "指尖由骨牌印向陈迹方向平直移动后停住", "end_state": "指尖停在短线末端，视线锁住陈迹", "intent": "把诱敌目的转成清楚可见的推理路径", "visible_causality": "指尖轨迹连接骨牌印与陈迹，动作目的与台词一致", "expression": "姚太医眼神锐利、语速克制；陈迹眉眼微沉", "viewer_read": "这不是灭口，而是试探陈迹会不会追查"},
        {"start_seconds": 7.0, "end_seconds": 12.0, "subject": "姚太医与陈迹", "action": "姚太医收回手，身体微微前倾说出第二句；陈迹听到内鬼时视线落向骨牌印，听到还有工夫查时再抬眼与姚太医对视", "contact_point": "姚太医双手收回身前、陈迹视线与骨牌印及姚太医形成连续轴线", "direction": "姚太医上身向前数厘米后停稳，陈迹视线由案面抬向对方", "end_state": "两人隔案对视，骨牌印仍在案面无人触碰", "intent": "观众理解敌人真正害怕的是陈迹拥有继续调查的时间", "visible_causality": "陈迹的两段视线反应分别对应内鬼和调查时间两个信息点", "expression": "姚太医忧惧压在平静表面；陈迹由警觉转为决断", "viewer_read": "敌人的核心恐惧是陈迹还能继续追查"},
    ]
    spec = {"schema": "qingshan.performance_generation_spec.v2", "episode": "E32", "unit_id": "E32-CW-U12", "duration_seconds": 12, "prop_ownership": {"骨牌印": "始终位于医馆前堂案面，只由姚太医放回并指向"}, "motion_beats": beats}
    write_json(SPEC, spec)

    dialogue_assets = []
    for index, row in enumerate(dialogues, 1):
        path = ROOT / row["path"]
        dialogue_assets.append({"dia_id": row["dia_id"], "speaker": row["speaker"], "spoken_text": row["spoken_text"], "audio_slot": f"@音频{index}", "path": rel(path), "sha256": sha(path), "duration_seconds": float(row["duration_seconds"]), "purpose": "EXACT_TARGET_DIALOGUE_REFERENCE", "local_transform": "NONE", "source_voice": "AGENTCUT_SPEECH_GENERATION:clone_20251023_071601_594968", "voice_gender": "male", "voice_derivation_status": "PASS", "voice_reference_asset_id": "v9ob3saa0i"})

    bindings = [
        {"entity_id": "chenji", "character_name": "陈迹", "registry_id": "CHAR-陈迹-古装", "visual_reference": rel(CHENJI_IDENTITY), "visual_reference_sha256": sha(CHENJI_IDENTITY), "identity_image_slot": "@图片2", "voice_reference_asset_id": "cypqud0bu7t", "dialogue_audio_slots": [], "visible_speaker": False, "lip_sync": False, "prop_owners": {}, "ability_owners": []},
        {"entity_id": "yao_taiyi", "character_name": "姚太医", "registry_id": "CHAR-姚太医-古装", "visual_reference": rel(YAO_IDENTITY), "visual_reference_sha256": sha(YAO_IDENTITY), "identity_image_slot": "@图片3", "voice_reference_asset_id": "v9ob3saa0i", "dialogue_audio_slots": ["@音频1", "@音频2"], "visible_speaker": True, "lip_sync": True, "prop_owners": {"骨牌印": "姚太医放回案面后只指向"}, "ability_owners": []},
    ]
    task = {
        "task_key": "E32-CW-U12-PERFORMANCE-V2", "source_id": "E32-CW-U12", "tool_type": "video_generation", "generation_mode": "performance_generation", "episode": "E32", "batch_id": "E32-PERFORMANCE-V2", "unit_id": "E32-CW-U12", "scene_id": "E32-CW-S04", "visual_zone": "E32-CW-U12-CLINIC-FRONT-HALL-ANALYSIS", "duration": 12, "duration_seconds": 12, "model": "seedance-2.0-pro", "duration_plan": {"policy": "qingshan.shot_generation_duration.v5", "duration_seconds": 12, "rationale": "Claude v2 same-space analysis with two measured exact dialogue lines and visible reaction beats.", "edit_policy": "End on Chenji and Yao holding eye contact; never pad, slow or loop."}, "aspect_ratio": "9:16", "resolution": "720p", "prompt_file": rel(PROMPT), "prompt_sha256": sha(PROMPT),
        "reference_images": [rel(A1), rel(CHENJI_IDENTITY), rel(YAO_IDENTITY)],
        "reference_image_sequence": [
            {"asset_label": "@图片1", "role": "PERFORMANCE_START", "path": rel(A1), "sha256": sha(A1)},
            {"asset_label": "@图片2", "role": "IDENTITY_REFERENCE_CHENJI", "path": rel(CHENJI_IDENTITY), "sha256": sha(CHENJI_IDENTITY), "identity_reference": True},
            {"asset_label": "@图片3", "role": "IDENTITY_REFERENCE_YAO", "path": rel(YAO_IDENTITY), "sha256": sha(YAO_IDENTITY), "identity_reference": True},
        ],
        "state_reference_minimum": 1, "planned_reference_image_count": 1, "still_sequence_only_allowed": True, "inherits_establishing_coverage": True, "action_unit": False, "performance_spec": spec, "keyframe_interpolation_gate": {"status": "PASS", "stage": "CANDIDATE_PREFLIGHT", "anchor_count": 1, "checked_adjacent_pairs": 0, "candidate_recheck_required": False, "reason": "One performance start anchor plus two non-temporal identity locks support the same-space dialogue analysis."},
        "dialogue": [{"dia_id": row["dia_id"], "speaker": row["speaker"], "spoken_text": row["spoken_text"]} for row in dialogues], "reference_audios": [row["path"] for row in dialogue_assets], "dialogue_audio_assets": dialogue_assets, "native_dialogue_required": True, "audio_reference_optional": False, "dialogue_audio_coverage": {"required": 2, "bound": 2, "status": "PASS"}, "nonvisual_entity_mentions": ["qisan"], "source_spec": rel(SPEC), "source_spec_sha256": sha(SPEC), "workflow_credit_scope": "e32_claude_writer_v2_20260723", "status": "READY_TO_SUBMIT", "prompt_contract": {"source_action": "姚太医验印后指出敌人真正害怕陈迹仍有时间追查内鬼", "spatial_continuity": {"mode": "SAME_SPACE_CONTINUOUS", "policy_source": "PER_UNIT_SCRIPT_CONTENT", "scene_id": "E32-CW-S04-CLINIC-FRONT-HALL", "anchor_scope": "ORIGIN_ONLY", "camera_policy": "ALLOW_AUTHORED_INTRA_SCENE_CAMERA_MOVEMENT"}}, "multimodal_entity_bindings": bindings, "multimodal_binding_sha256": binding_digest(bindings), "effect_provenance": [],
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
    report = {"schema": "qingshan.e32_u12_exact_dialogue_video_precheck.v2", "episode": "E32", "unit_id": "E32-CW-U12", "status": "PASS" if all(row.get("status") == "PASS" for row in checks.values()) else "FAIL", "checks": checks, "config": rel(CONFIG), "recorded_at": datetime.now(timezone.utc).isoformat()}
    write_json(PRECHECK, report)
    print(json.dumps({"status": report["status"], "config": rel(CONFIG), "precheck": rel(PRECHECK), "generation_fingerprint": task["generation_fingerprint"]}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
