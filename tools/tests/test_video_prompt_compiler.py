import unittest
from unittest.mock import patch

from tools.minimax_h3_prompt_compiler import (
    H3_MODEL_PROMPT_POLICY_VERSION,
    compile_h3_prompt,
    validate_h3_prompt,
)
from tools.compile_grouped_seedance_manifest import prompt_text as seedance_prompt_text
from tools.video_prompt_compiler import (
    compile_model_prompt,
    model_family,
    validate_model_prompt_for_model,
)


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
        self.assertIn("服装身份锁：", text)
        self.assertIn("象牙白", text)
        self.assertIn("唯一的人声事件是上述<d>标签内的逐字台词", text)
        self.assertIn("overall_soundscape:", text)
        self.assertIn("non_diegetic_music:\nN/A", text)

    def test_h3_silent_unit_explicitly_closes_mouths(self):
        unit = h3_unit()
        text = compile_h3_prompt(unit)
        report = validate_h3_prompt(text, source_id=unit["unit_id"], unit=unit)

        self.assertEqual(report["status"], "PASS", report["failures"])
        self.assertNotIn("<d>", text)
        self.assertIn("本段没有人声事件；所有人物全程闭口", text)

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


if __name__ == "__main__":
    unittest.main()
