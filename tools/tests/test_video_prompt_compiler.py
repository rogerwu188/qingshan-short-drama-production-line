from __future__ import annotations

from copy import deepcopy
import re
import unittest

from tools.h3_provider_english_contract import (
    DIALOGUE_TAG,
    bind_h3_provider_english_contract,
    validate_h3_provider_text_boundary,
)
from tools.speaker_voice_contract import attach_speaker_voice_contract
from tools.video_prompt_compiler import (
    compile_model_prompt,
    compile_receipt,
    model_family,
    validate_model_prompt_for_model,
)
from tools.submit_giggle_video_manifest_v2 import uses_structured_role_gate


def _spec(*, dialogue: str = "") -> dict:
    spec = {
        "space": {"location": "医馆门外", "subspace": "马车旁"},
        "scene_state": {"time": "清晨", "weather": "薄雾，晨风很轻", "palette": "冷灰"},
        "cast": [{"character": "白鲤", "character_id": "CHAR-BAILI"}],
        "props": [{
            "prop": "车帘",
            "state": {
                "entry": {"owner": "马车", "hand": "白鲤右手", "position": "门框内侧", "disposition": "HELD"},
                "exit": {"owner": "马车", "hand": "白鲤右手", "position": "门框一侧", "disposition": "HELD"},
            },
            "transition_authorization": {"writer_authored": True},
            "start_frame_visual_confirmation": {"status": "PASS", "evidence_ref": "fixture://curtain-at-hand"},
        }],
        "action": {
            "action_kind": "PHYSICAL_ACTION",
            "subject_id": "CHAR-BAILI",
            "t0_seconds": 0,
            "t1_seconds": 6,
            "start_state": "白鲤的手指顶住帘边",
            "primary_action": "白鲤掀开车帘并看向门口",
            "completion_state": "帘布停在一侧，白鲤的目光落在门口",
            "state_delta_dimensions": ["POSITION"],
            "state_delta_evidence": {
                "POSITION": {
                    "entry": "手指在帘边内侧",
                    "exit": "车帘移到一侧",
                    "entry_code": "CURTAIN_CLOSED_EDGE",
                    "exit_code": "CURTAIN_OPEN_SIDE",
                }
            },
        },
        "performance": {
            "expression_arc": "目光从车帘转到门口",
            "body_sync": "下颌先转，肩颈随后跟进",
        },
        "dialogue": dialogue,
        "sound_design": {
            "ambience": "街巷晨风与远处晨鸡",
            "foley": "帘布和衣袖摩擦",
            "action_sound": "指节推动帘边的一次轻响",
        },
        "negative_prompts": ["无字幕", "无水印"],
    }
    spec["role_semantic_disambiguation"] = {
        "primary_actor": "白鲤",
        "primary_actor_id": "CHAR-BAILI",
        "primary_actor_kind": "CHARACTER",
        "dialogue_speaker": "白鲤" if dialogue else "",
        "dialogue_speaker_id": "CHAR-BAILI" if dialogue else "",
        "lip_owner_id": "CHAR-BAILI" if dialogue else "",
        "dialogue_mode": "VISIBLE_DIALOGUE" if dialogue else "NONE",
        "entity_presence": {"CHAR-BAILI": "VISIBLE"},
        "entity_states": {"CHAR-BAILI": "ACTIVE"},
    }
    return spec


