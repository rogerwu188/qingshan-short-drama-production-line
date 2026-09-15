from __future__ import annotations

from copy import deepcopy
import unittest

from tools.video_prompt_compiler import compile_model_prompt, compile_receipt
from tools.video_execution_plan_compiler import compile_video_execution_plan
from tools.h3_provider_english_contract import bind_h3_provider_english_contract
from tools.provider_semantic_coverage import assert_equivalent_required_fact_sets
from tools.visual_culture_contract import DEFAULT_CONTRACT


def _unit(model: str = "seedance-2.0-pro") -> dict:
    return {
        "unit_id": "E99-VU-001",
        "episode": "E99",
        "visual_culture_contract": DEFAULT_CONTRACT,
        "character_entities": [
            {"character_id": "CHAR-CHENJI", "canonical_name": "陈迹", "aliases": []},
            {"character_id": "CHAR-MASKED", "canonical_name": "蒙面人", "aliases": []},
        ],
        "pipeline_rectification_version": "E51_V1",
        "model": model,
        "duration_seconds": 4,
        "resolution": "720p",
        "aspect_ratio": "9:16",
        "reference_images": [{"path": "anchor.png", "role": "START"}],
        "wuxia_combat_profile_required": True,
        "wuxia_combat_profile_signals": {
            "weapon_type": "BLADE",
            "cast_count": 2,
            "interaction_modes": ["CONTACT"],
            "environment_tags": ["RAIN"],
            "profile_ids": ["WXC-SWORD-02", "WXC-ENV-01"],
        },
        "camera_plan": {
            "shot_scale": "MEDIUM",
            "camera_height": "EYE_LEVEL",
            "camera_side": "AXIS_A",
            "motion_family": "PAN",
            "motion_direction": "LEFT_TO_RIGHT",
            "lens_intent": "35mm保留双方距离与接触路径",
            "axis_relation": "人物轴A侧不越轴",
            "start_framing": "攻击者右肩与承受者胸口同框",
            "end_framing": "承受者撞向桌角的结果同框",
            "motivation": "只随短刀冲量短促右摇并在受力结果停住",
            "signature": "PAN:LEFT_TO_RIGHT",
        },
        "ordered_prompt_specs": [{
            "space": {"location": "雨夜客栈", "subspace": "北窗内侧"},
            "scene_state": {"time": "夜", "weather": "窗外有雨", "palette": "冷蓝暖灯"},
            "cast": [
                {"character": "陈迹", "character_id": "CHAR-CHENJI"},
                {"character": "蒙面人", "character_id": "CHAR-MASKED"},
            ],
            "props": [
                {
                    "prop": "短刀",
                    "state": {
                        "entry": {"owner": "蒙面人", "hand": "RIGHT", "position": "右肋", "disposition": "HELD"},
                        "exit": {"owner": "蒙面人", "hand": "RIGHT", "position": "陈迹左前臂外侧", "disposition": "HELD"},
                    },
                    "transition_authorization": {"writer_authored": True},
                    "start_frame_visual_confirmation": {"status": "PASS", "evidence_ref": "fixture://short-blade-right-hand"},
                },
                {
                    "prop": "方桌",
                    "state": {
                        "entry": {"owner": "场景", "hand": "NONE", "position": "陈迹身前", "disposition": "FIXED"},
                        "exit": {"owner": "场景", "hand": "NONE", "position": "被髋部撞偏", "disposition": "FIXED"},
                    },
                    "transition_authorization": {"writer_authored": True},
                    "start_frame_visual_confirmation": {"status": "PASS", "evidence_ref": "fixture://table-in-frame"},
                },
            ],
            "role_semantic_disambiguation": {
                "schema": "qingshan.role_semantic_disambiguation.v1",
                "status": "PASS",
                "shot_id": "E99-S01-01",
                "primary_actor": "蒙面人",
                "primary_actor_id": "CHAR-MASKED",
                "primary_actor_kind": "CHARACTER",
                "dialogue_speaker": "",
                "dialogue_listener": "",
                "action_patient": "陈迹",
                "action_patient_id": "CHAR-CHENJI",
                "dialogue_speaker_id": "",
                "dialogue_listener_id": "",
                "lip_owner_id": "",
                "entity_states": {
                    "CHAR-MASKED": "唯一发力者，持短刀前冲",
                    "CHAR-CHENJI": "唯一承受者，在桌后抬左臂格挡",
                },
                "entity_presence": {
                    "CHAR-MASKED": "VISIBLE_AND_IDENTITY_LOCKED",
                    "CHAR-CHENJI": "VISIBLE_AND_IDENTITY_LOCKED",
                },
                "forbidden_role_swaps": True,
                "unresolved": [],
            },
            "action": {
                "subject_id": "CHAR-MASKED",
                "action_kind": "COMBAT",
                "t0_seconds": 0,
                "t1_seconds": 4,
                "start_state": "蒙面人双脚刚落地，短刀收在右肋；陈迹直立在桌后",
                "primary_action": "蒙面人落地即起，短刀贴桌猛地直刺陈迹前胸",
                "contact_time_seconds": 1.1,
                "contact_point": "刀背撞偏陈迹抬起的左前臂",
                "force_feedback": "陈迹左肩后撤，方桌被髋部撞偏，杯子摔碎",
                "completion_state": "刀尖越过陈迹左侧，陈迹退至桌角且左臂仍承重",
                "state_delta_dimensions": ["POSITION", "CONTACT", "MOMENTUM"],
                "state_delta_evidence": {
                    "POSITION": {"entry": "陈迹在桌后", "exit": "陈迹退至桌角", "entry_code": "BEHIND_TABLE", "exit_code": "AT_TABLE_CORNER"},
                    "CONTACT": {"entry": "刀与人未接触", "exit": "刀背压住左前臂", "entry_code": "NO_CONTACT", "exit_code": "BLADE_ARM_CONTACT"},
                    "MOMENTUM": {"entry": "蒙面人落地前冲", "exit": "冲量转移到陈迹与方桌", "entry_code": "ATTACKER_FORWARD", "exit_code": "TRANSFERRED_TO_TARGET_TABLE"},
                },
                "patient_state_delta_dimensions": ["POSITION", "POSTURE"],
                "patient_state_delta_evidence": {
                    "POSITION": {"entry": "陈迹在桌后", "exit": "陈迹退至桌角"},
                    "POSTURE": {"entry": "直立抬臂", "exit": "左肩后撤且左臂承重"},
                },
            },
            "performance": {"event_reaction": "接触瞬间陈迹瞳孔收紧，肩颈随受力后撤"},
            "dialogue": "",
            "sound_design": {
                "ambience": "窗外雨声", "foley": "衣料与木桌摩擦",
                "action_sound": "短刀破风、前臂格挡闷响、瓷杯碎裂",
            },
            "negative_prompts": ["无额外人物", "无肢体增生"],
        }],
    }


