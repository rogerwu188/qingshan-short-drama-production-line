import unittest
from unittest.mock import patch

from tools.minimax_h3_prompt_compiler import (
    H3_MODEL_PROMPT_POLICY_VERSION,
    H3_MINIMAL_AUDIO_RESCUE_PROFILE,
    H3_ANTI_CAPTION_CLAUSE,
    H3_SPEECH_ISOLATION_REPAIR_PROFILE,
    compile_h3_prompt,
    validate_h3_prompt,
)
from tools.wardrobe_identity_contract import (
    h3_adult_female_visual_block,
    model_specific_adult_female_visual_block,
)
from tools.compile_grouped_seedance_manifest import prompt_text as seedance_prompt_text
from tools.video_prompt_compiler import (
    compile_model_prompt,
    model_family,
    validate_model_prompt_for_model,
)
from tools.speaker_voice_contract import attach_speaker_voice_contract


def h3_spec(*, dialogue=""):
    return {
        "space": {"global": "GLOBAL", "location": "门外", "subspace": "马车旁"},
        "scene_state": {
            "time": "清晨，医馆门外",
            "weather": "薄雾贴地，晨风很轻",
            "palette": "冷灰",
        },
        "cast": [{"character": "白鲤"}],
        "props": [{"prop": "帘"}],
        "action": {
            "t0_seconds": 0,
            "t1_seconds": 6,
            "start_state": "白鲤的手指顶住帘边",
            "primary_action": "白鲤掀开车帘并看向门口",
            "completion_state": "帘布停在一侧，白鲤的目光落在门口",
        },
        "performance": {
            "expression_arc": "克制观察转为确认",
            "continuous_micro_action": "自然呼吸持续，目光先移动",
            "body_sync": "下颌与肩颈随后响应",
        },
        "dialogue": dialogue,
        "dialogue_delivery": {"pace": "短促、克制"} if dialogue else None,
        "sound_design": {
            "ambience": "街巷晨风与远处晨鸡保持低声",
            "foley": "帘布摩擦和衣袖轻响",
            "action_sound": "指节推动帘边时发出一次轻响",
        },
    }


def h3_unit(*, dialogue="", transitions=False):
    unit = {
        "unit_id": "E45-VU-TEST",
        "model": "MiniMax-H3",
        "duration_seconds": 6,
        "aspect_ratio": "9:16",
        "resolution": "768p",
        "ordered_prompt_specs": [h3_spec(dialogue=dialogue)],
        "reference_images": [
            {"path": "first.png", "role": "ADMITTED_SCENE_START_STATE"},
            {"path": "last.png", "role": "NON_INTERPOLABLE_RESULT_STATE"},
        ],
        "camera_plan": {
            "shot_scale": "MEDIUM_CLOSE_UP",
            "motion_family": "DOLLY",
            "motion_direction": "PUSH_IN",
        },
        "internal_transition_contracts": [],
        "wardrobe_contract": {
            "schema": "qingshan.wardrobe_identity_contract.v1_role_and_peer_distinction",
            "characters": [{
                "character": "白鲤", "social_tier": "ARISTOCRATIC_AGENT",
                "role_basis": "世家出身且独立行动的年轻女主角",
                "silhouette": "窄肩长线条、外披短斗篷",
                "outer_layer": "象牙白暗纹轻绸交领长衫",
                "inner_layer": "浅青细绢窄袖内衫", "primary_color": "象牙白",
                "secondary_color": "浅青与一点朱红", "material": "轻绸与细绢",
                "pattern": "仅领缘有低对比水波暗纹", "belt_or_fastening": "朱红细绦系带",
                "footwear": "深青软底短靴", "accessory": "单枚红玉坠",
                "condition": "洁净但下摆带一线旅尘", "continuity_key": "BAILI-IVORY-CELADON-V1",
            }],
        },
    }
    if transitions:
        unit["incoming_transition_contract"] = {
            "incoming_handle_seconds": 0.8,
            "target_initial_state": {"blocking": "帘边仍被手指顶住"},
        }
        unit["outgoing_transition_contract"] = {
            "outgoing_handle_seconds": 1.0,
            "source_terminal_state": {"blocking": "帘布停在一侧，目光落在门口"},
            "sound_bridge": "晨风和帘布声连续进入下一段",
        }
    if dialogue:
        attach_speaker_voice_contract(unit, {"characters": [{
            "character": "白鲤",
            "entity_id": "baili",
            "status": "LOCKED_PRODUCTION_READY",
            "remote_asset_id": "test-baili-voice",
            "remote_url": "https://example.invalid/baili.wav",
        }]})
    return unit