def _unit(*, dialogue: str = "", transitions: bool = False) -> dict:
    unit = {
        "unit_id": "E45-VU-TEST",
        "model": "MiniMax-H3",
        "duration_seconds": 6,
        "aspect_ratio": "9:16",
        "resolution": "720p",
        "ordered_prompt_specs": [_spec(dialogue=dialogue)],
        "reference_images": [{
            "path": "first.png", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE",
        }],
        "character_entities": [{
            "character_id": "CHAR-BAILI", "canonical_name": "白鲤", "aliases": [],
        }],
        "provider_entity_token_map": {"白鲤": "SUBJECT_1"},
        "provider_scope_projection": {
            "schema": "qingshan.provider_scope_projection.v1",
            "status": "LOCKED",
            "scene_domain": "CLINIC_EXTERIOR",
            "visible_character_ids": ["CHAR-BAILI"],
            "visible_entity_instance_counts": {"CHAR-BAILI": 1},
            "exclusive_visible_living_entity_set": True,
            "visible_living_entity_instance_total": 1,
            "background_population_count": 0,
            "unbound_visible_living_entity_count": 0,
            "visible_prop_ids": [],
            "location_ids": [],
            "environment_terms": [],
            "sound_terms": [],
            "reference_identity_bindings": [{
                "reference_index": 1,
                "entity_id": "CHAR-BAILI",
                "provider_entity_label": "Baili",
                "exclusive_identity_owner": True,
            }],
            "absent_episode_entities": [],
            "episode_prop_catalog": [],
            "provider_reads_episode_global_contract_directly": False,
        },
        "camera_plan": {
            "shot_scale": "MEDIUM_CLOSE_UP",
            "camera_height": "EYE_LEVEL",
            "camera_side": "AXIS_A",
            "motion_family": "DOLLY",
            "motion_direction": "PUSH_IN",
            "lens_intent": "50mm保持人物面部与手部动作清楚",
            "axis_relation": "始终保持人物轴线A侧",
            "start_framing": "车帘边缘与白鲤上半身同框",
            "end_framing": "推近到白鲤目光和手部同框",
            "motivation": "随车帘开启和目光确认短促推近",
        },
        "wardrobe_contract": {"characters": [{
            "character": "白鲤", "primary_color": "象牙白",
            "secondary_color": "浅青", "continuity_key": "BAILI-IVORY-CELADON-V1",
        }]},
    }
    if transitions:
        unit["incoming_transition_contract"] = {
            "target_initial_state": {"blocking": "帘边仍被手指顶住"},
        }
        unit["outgoing_transition_contract"] = {
            "source_terminal_state": {"blocking": "帘布停在一侧，目光落在门口"},
        }
    if dialogue:
        attach_speaker_voice_contract(unit, {"characters": [{
            "character": "白鲤", "entity_id": "baili",
            "status": "LOCKED_PRODUCTION_READY",
            "remote_asset_id": "test-baili-voice",
            "remote_url": "https://example.invalid/baili.wav",
        }]})
    return unit


def _english_payload(unit: dict) -> dict:
    beats = []
    for index, spec in enumerate(unit["ordered_prompt_specs"]):
        action = spec["action"]
        row = {
            "entry_state": f"beat {index + 1} starts with the hand at the curtain edge",
            "primary_action": f"beat {index + 1} opens the carriage curtain and turns the gaze toward the doorway",
            "exit_state": f"beat {index + 1} ends with the curtain at one side and the gaze on the doorway",
            "microexpression_cue": "the gaze shifts once and then settles",
            "body_sync_cue": "the jaw turns first and the shoulders follow",
        }
        for key in ("contact_point", "force_feedback"):
            if action.get(key):
                row[key] = "one visible contact point" if key == "contact_point" else "the receiver recoils along the force direction"
        if index < len(unit.get("internal_transition_contracts") or []):
            row["internal_transition_after"] = f"bridge from beat {index + 1} into beat {index + 2} without reset"
        beats.append(row)
    transition = {}
    if unit.get("incoming_transition_contract"):
        transition["incoming"] = "the fingers already hold the curtain edge"
    if unit.get("outgoing_transition_contract"):
        transition["outgoing"] = "the curtain stays open while the gaze remains on the doorway"
    return {
        "identity_prop_fact": "One adult character named BAILI and one carriage curtain, with identity and wardrobe locked by references",
        "space_weather_fact": "Same carriage-side area outside the clinic at dawn, with thin mist and cold-gray light",
        "beats": beats,
        "sounds": {
            "ambience": ["morning alley wind and one distant rooster"],
            "foley": ["curtain cloth and sleeve friction"],
            "action_sound": ["one soft finger contact on the curtain edge"],
        },
        "environment_motion": [],
        "negative_constraints": ["No captions", "No watermark"],
        "transition": transition,
    }


def _compile_h3(unit: dict) -> str:
    bind_h3_provider_english_contract(unit, _english_payload(unit))
    return compile_model_prompt(unit)


def _make_combat() -> dict:
    unit = _unit()
    unit["duration_seconds"] = 4
    unit["action_classification"] = "COMBAT"
    unit["combat_or_chase"] = True
    action = unit["ordered_prompt_specs"][0]["action"]
    action.update({
        "t1_seconds": 4,
        "start_state": "袭击者握刀在右肋，白鲤站在门边",
        "primary_action": "袭击者跨步直刺，白鲤侧身格开刀背",
        "contact_time_seconds": 1.1,
        "contact_point": "刀背与白鲤左前臂唯一接触",
        "force_feedback": "袭击者腕部被格开，刀尖偏离胸口",
        "completion_state": "袭击者右臂偏到外侧，白鲤移到门柱后",
        "state_delta_dimensions": ["CONTACT", "POSITION", "MOMENTUM"],
        "state_delta_evidence": {
            "CONTACT": {"entry": "刀未接触", "exit": "刀背接触左前臂", "entry_code": "NO_CONTACT", "exit_code": "BLADE_FOREARM_CONTACT"},
            "POSITION": {"entry": "白鲤在门边", "exit": "白鲤在门柱后", "entry_code": "AT_DOOR", "exit_code": "BEHIND_POST"},
            "MOMENTUM": {"entry": "刀向胸口", "exit": "刀向外偏", "entry_code": "THRUST_IN", "exit_code": "DEFLECT_OUT"},
        },
        "patient_state_delta_dimensions": ["POSITION", "POSTURE"],
        "patient_state_delta_evidence": {
            "POSITION": {"entry": "白鲤在门边", "exit": "白鲤在门柱后"},
            "POSTURE": {"entry": "直立", "exit": "侧身格挡"},
        },
    })
    unit["interaction_topology_contract"] = {"required": True}
    return unit