class SharedVideoExecutionCompilerTest(unittest.TestCase):
    def test_sd2_and_h3_share_execution_semantics_but_not_prompt_grammar(self) -> None:
        sd2 = _unit()
        h3 = deepcopy(sd2)
        h3["model"] = "MiniMax-H3"
        sd2_prompt = compile_model_prompt(sd2)
        sd2_receipt = deepcopy(compile_receipt("E99-VU-001"))
        bind_h3_provider_english_contract(h3, {
            "identity_prop_fact": "Subjects are Chen Ji and one masked attacker; key props are one short blade and one square table",
            "space_weather_fact": "Same north-window interior of a rain-night inn; cold blue exterior and warm lamp light",
            "beats": [{
                "entry_state": "the masked attacker has just landed with the blade at the right ribs while Chen Ji stands behind the table",
                "primary_action": "the attacker rises immediately and thrusts the short blade hard across the tabletop toward Chen Ji's chest",
                "contact_point": "the blade spine strikes Chen Ji's raised left forearm",
                "force_feedback": "Chen Ji's left shoulder recoils, his hip knocks the table aside, and one cup shatters",
                "exit_state": "the blade tip passes Chen Ji's left side while he reaches the table corner with the left arm still bearing force",
                "microexpression_cue": "Chen Ji's pupils tighten once at contact and his neck follows the recoil",
            }],
            "sounds": {
                "ambience": ["rain outside the window"],
                "foley": ["cloth and wood-table friction"],
                "action_sound": ["blade whoosh, forearm impact, and one cup shattering"],
            },
            "environment_motion": [],
            "negative_constraints": ["No extra people", "No malformed limbs"],
        })
        h3_prompt = compile_model_prompt(h3)
        h3_receipt = deepcopy(compile_receipt("E99-VU-001"))
        self.assertIn("【时间轴】", sd2_prompt)
        self.assertIn("detailed_description:", h3_prompt)
        self.assertIn("估算35mm焦段", sd2_prompt)
        self.assertIn("estimated 35mm focal length", h3_prompt)
        self.assertEqual(sd2_receipt["camera_language_selection"]["mode"], "HYBRID")
        self.assertEqual(h3_receipt["camera_language_selection"]["mode"], "HYBRID")
        self.assertEqual(
            sd2_receipt["wuxia_combat_profile_selection"]["selected_profile_ids"],
            ["WXC-SWORD-02", "WXC-ENV-01"],
        )
        self.assertEqual(
            sd2_receipt["wuxia_combat_profile_selection"]["selected_profile_ids"],
            h3_receipt["wuxia_combat_profile_selection"]["selected_profile_ids"],
        )
        self.assertIn("武侠动作镜头原型", sd2_prompt)
        self.assertIn("Wuxia action-camera profile", h3_prompt)
        self.assertNotIn("ROLE_LOCK[", sd2_prompt + h3_prompt)
        self.assertEqual(compile_receipt("E99-VU-001")["motion_density_gate"]["status"], "PASS")
        self.assertEqual(
            sd2_receipt["execution_semantics_sha256"],
            h3_receipt["execution_semantics_sha256"],
        )
        assert_equivalent_required_fact_sets(
            sd2_receipt["provider_semantic_coverage_receipt"],
            h3_receipt["provider_semantic_coverage_receipt"],
        )
        self.assertEqual(sd2_receipt["provider_semantic_coverage_receipt"]["status"], "PASS")
        self.assertEqual(h3_receipt["provider_semantic_coverage_receipt"]["status"], "PASS")
        self.assertNotEqual(
            sd2_receipt["immutable_contract_sha256"],
            h3_receipt["immutable_contract_sha256"],
        )
        self.assertNotEqual(
            sd2["ordered_prompt_specs"][0]["action"]["start_state"],
            sd2["ordered_prompt_specs"][0]["action"]["completion_state"],
        )

    def test_identical_entry_and_exit_fails_closed(self) -> None:
        unit = _unit()
        action = unit["ordered_prompt_specs"][0]["action"]
        action["completion_state"] = action["start_state"]
        with self.assertRaisesRegex(ValueError, "STATE_ENDPOINT_IDENTICAL"):
            compile_model_prompt(unit)

    def test_combat_impulse_gates_are_deterministic(self) -> None:
        cases = [
            ({"contact_time_seconds": 0.2}, "COMBAT_CONTACT_RATIO"),
            ({"primary_action": "蒙面人持续把短刀推向陈迹前胸"}, "COMBAT_IMPULSE_VERB_MISSING|COMBAT_EXTEND_WORD_FORBIDDEN"),
            ({"state_delta_dimensions": ["POSITION"]}, "STATE_DELTA_DIMENSION_COUNT"),
        ]
        for bad_action, match in cases:
            with self.subTest(bad_action=bad_action):
                unit = _unit()
                unit["ordered_prompt_specs"][0]["action"].update(bad_action)
                with self.assertRaisesRegex(ValueError, match):
                    compile_model_prompt(unit)

    def test_action_ir_is_shared_and_capacity_is_observe_only(self) -> None:
        plan = compile_video_execution_plan(_unit())
        self.assertEqual(
            plan["action_ir"]["schema"],
            "qingshan.action_ir.v1_single_causal_chain_per_beat",
        )
        beat = plan["action_ir"]["causal_chains"][0]
        self.assertEqual(beat["interaction_mode"], "CONTACT")
        self.assertEqual(beat["action_capacity"]["tier"], "UNCALIBRATED_OBSERVE_ONLY")
        self.assertFalse(beat["action_capacity"]["hard_rejection"])
        self.assertFalse(plan["action_ir"]["post_generation_dynamic_media_qa_required"])

    def test_duration_underfill_fails_before_submission(self) -> None:
        unit = _unit()
        unit["authorized_content_seconds"] = 2.0
        with self.assertRaisesRegex(ValueError, "DURATION_EXCEEDS_AUTHORIZED_CONTENT"):
            compile_model_prompt(unit)

    def test_threat_threshold_cannot_claim_contact_state_delta(self) -> None:
        unit = _unit()
        action = unit["ordered_prompt_specs"][0]["action"]
        action["contact_point"] = "刀尖抵达陈迹胸前一掌距离，刀刃尚未接触衣襟"
        with self.assertRaisesRegex(ValueError, "AMBIGUOUS_CONTACT_TYPE"):
            compile_model_prompt(unit)

    def test_only_one_secondary_feedback_is_allowed(self) -> None:
        unit = _unit()
        unit["ordered_prompt_specs"][0]["action"]["secondary_feedback"] = [
            "雨水飞散", "灯焰熄灭",
        ]
        with self.assertRaisesRegex(ValueError, "COMBAT_SECONDARY_FEEDBACK_LIMIT"):
            compile_model_prompt(unit)

    def test_mixed_unit_does_not_force_noncombat_beat_through_combat_gate(self) -> None:
        unit = _unit()
        recovery = deepcopy(unit["ordered_prompt_specs"][0])
        recovery["action"] = {
            "action_kind": "PHYSICAL_ACTION",
            "t0_seconds": 0,
            "t1_seconds": 2,
            "start_state": "陈迹左臂仍承重，蒙面人短刀已经偏出",
            "primary_action": "陈迹退至桌角并重新站稳",
            "interaction_mode": "NONE",
            "contact_point": "陈迹双脚在桌角重新落稳",
            "force_origin": "前一拍冲量衰减后由陈迹双腿承重",
            "primary_feedback": "肩线回正，桌脚停止滑动",
            "completion_state": "陈迹在桌角站稳，蒙面人位于桌侧",
            "state_delta_dimensions": ["POSITION", "POSTURE"],
            "state_delta_evidence": {
                "POSITION": {"entry": "陈迹在桌后", "exit": "陈迹在桌角", "entry_code": "BEHIND_TABLE", "exit_code": "AT_CORNER"},
                "POSTURE": {"entry": "左臂承重", "exit": "双脚站稳", "entry_code": "ARM_BEARING", "exit_code": "FEET_SET"},
            },
        }
        attack = deepcopy(unit["ordered_prompt_specs"][0])
        attack["action"]["t0_seconds"] = 2
        attack["action"]["t1_seconds"] = 4
        attack["action"]["contact_time_seconds"] = 2.8
        unit["ordered_prompt_specs"] = [recovery, attack]
        plan = compile_video_execution_plan(unit)
        self.assertEqual(plan["unit_class"], "COMBAT_IMPULSE")
        self.assertEqual(plan["beats"][0]["source_action_kind"], "PHYSICAL_ACTION")
        self.assertEqual(plan["beats"][1]["source_action_kind"], "COMBAT")
        self.assertEqual(plan["motion_density_gate"]["status"], "PASS")

    def test_h3_accepts_official_three_second_minimum(self) -> None:
        unit = _unit("MiniMax-H3")
        unit["duration_seconds"] = 3
        unit["authorized_content_seconds"] = 3
        action = unit["ordered_prompt_specs"][0]["action"]
        action["t1_seconds"] = 3
        action["contact_time_seconds"] = 1.0
        plan = compile_video_execution_plan(unit)
        self.assertEqual(plan["duration_seconds"], 3.0)


if __name__ == "__main__":
    unittest.main()
