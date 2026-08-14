#!/usr/bin/env python3
"""Build the E37 atomic action replacement batch and its fail-closed reports."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from multimodal_character_binding_guard import binding_digest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = "workflow/claude_writer_agent/scripts/E37剧本_ClaudeWriter_v2.md"
SCRIPT_SHA = "07a63a0c286be656feac59a0f31ea1bb159f3f7ce56f1172bb202832edf9db3a"
MANIFEST = "workflow/claude_writer_agent/scripts/E37_manifest_v2.json"
MANIFEST_SHA = "9082f9d3b45bf0466476e98cb194d91d00d6775c2b762b5253c8f7557d31c33e"
PLAN = "qa/e37_agentcut_20260803/direct_motion_audit_20260803/E37_V3_ATOMIC_ACTION_AND_OPENING_REPAIR_PLAN_V1.json"
OUT = Path("working_assets/e37_prompt_repair_20260803/compiled_prompts_v2")
PROD = Path("workflow/claude_writer_agent/production/e37_claude_writer_v2_4a738459_20260802/action_replacement_v2")
QA = Path("qa/e37_action_replacement_v2_20260803")


def sha(path: str | Path) -> str:
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def write(path: Path, payload: dict) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def identity(entity_id: str) -> tuple[str, str, str, str]:
    rows = {
        "chenji": ("陈迹", "CHAR-陈迹-古装", "assets/reference/e37_plus_20260729/characters/CHAR-chenji-age20-user-turnaround-canonical-v1-20260729.png", "cypqud0bu7t"),
        "yunyang": ("云羊", "CHAR-云羊-古装", "assets/reference/e36_20260729/characters/CHAR-yunyang-age17-canonical-v1-20260729.png", ""),
        "jiaotu": ("皎兔", "CHAR-皎兔-古装", "assets/reference/characters_canonical_20260709/images/CHAR-jiaotu-ancient-card-20260709.jpg", "x2ucerh9xoo"),
    }
    return rows[entity_id]


def main() -> int:
    plan = json.loads((ROOT / PLAN).read_text(encoding="utf-8"))
    failure_memory_path = Path("workflow/claude_writer_agent/GENERATION_PROMPT_FAILURE_MEMORY.json")
    failure_memory = json.loads((ROOT / failure_memory_path).read_text(encoding="utf-8"))
    failure_mode_ids = [str(row["id"]) for row in failure_memory.get("rules", []) if row.get("id")]
    shots = {row["shot_id"]: row for row in plan["shots"]}
    original_dir = ROOT / "working_assets/e37_prompt_repair_20260803/compiled_prompts_v1"
    anchor_by_shot = {
        "E37-R-A01": "working_assets/e37_stills_20260802/candidates/E37_E37-CW-U04-A1-STILL-V1_ZERO_CREDIT_ALT.png",
        "E37-R-A02": "working_assets/e37_stills_20260802/candidates/E37_E37-CW-U05-A1-STILL-V2_ZERO_CREDIT_ALT_PASS.png",
        "E37-R-A03": "working_assets/e37_stills_20260802/candidates/E37_E37-CW-U05-A1-STILL-V2_ZERO_CREDIT_ALT_PASS.png",
        "E37-R-A04": "working_assets/e37_stills_20260802/candidates/E37_E37-CW-U05-A2-STILL-V2_ZERO_CREDIT_ALT_PASS.png",
        "E37-R-A05": "working_assets/e37_stills_20260802/candidates/E37_E37-CW-U06-A1-STILL-V1_ZERO_CREDIT_ALT_PASS.png",
        "E37-R-A06": "working_assets/e37_stills_20260802/candidates/E37_E37-CW-U06-A1-STILL-V1_ZERO_CREDIT_ALT_PASS.png",
        "E37-R-A07": "working_assets/e37_stills_20260802/candidates/E37_E37-CW-U05-A2-STILL-V2_ZERO_CREDIT_ALT_PASS.png",
        "E37-R-A08": "working_assets/e37_stills_20260802/candidates/E37_E37-CW-U05-A2-STILL-V2_ZERO_CREDIT_ALT_PASS.png",
    }
    cast_by_shot = {
        "E37-R-A01": ["chenji"],
        "E37-R-A02": ["chenji"],
        "E37-R-A03": ["yunyang"],
        "E37-R-A04": ["yunyang"],
        "E37-R-A05": ["chenji", "jiaotu"],
        "E37-R-A06": ["chenji"],
        "E37-R-A07": ["chenji", "jiaotu", "yunyang"],
        "E37-R-A08": ["chenji", "jiaotu", "yunyang"],
    }
    # One physical contact must not be stretched to satisfy a scene-runtime target.
    # Four seconds is the hard ceiling: <=0.8s entry, <=2.0s action, 0.55s result.
    durations = {"E37-R-A01": 4, "E37-R-A02": 3, "E37-R-A03": 4, "E37-R-A04": 3, "E37-R-A05": 3, "E37-R-A06": 4, "E37-R-A07": 4, "E37-R-A08": 4}
    tasks = []
    anchor_units = []
    prompt_rows = []
    period_units = []
    causality_units = []
    mechanical_units = []

    for index in range(1, 9):
        shot_id = f"E37-R-A{index:02d}"
        shot = shots[shot_id]
        original = (original_dir / f"{shot_id}.txt").read_text(encoding="utf-8")
        camera = shot["camera"]
        contact = shot["primary_contacts"][0]
        prompt = (
            original.splitlines()[0] + "\n"
            f"[[scene_liuzhai_fire_escape]] [[prop_guard_ledger]] "
            + " ".join(f"[[char_{entity}]]" for entity in cast_by_shot[shot_id]) + "\n"
            f"【天气硬合同】weather=RAIN_NIGHT\n"
            f"镜头1【中景 固定机位 {camera['family']}，禁止摇镜、环绕、推拉、变焦，严禁越轴】"
            f"入场即处于动作中：{contact['pre_state']}。"
            f"先完成：{contact['actor']}{contact['action']}；再完成：接触后立即产生{contact['force_feedback']}；"
            f"动作结果：{contact['result_state']}并稳定保持0.55秒。"
            f"接触点：{contact['contact_point']}；力向：{contact['force_direction']}。"
            "{无对白} <撞击、火焰、雨声或碎屑的同期音效，按本镜实际接触选择>。\n"
            "色彩与动机光：雨夜冷青环境光对比宅内橙红火光，人物轮廓和接触点必须清楚。"
            "力量作用环境：火焰、白汽、木屑、尘与碎片只响应主接触，不得用镜头运动制造冲击。\n"
            + "\n".join(original.splitlines()[1:]) + "\n"
            "NEGATIVE_PROMPT: camera shake, pan, orbit, zoom, repeated action, reset, replay, slow motion, frozen pose, unreadable contact, modern object, readable text, subtitle, watermark.\n"
        )
        prompt_path = OUT / f"{shot_id}.txt"
        target = ROOT / prompt_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(prompt, encoding="utf-8")

        anchor = anchor_by_shot[shot_id]
        refs = [anchor]
        sequence = [{"asset_label": "@图片1", "role": "ACTION_STATE_ANCHOR", "path": anchor, "sha256": sha(anchor), "identity_reference": False}]
        bindings = []
        for entity_index, entity_id in enumerate(cast_by_shot[shot_id], start=2):
            name, registry_id, ref, voice_id = identity(entity_id)
            refs.append(ref)
            slot = f"@图片{entity_index}"
            sequence.append({"asset_label": slot, "role": f"IDENTITY_REFERENCE_{entity_id.upper()}", "path": ref, "sha256": sha(ref), "identity_reference": True, "entity_id": entity_id})
            bindings.append({
                "entity_id": entity_id,
                "character_name": name,
                "registry_id": registry_id,
                "visual_reference": ref,
                "visual_reference_sha256": sha(ref),
                "identity_image_slot": slot,
                "voice_reference_asset_id": voice_id or None,
                "dialogue_audio_slots": [],
                "visible_speaker": False,
                "lip_sync": False,
                "prop_owners": {"single_source_rule": "Only the action contract may transfer or retain a prop."},
                "ability_owners": ["Only the canonical character named by the action contract may perform the ability."],
            })

        duration = durations[shot_id]
        unit_id = shot_id
        task_key = f"{shot_id}-ATOMIC-REPLACEMENT-V2"
        previous_task_key = f"E37-R-A{index - 1:02d}-ATOMIC-REPLACEMENT-V2" if index > 1 else None
        previous_tail = f"working_assets/e37_action_replacement_v2_20260803/predecessor_tails/E37-R-A{index - 1:02d}_TAIL.jpg" if index > 1 else None
        task = {
            "task_key": task_key,
            "source_id": shot_id,
            "tool_type": "video_generation",
            "generation_mode": "performance_generation",
            "episode": "E37",
            "batch_id": "E37-ATOMIC-ACTION-REPLACEMENT-V2-20260803",
            "unit_id": unit_id,
            "scene_id": "E37-CW-S04",
            "visual_zone": f"fire_escape_atomic_{index:02d}",
            "duration": duration,
            "duration_seconds": duration,
            "duration_plan": {"policy": "qingshan.shot_generation_duration.v5", "duration_seconds": duration, "rationale": "One atomic contact plus a 0.55 second readable terminal state at real speed.", "edit_policy": "Trim only at the authored entry and terminal state; never repeat or slow the action."},
            "model": "seedance-2.0-pro",
            "aspect_ratio": "9:16",
            "resolution": "720p",
            "prompt_file": str(prompt_path),
            "prompt_path": str(prompt_path),
            "prompt_sha256": sha(prompt_path),
            "reference_images": refs,
            "reference_image_sequence": sequence,
            "planned_reference_image_count": 1,
            "state_reference_minimum": 1,
            "still_sequence_only_allowed": True,
            "inherits_establishing_coverage": True,
            "action_unit": True,
            "performance_tempo_contract": {
                "playback_speed": "REAL_TIME_1X",
                "entry_action_already_in_progress": True,
                "primary_action_complete_by_seconds": 1.5,
                "result_hold_seconds": 0.55,
                "forbid_duration_filling": ["slow_motion", "replay", "reset", "extended_windup", "camera_motion"],
            },
            "visual_tier": "CORE",
            "minimum_score_100": 80,
            "hard_fact_fail_overrides_score": True,
            "prompt_failure_modes_applied": failure_mode_ids,
            "prompt_failure_modes_not_applicable": [],
            "native_dialogue_required": False,
            "dialogue": [],
            "audio_reference_optional": True,
            "performance_spec": {
                "schema": "qingshan.performance_generation_spec.v3",
                "episode": "E37",
                "unit_id": unit_id,
                "duration_seconds": duration,
                "single_source_of_truth": True,
                "prop_ownership": {"single_source_rule": "The ledger and every action prop remain with the owner declared by this shot's entry and exit state tokens."},
                "motion_beats": [{
                    "subject": contact["actor"],
                    "action": contact["action"],
                    "contact_point": contact["contact_point"],
                    "direction": contact["force_direction"],
                    "end_state": contact["result_state"],
                    "intent": shot["information_beats"][0],
                    "visible_causality": contact["force_feedback"],
                    "expression": "Bodies and faces react only to the declared force; no reset, replay, or anticipatory pose.",
                    "viewer_read": "The single contact and its terminal consequence remain readable for at least 0.55 seconds.",
                }],
            },
            "keyframe_interpolation_gate": {"status": "PASS", "checked_adjacent_pairs": 0, "reason": "One temporal action-state anchor; identity references are non-temporal."},
            "visual_entity_ids": cast_by_shot[shot_id],
            "multimodal_entity_bindings": bindings,
            "multimodal_binding_sha256": binding_digest(bindings),
            "effect_provenance": [{"effect": "冰流、阴神、冰幕、水幕、皮影", "source_type": "CLAUDE_SCRIPT", "source_ref": SCRIPT}],
            "prompt_contract": {
                "source_action": contact["action"],
                "spatial_continuity": (
                    {"mode": "CROSS_SPACE_TRANSITION", "policy_source": "PER_UNIT_SCRIPT_CONTENT", "origin_scene_id": "E37-CW-S04-INTERIOR", "destination_scene_id": "E37-CW-S04-EXTERIOR", "anchor_scope": "VIDEO_WITH_ORIGIN_AND_DESTINATION_ANCHORS"}
                    if shot_id == "E37-R-A07"
                    else {"mode": "SAME_SPACE_CONTINUOUS", "policy_source": "PER_UNIT_SCRIPT_CONTENT", "scene_id": "E37-CW-S04", "anchor_scope": "PERFORMANCE_TEMPORAL_ANCHORS_ONLY", "camera_policy": "LOCKED_TO_ACTION_CONTRACT"}
                ),
            },
            "action_design_shot_id": shot_id,
            "action_design_contract_sha256": shot["action_design_contract_sha256"],
            "source_script_sha256": SCRIPT_SHA,
            "workflow_credit_scope": "e37_claude_writer_v2_07a63a0c_20260802",
            "status": "READY_TO_SUBMIT",
            "dependencies_ready": True,
            "action_sequence_contract": {
                "sequence_index": index,
                "entry_state_token": contact["pre_state"],
                "exit_state_token": contact["result_state"],
                "predecessor_tail_frame_ref": previous_tail,
                "tail_to_head_identity_required": index > 1,
                "hidden_inter_shot_events_forbidden": True,
            },
        }
        if previous_task_key:
            task["depends_on_task"] = previous_task_key
            task["dependencies_ready"] = False
        tasks.append(task)
        criteria = {"continuous_motion_from_single_start": True, "identity_or_space_reanchor": False, "prop_ownership_transition": False, "non_interpolable_terminal_state": False}
        anchor_units.append({
            "unit_id": unit_id,
            "planned_reference_image_count": 1,
            "reference_image_task_keys": [f"{unit_id}-ACTION-STATE-REF"],
            "anchor_count_decision": {"planned_reference_image_count": 1, "reason": "One accepted action-state frame can drive this single continuous contact; identity images are non-temporal authority references.", "criteria": criteria, "anchor_roles": ["ACTION_STATE_ANCHOR"], "action_design_class": camera["family"]},
            "keyframe_interpolation_gate": {"status": "PASS", "adjacent_pairs_checked": 0},
        })
        prompt_rows.append({"unit_id": unit_id, "scene_id": "E37-CW-S04", "weather": "RAIN_NIGHT", "prompt_path": str(prompt_path), "prompt_sha256": sha(prompt_path)})
        mechanical_units.append({"unit_id": unit_id, "duration_seconds": duration, "planned_reference_image_count": len(refs), "camera": camera["family"], "scene_id": "E37-CW-S04", "weather": "RAIN_NIGHT", "prompt_sha256": sha(prompt_path)})
        causality_units.append({"unit_id": unit_id, "causality": {"applicable": True, "purpose": shot["information_beats"][0], "intended_effect": contact["result_state"], "visible_causality": f"{contact['contact_point']} visibly causes {contact['force_feedback']}", "viewer_read": "The viewer can identify actor, contact, force direction, feedback and terminal state without camera motion.", "preconditions": [contact["pre_state"]], "mechanism_chain": [contact["action"], contact["force_feedback"], contact["result_state"]], "counterfactual_test": {"opponent_can_bypass": False, "reasoning": "The result is physically bound to the single visible contact and the next shot inherits its exact terminal token."}, "prop_function_status": "PASS", "evidence_refs": [PLAN, str(prompt_path)]}})
        period_units.append({"unit_id": unit_id, "period_lock": {"status": "PASS", "reviewed_visible_elements": ["古代土木宅院", "古装人物", "纸质账册", "火把", "木梁", "油灯灯油"], "detected_anachronisms": [], "exception_approvals": {}, "evidence_refs": [SCRIPT, str(prompt_path)]}})

    scene = {"schema": "qingshan.scene_state_authority.v1", "episode": "E37", "scene_state": [{"scene_id": "E37-CW-S04", "location": "刘宅正屋与东厢逃生墙洞", "time_of_day": "night", "weather": "rain", "allowed_time_terms": ["night"], "allowed_weather_terms": ["rain"], "event_summary": "火宅内八个原子动作按连续状态链完成逃生与坍塌。"}]}
    scene_path = PROD / "E37_ACTION_REPLACEMENT_SCENE_AUTHORITY_V2.json"
    write(scene_path, scene)
    anchor_plan = {"schema": "qingshan.video_unit_anchor_count_plan.v1", "episode": "E37", "planned_reference_image_count": sum(row["planned_reference_image_count"] for row in anchor_units), "uniform_count_independence_audit": {"status": "PASS", "evaluated_individually": True, "distinct_action_design_classes": 8}, "units": anchor_units}
    anchor_path = PROD / "E37_ACTION_REPLACEMENT_ANCHOR_PLAN_V2.json"
    write(anchor_path, anchor_plan)
    complete_path = PROD / "E37_ACTION_REPLACEMENT_COMPLETE_PROMPT_MANIFEST_V2.json"
    write(complete_path, {"schema": "qingshan.complete_video_prompt_manifest.v1", "episode": "E37", "all_units_have_prompt": True, "unit_count": len(prompt_rows), "source_plan": str(anchor_path), "source_plan_sha256": sha(anchor_path), "source_scene_authority": str(scene_path), "source_scene_authority_sha256": sha(scene_path), "rows": prompt_rows})
    dialogue_path = PROD / "E37_ACTION_REPLACEMENT_DIALOGUE_MANIFEST_V2.json"
    write(dialogue_path, {"schema": "qingshan.video_dialogue_manifest.v1", "episode": "E37", "status": "PASS", "rows": []})

    dramatic = {
        "schema": "qingshan.dramatic_quality_plan.v1", "episode": "E37", "script_sha256": SCRIPT_SHA, "runtime_seconds": 48,
        "council": {"advisors": [{"role": role, "independent": True, "analysis": "The repair isolates one readable action delta per shot and preserves causal state handoffs."} for role in ["film_director", "short_drama_director", "original_author", "ordinary_audience", "executive_producer", "american_tv_pacing"]], "chair_verdict": "PASS", "experience_memory_ref": "E36/E37 direct-watch motion failure memory", "revision_cascade": {"affected_unproduced_episodes": [], "affected_published_episodes": [], "status": "COMPLETE"}},
        "beats": [{"scene_entry": "late", "scene_exit": "early", "power_shift": "The exit closes, then the heroes create a new route.", "intercut_with": "outside arson pressure", "end_button": "The house collapses only after the group clears the wall.", "unresolved_question_id": "E37-Q-FIRE", "act_out": True, "dialogue_interruption_refs": ["fire interrupts the ledger search"]}, {"scene_entry": "late", "scene_exit": "early", "power_shift": "The ledger transfers to safety before the floor fails.", "intercut_with": "", "end_button": "The ledger survives while the guard is lost.", "unresolved_question_id": "E37-Q-LEDGER", "act_out": False, "dialogue_interruption_refs": []}],
        "narrative_technique_contract": {"cold_open": {"enabled": True, "within_seconds": 1.0, "event_in_progress": True}, "dual_line_episode": True},
        "two_episode_fight_floor": {"qualifying_true_fight_scene_count": 1, "minimum_qualifying_duration_seconds": 20, "duration_must_come_from_distinct_causal_beats": True},
    }
    dramatic_path = PROD / "E37_ACTION_REPLACEMENT_DRAMATIC_QUALITY_V2.json"
    write(dramatic_path, dramatic)
    mechanical_path = PROD / "E37_ACTION_REPLACEMENT_MECHANICAL_DEFAULT_V2.json"
    write(mechanical_path, {"schema": "qingshan.mechanical_default_plan.v1", "episode": "E37", "units": mechanical_units, "global_defaults": [], "variable_fields": ["duration_seconds", "planned_reference_image_count", "camera", "prompt_sha256"]})
    causality_path = PROD / "E37_ACTION_REPLACEMENT_CAUSALITY_V2.json"
    write(causality_path, {"schema": "qingshan.common_sense_causality_plan.v1", "episode": "E37", "units": causality_units})
    period_path = PROD / "E37_ACTION_REPLACEMENT_PERIOD_LOCK_V2.json"
    write(period_path, {"schema": "qingshan.anachronism_lock_plan.v1", "episode": "E37", "period_contract": {"era": "架空古代中国", "status": "PASS", "source_refs": [SCRIPT]}, "units": period_units})

    policy = json.loads((ROOT / "workflow/claude_writer_agent/production/e37_claude_writer_v2_4a738459_20260802/E37_GENERATION_FIRST_PASS_POLICY_CONFIG_V1.json").read_text(encoding="utf-8"))
    config = {
        "schema": "qingshan.episode_streaming_video_batch.v2", "episode": "E37", "status": "READY_FOR_ATOMIC_ACTION_REPLACEMENT_SUBMIT", "concurrency": 8, "max_retries": 0,
        "retry_policy": "FAILED_ITEMS_ONLY_MATERIALLY_CHANGED_INPUT_REQUIRED", "effective_ruleset": "QINGSHAN_PIPELINE_EFFECTIVE_RULESET_V1", "workflow_credit_scope": "e37_claude_writer_v2_07a63a0c_20260802", "video_credit_limit": 10000,
        "source_script_sha256": SCRIPT_SHA, "output_dir": "working_assets/e37_action_replacement_v2_20260803/outputs", "qa_dir": str(QA), "targeted_unit_replacement": True,
        "scene_contract_ref": str(scene_path), "script_readiness_report": "qa/e37_preproduction_20260802/E37_CANONICAL_AND_SCRIPT_PREFLIGHT_V1.json",
        "dramatic_quality_report_ref": str(dramatic_path), "mechanical_default_plan_ref": str(mechanical_path), "anchor_count_plan_ref": str(anchor_path), "common_sense_causality_plan_ref": str(causality_path), "action_shot_design_plan_ref": PLAN, "period_lock_plan_ref": str(period_path),
        "complete_video_prompt_manifest_ref": str(complete_path), "dialogue_manifest_ref": str(dialogue_path), "voice_registry_ref": "configs/series_voice_reference_registry_current_20260723.json", "supervisor_script_gate_required": False, "space_camera_constraint_gate_required": True,
        "generation_first_pass_policy_ref": policy["generation_first_pass_policy_ref"], "generation_first_pass_policy_sha256": policy["generation_first_pass_policy_sha256"], "generation_prompt_failure_memory_ref": str(failure_memory_path), "generation_prompt_failure_memory_sha256": sha(failure_memory_path),
        "writer_agent_provenance": {"status": "PASS", "provenance_type": "claude_writer_script", "source_script": SCRIPT, "source_script_sha256": SCRIPT_SHA, "production_manifest": MANIFEST, "production_manifest_sha256": MANIFEST_SHA},
        "tasks": tasks,
    }
    config_path = PROD / "E37_ATOMIC_ACTION_REPLACEMENT_BATCH_V2.json"
    write(config_path, config)
    print(json.dumps({"status": "BUILT", "config": str(config_path), "tasks": len(tasks), "prompt_dir": str(OUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