class VideoPromptCompilerTest(unittest.TestCase):
    def test_model_families_route_independently(self):
        self.assertEqual(model_family("seedance-2.0-pro"), "seedance2")
        self.assertEqual(model_family("MiniMax-H3"), "minimax-h3")
        with self.assertRaises(ValueError):
            model_family("seedance-2.0-fast")

    def test_router_keeps_seedance_grammar_independent(self):
        unit = _unit()
        unit["model"] = "seedance-2.0-pro"
        text = compile_model_prompt(unit)
        self.assertIn("【时间轴】", text)
        self.assertNotIn("subject_definitions:", text)

    def test_shared_sd2_prompt_uses_structured_role_gate_not_legacy_role_dump(self):
        unit = _unit(dialogue="白鲤：陈迹。")
        unit["model"] = "seedance-2.0-pro"
        text = compile_model_prompt(unit)
        self.assertNotIn("ROLE_LOCK[", text)
        self.assertNotIn("角色语义消歧硬锁", text)
        self.assertTrue(uses_structured_role_gate({"model": unit["model"]}, text))

    def test_h3_requires_sha_bound_english_execution_contract(self):
        with self.assertRaisesRegex(ValueError, "H3_ENGLISH_CONTRACT"):
            compile_model_prompt(_unit())

    def test_h3_dialogue_is_the_only_cjk_outside_machine_metadata(self):
        unit = _unit(dialogue="白鲤：陈迹。")
        text = _compile_h3(unit)
        outside = DIALOGUE_TAG.sub("", text)
        self.assertIsNone(re.search(r"[\u3400-\u9fff]", outside))
        self.assertEqual(text.count("<d>[Chinese] 陈迹。</d>"), 1)
        self.assertIn("Only literals inside d-tags may become speech", text)
        self.assertEqual(validate_model_prompt_for_model(
            text, model=unit["model"], source_id=unit["unit_id"], unit=unit
        )["status"], "PASS")

    def test_h3_dialogue_closes_identity_image_lip_and_voice_loop(self):
        text = _compile_h3(_unit(dialogue="白鲤：陈迹。"))
        self.assertIn(
            "Baili is SUBJECT_1 with identity @Image1, lip owner SPEAKER_1 "
            "and exclusive voice @Audio1",
            text,
        )
        self.assertIn(
            "Baili (SUBJECT_1, identity @Image1, lip owner SPEAKER_1, "
            "fixed voice @Audio1)",
            text,
        )

    def test_h3_dialogue_fails_closed_without_speaker_voice_contract(self):
        unit = _unit(dialogue="白鲤：陈迹。")
        unit.pop("speaker_voice_contract")
        with self.assertRaisesRegex(ValueError, "SPEAKER_VOICE_CONTRACT"):
            _compile_h3(unit)

    def test_h3_silent_unit_explicitly_closes_mouths(self):
        text = _compile_h3(_unit())
        self.assertNotIn("<d>", text)
        self.assertIn("every visible person keeps the mouth closed", text)

    def test_h3_cjk_and_quoted_cjk_hard_checks(self):
        text = _compile_h3(_unit(dialogue="白鲤：陈迹。"))
        for suffix, code in (("\n景朝标签", "H3_CJK_OUTSIDE_DIALOGUE"), ('\n"景朝"', "H3_QUOTED_CJK_FORBIDDEN")):
            report = validate_h3_provider_text_boundary(text + suffix, source_id="X")
            self.assertEqual(report["status"], "FAIL")
            self.assertTrue(any(code in row for row in report["failures"]))

    def test_h3_zero_text_frame_contract_is_fail_closed(self):
        unit = _unit()
        text = _compile_h3(unit)
        weakened = text.replace("TEXT-FREE FRAME", "TRY TO AVOID TEXT")
        report = validate_model_prompt_for_model(
            weakened, model=unit["model"], source_id=unit["unit_id"], unit=unit
        )
        self.assertEqual(report["status"], "FAIL")

    def test_h3_contact_action_binds_limb_ownership_and_occlusion_topology(self):
        text = _compile_h3(_make_combat())
        self.assertIn("anatomically connected through shoulder", text)
        self.assertIn("no isolated limb, extra limb, severed limb", text)

    def test_h3_combat_uses_real_motion_contract_not_reference_tableaux(self):
        text = _compile_h3(_make_combat())
        self.assertIn("setup and displacement, one contact or clear evasion", text)
        self.assertIn("no posing, push-hands contact, or still-frame interpolation", text)

    def test_h3_transition_contract_is_serialized_as_semantics_not_ids(self):
        unit = _unit(transitions=True)
        text = _compile_h3(unit)
        self.assertIn("the fingers already hold the curtain edge", text)
        self.assertIn("the curtain stays open", text)
        self.assertNotIn("BND-", text)

    def test_h3_internal_transition_rows_bind_in_exact_shot_order(self):
        unit = _unit()
        unit["duration_seconds"] = 12
        unit["ordered_prompt_specs"] = [_spec(), _spec()]
        unit["internal_transition_contracts"] = [{"action_bridge": "中文源衔接，不进入H3提示词"}]
        text = _compile_h3(unit)
        first = text.index("beat 1 opens")
        bridge = text.index("bridge from beat 1 into beat 2")
        second = text.index("beat 2 opens")
        self.assertLess(first, bridge)
        self.assertLess(bridge, second)

    def test_h3_strips_speakable_action_scaffolding_by_translation_boundary(self):
        unit = _unit(dialogue="白鲤：陈迹。")
        unit["ordered_prompt_specs"][0]["action"]["start_state"] = "说这句时她的手指顶住帘边"
        text = _compile_h3(unit)
        self.assertNotIn("说这句时", text)
        self.assertEqual(text.count("陈迹。"), 1)

    def test_h3_profiles_preserve_existing_safety_constraints(self):
        for profile, expected in (
            ("H3_CONCISE_QUOTED_DIALOGUE_REPAIR_V1", "Only the bound named speaker may speak"),
            ("H3_MINIMAL_AUDIO_RESCUE_V1", "Repair only the declared native sound"),
            ("H3_CONCISE_COMBAT_REPAIR_V1", "no push-hands contact"),
        ):
            unit = _make_combat() if "COMBAT" in profile else _unit(dialogue="白鲤：陈迹。")
            unit["h3_prompt_profile"] = profile
            self.assertIn(expected, _compile_h3(unit))

    def test_model_prompt_is_compact_and_does_not_leak_machine_contract(self):
        unit = _unit(dialogue="白鲤：陈迹。")
        text = _compile_h3(unit)
        self.assertLess(len(text), 3000)
        for forbidden in ("qingshan.", "sha256", "ROLE_LOCK[", "immutable_contract_sha256"):
            self.assertNotIn(forbidden, text)
        receipt = compile_receipt(unit["unit_id"])
        self.assertEqual(receipt["provider_semantic_coverage_receipt"]["status"], "PASS")

    def test_h3_adult_female_visual_is_explicitly_adult_and_model_specific(self):
        unit = _unit()
        unit["wardrobe_contract"]["characters"][0].update({
            "gender_presentation": "FEMALE", "adult_status": "CONFIRMED_ADULT",
        })
        text = _compile_h3(unit)
        self.assertIn("mature, naturally fuller silhouette", text)
        unit["model"] = "seedance-2.0-pro"
        unit.pop("h3_provider_english_contract", None)
        self.assertNotIn("mature, naturally fuller silhouette", compile_model_prompt(unit))

    def test_h3_adult_female_visual_rejects_explicit_direction(self):
        unit = _unit()
        unit["wardrobe_contract"]["characters"][0].update({
            "gender_presentation": "FEMALE", "adult_status": "CONFIRMED_ADULT",
            "mature_visual_direction": "全裸色情造型",
        })
        with self.assertRaisesRegex(ValueError, "H3_ADULT_FEMALE_EXPLICIT_VISUAL_FORBIDDEN"):
            _compile_h3(unit)

    def test_h3_stale_translation_sha_fails_closed(self):
        unit = _unit()
        _compile_h3(unit)
        unit["ordered_prompt_specs"][0]["action"]["completion_state"] = "另一个结果"
        with self.assertRaisesRegex(ValueError, "SOURCE_SHA_MISMATCH"):
            compile_model_prompt(unit)

    def test_exact_rendered_provider_payload_over_10000_runes_fails_preflight(self):
        prompt = "【任务】【锚点】【时间轴】【摄影】【声音】【限制】" + "甲" * 10000
        report = validate_model_prompt_for_model(
            prompt, model="seedance-2.0-pro", source_id="E99-VU-001"
        )
        self.assertEqual(report["status"], "FAIL")
        self.assertGreater(report["prompt_runes"], 10000)
        self.assertEqual(report["maximum_prompt_runes"], 10000)
        self.assertTrue(any(
            value.startswith("PROVIDER_PROMPT_RUNE_LIMIT_EXCEEDED:E99-VU-001:")
            for value in report["failures"]
        ))


if __name__ == "__main__":
    unittest.main()