class VideoPromptCompilerTest(unittest.TestCase):
    def test_router_keeps_seedance_on_unchanged_compiler(self):
        unit = {"model": "seedance-2.0-pro"}
        with patch("tools.video_prompt_compiler.compile_seedance_prompt", return_value="sd2-exact") as compile_sd2:
            self.assertEqual(compile_model_prompt(unit, [{"id": "memory"}]), "sd2-exact")
            compile_sd2.assert_called_once_with(unit, [{"id": "memory"}])

    def test_model_families_route_independently(self):
        self.assertEqual(model_family("seedance-2.0-pro"), "seedance2")
        self.assertEqual(model_family("MiniMax-H3"), "minimax-h3")
        with self.assertRaises(ValueError):
            model_family("seedance-2.0-fast")

    def test_seedance_compiler_fails_closed_for_h3(self):
        with self.assertRaisesRegex(ValueError, "video_prompt_compiler"):
            seedance_prompt_text(h3_unit())

    def test_h3_dialogue_is_the_only_speakable_text(self):
        unit = h3_unit(dialogue="白鲤：陈迹。")
        text = compile_h3_prompt(unit)
        report = validate_model_prompt_for_model(
            text, model="MiniMax-H3", source_id=unit["unit_id"], unit=unit
        )

        self.assertEqual(report["status"], "PASS", report["failures"])
        self.assertEqual(report["policy"], H3_MODEL_PROMPT_POLICY_VERSION)
        self.assertEqual(text.count("<d>[Chinese] 陈迹。</d>"), 1)
        self.assertEqual(text.count("陈迹。"), 1)
        self.assertNotIn("白鲤：", text)
        self.assertNotIn("“", text)
        self.assertNotIn("【节拍】", text)
        self.assertIn("白鲤（S1）", text)
        self.assertIn("@音频1：白鲤的已登记固定声线参考", text)
        self.assertIn("H3发声实体锁：", text)
        self.assertIn("服装身份锁：", text)
        self.assertIn("象牙白", text)
        self.assertIn("唯一的人声事件是上述<d>标签内的逐字内容", text)
        self.assertIn("overall_soundscape:", text)
        self.assertIn("non_diegetic_music:\nN/A", text)

    def test_h3_dialogue_fails_closed_without_speaker_voice_contract(self):
        unit = h3_unit(dialogue="白鲤：陈迹。")
        unit.pop("speaker_voice_contract")
        with self.assertRaisesRegex(ValueError, "SPEAKER_VOICE_CONTRACT"):
            compile_h3_prompt(unit)

    def test_h3_silent_unit_explicitly_closes_mouths(self):
        unit = h3_unit()
        text = compile_h3_prompt(unit)
        report = validate_h3_prompt(text, source_id=unit["unit_id"], unit=unit)

        self.assertEqual(report["status"], "PASS", report["failures"])
        self.assertNotIn("<d>", text)
        self.assertIn("本段没有人声事件；所有人物全程闭口", text)

    def test_h3_contact_action_binds_limb_ownership_and_occlusion_topology(self):
        unit = h3_unit()
        action = unit["ordered_prompt_specs"][0]["action"]
        action.update({
            "start_state": "陈迹右手尚未接触门闩",
            "primary_action": "陈迹右手抬起门闩",
            "completion_state": "陈迹右手仍连接右臂并停在门闩内侧",
        })
        text = compile_h3_prompt(unit)
        self.assertIn("肢体与接触拓扑硬锁", text)
        self.assertIn("肩→上臂→肘→前臂→腕→手掌→手指", text)
        self.assertIn("不得从门板、墙体、桌柜、衣物或画外凭空长出", text)

    def test_h3_combat_uses_real_motion_contract_not_reference_tableaux(self):
        unit = h3_unit()
        unit["ordered_prompt_specs"][0]["action"].update({
            "start_state": "刀仍在袭击者袖中，双方相距一步",
            "primary_action": "袭击者短刀直刺，白鲤侧步格挡并反扣手腕",
            "completion_state": "短刀落地，袭击者手腕被扣在身后",
        })
        text = compile_h3_prompt(unit)
        self.assertIn("打斗镜头语言硬合同", text)
        self.assertIn("不把参考图之间的姿势当作静态幻灯片", text)
        self.assertIn("state_target_only_no_pose_hold", text)
        self.assertNotIn("动作完成后维持该身体与道具状态", text)

    def test_h3_transition_contract_is_serialized_as_semantics_not_ids(self):
        unit = h3_unit(transitions=True)
        text = compile_h3_prompt(unit)

        self.assertIn("开场前0.8秒承接上一视频单元", text)
        self.assertIn("结尾最后1秒完成并保持", text)
        self.assertNotIn("BND-", text)
        self.assertEqual(
            validate_h3_prompt(text, source_id=unit["unit_id"], unit=unit)["status"],
            "PASS",
        )

    def test_h3_internal_transition_rows_bind_in_exact_shot_order(self):
        unit = h3_unit()
        unit["ordered_prompt_specs"] = [h3_spec(), h3_spec(), h3_spec()]
        unit["internal_transition_contracts"] = [
            {
                "boundary_id": "INT-ONE-TWO",
                "transition_mode": "MATCH_CUT",
                "action_bridge": "FIRST_UNIQUE_ACTION_BRIDGE",
            },
            {
                "boundary_id": "INT-TWO-THREE",
                "transition_mode": "MOTIVATED_CUT",
                "action_bridge": "SECOND_UNIQUE_ACTION_BRIDGE",
            },
        ]

        text = compile_h3_prompt(unit)
        shot_two = text.index("[Shot 2]")
        shot_three = text.index("[Shot 3]")

        self.assertLess(shot_two, text.index("FIRST_UNIQUE_ACTION_BRIDGE"))
        self.assertLess(text.index("FIRST_UNIQUE_ACTION_BRIDGE"), shot_three)
        self.assertLess(shot_three, text.index("SECOND_UNIQUE_ACTION_BRIDGE"))
        self.assertEqual(text.count("FIRST_UNIQUE_ACTION_BRIDGE"), 1)
        self.assertEqual(text.count("SECOND_UNIQUE_ACTION_BRIDGE"), 1)
        self.assertEqual(
            validate_h3_prompt(text, source_id=unit["unit_id"], unit=unit)["status"],
            "PASS",
        )

    def test_h3_validator_rejects_seedance_grammar_and_unisolated_dialogue(self):
        unit = h3_unit(dialogue="白鲤：陈迹。")
        bad = compile_h3_prompt(unit).replace(
            "<d>[Chinese] 陈迹。</d>", "陈迹。"
        ) + "\n【节拍】白鲤：陈迹。\n"
        report = validate_h3_prompt(bad, source_id=unit["unit_id"], unit=unit)

        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("H3_CONTAINS_SD2_PROMPT_MARKER" in row for row in report["failures"]))
        self.assertTrue(any("H3_DIALOGUE_TAG_CONTENT_MISMATCH" in row for row in report["failures"]))
        self.assertTrue(any("H3_SPEAKER_COLON_OUTSIDE_DIALOGUE" in row for row in report["failures"]))

    def test_h3_strips_speakable_action_scaffolding(self):
        unit = h3_unit(dialogue="白鲤：陈迹。")
        unit["ordered_prompt_specs"][0]["action"]["start_state"] = "说这句时她的手指顶住帘边"
        unit["ordered_prompt_specs"][0]["action"]["completion_state"] = (
            "说这句时帘布停在一侧，白鲤的目光落在门口，保持为本镜头结果"
        )
        text = compile_h3_prompt(unit)

        self.assertNotIn("说这句时", text)
        self.assertNotIn("本镜头结果", text)
        self.assertIn("她的手指顶住帘边", text)
        self.assertEqual(validate_h3_prompt(text, source_id=unit["unit_id"], unit=unit)["status"], "PASS")

    def test_h3_validator_rejects_speakable_meta_outside_dialogue(self):
        unit = h3_unit(dialogue="白鲤：陈迹。")
        text = compile_h3_prompt(unit) + "\n保持为本镜头结果。"
        report = validate_h3_prompt(text, source_id=unit["unit_id"], unit=unit)
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("H3_SPEAKABLE_META_OUTSIDE_DIALOGUE" in row for row in report["failures"]))

    def test_h3_speech_isolation_repair_profile_is_terse_and_dialogue_bounded(self):
        unit = h3_unit(dialogue="白鲤：陈迹。", transitions=True)
        unit["h3_prompt_profile"] = H3_SPEECH_ISOLATION_REPAIR_PROFILE
        text = compile_model_prompt(unit)
        report = validate_model_prompt_for_model(
            text, model="MiniMax-H3", source_id=unit["unit_id"], unit=unit
        )

        self.assertEqual(report["status"], "PASS", report["failures"])
        self.assertIn("【唯一可发声台词】", text)
        self.assertIn("“陈迹。”", text)
        self.assertEqual(text.count("陈迹。"), 1)
        self.assertIn("结尾最后1秒停止说话", text)
        self.assertNotIn("白鲤掀开车帘并看向门口", text)
        self.assertLess(len(text), 2400)

    def test_h3_minimal_audio_rescue_has_one_literal_dialogue_and_tiny_surface(self):
        unit = h3_unit(dialogue="白鲤：陈迹。", transitions=True)
        unit["h3_prompt_profile"] = H3_MINIMAL_AUDIO_RESCUE_PROFILE
        text = compile_model_prompt(unit)
        report = validate_model_prompt_for_model(
            text, model="MiniMax-H3", source_id=unit["unit_id"], unit=unit
        )

        self.assertEqual(report["status"], "PASS", report["failures"])
        self.assertEqual(text.count("陈迹。"), 1)
        self.assertIn("白鲤（克制自然）：“陈迹。”", text)
        self.assertIn(H3_ANTI_CAPTION_CLAUSE, text)
        self.assertNotIn("【声音隔离】", text)
        self.assertLess(len(text), 700)

    def test_h3_all_profiles_fail_closed_without_zero_text_frame_contract(self):
        for profile in (None, H3_SPEECH_ISOLATION_REPAIR_PROFILE, H3_MINIMAL_AUDIO_RESCUE_PROFILE):
            unit = h3_unit(dialogue="白鲤：陈迹。", transitions=True)
            if profile:
                unit["h3_prompt_profile"] = profile
            text = compile_model_prompt(unit)
            weakened = text.replace(H3_ANTI_CAPTION_CLAUSE, "画面尽量不要有字幕")
            report = validate_model_prompt_for_model(
                weakened, model="MiniMax-H3", source_id=unit["unit_id"], unit=unit
            )
            self.assertEqual(report["status"], "FAIL", profile)
            self.assertTrue(any("CAPTION" in failure or "VISIBLE_TEXT" in failure for failure in report["failures"]))

    def test_h3_adult_female_visual_is_explicitly_adult_and_model_specific(self):
        unit = h3_unit()
        row = unit["wardrobe_contract"]["characters"][0]
        row["gender_presentation"] = "FEMALE"
        row["adult_status"] = "CONFIRMED_ADULT"
        text = compile_h3_prompt(unit)
        self.assertIn("成年女性造型锁（仅H3）", text)
        self.assertIn("成熟丰满且比例自然", text)
        self.assertIn("胸腰臀曲线比默认造型更鲜明但不夸张", text)

        row["adult_status"] = "AGE_AMBIGUOUS"
        self.assertEqual(h3_adult_female_visual_block(unit), "")
        self.assertNotIn("成年女性造型锁（仅H3）", compile_h3_prompt(unit))

    def test_adult_female_visual_contract_is_shared_with_h3_stills_only(self):
        unit = h3_unit()
        row = unit["wardrobe_contract"]["characters"][0]
        row["gender_presentation"] = "女性"
        row["adult_status"] = "明确成年"

        self.assertIn(
            "成熟丰满",
            model_specific_adult_female_visual_block(
                unit, target_video_model="MiniMax-H3"
            ),
        )
        self.assertEqual(
            model_specific_adult_female_visual_block(
                unit, target_video_model="seedance-2.0-pro"
            ),
            "",
        )

    def test_h3_adult_female_visual_rejects_explicit_direction(self):
        unit = h3_unit()
        row = unit["wardrobe_contract"]["characters"][0]
        row.update({
            "gender_presentation": "FEMALE",
            "adult_status": "CONFIRMED_ADULT",
            "mature_visual_direction": "全裸色情造型",
        })
        with self.assertRaisesRegex(ValueError, "H3_ADULT_FEMALE_EXPLICIT_VISUAL_FORBIDDEN"):
            compile_h3_prompt(unit)


if __name__ == "__main__":
    unittest.main()
