import hashlib
import unittest

from tools.combat_action_library import (
    DEFAULT_LIBRARY,
    compile_binding_prompt,
    load_library,
    validate_binding,
)
from tools.minimax_h3_prompt_compiler import compile_h3_prompt
from tools.tests.test_video_prompt_compiler import h3_unit


class CombatActionLibraryTest(unittest.TestCase):
    def test_library_is_versioned_and_contains_user_trained_moves(self):
        library = load_library()
        self.assertEqual(library["schema"], "qingshan.combat_action_library.v1")
        self.assertGreaterEqual(len(library["moves"]), 22)
        names = {row["name_zh"] for row in library["moves"]}
        self.assertIn("极速瞬身突袭", names)
        self.assertIn("贴身缠斗快打", names)
        self.assertIn("两指夹刃卸力", names)
        self.assertIn("贴水兵器接触承重站稳", names)
        self.assertEqual(
            library["reference_lineage"]["status"],
            "INFERRED_RECONSTRUCTED_NOT_ORIGINAL",
        )
        self.assertEqual(library["sha256"], hashlib.sha256(DEFAULT_LIBRARY.read_bytes()).hexdigest())

    def test_binding_fails_closed_when_story_invention_is_not_forbidden(self):
        unit = {
            "combat_action_library_binding": {
                "schema": "qingshan.combat_action_library_binding.v1",
                "canonical_match": True,
                "canonical_action_source_sha256": "a" * 64,
                "move_ids": ["POWER_STRAIGHT_PUNCH"],
                "role_bindings": {
                    "initiator": "甲", "target": "乙", "weapon_or_prop_owner": "甲",
                    "winner": "甲", "loser": "乙",
                },
                "library_may_invent_story_action": True,
            }
        }
        report = validate_binding(unit)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("COMBAT_ACTION_LIBRARY_STORY_INVENTION_MUST_BE_FORBIDDEN", report["failures"])

    def test_h3_serializes_positive_physics_role_and_library_chain(self):
        unit = h3_unit()
        unit["ordered_prompt_specs"][0]["action"].update({
            "start_state": "元掌柜右手仍握袖中短刀，陈迹在门内相距一步",
            "primary_action": "元掌柜跨步直刺，陈迹侧移并以两指从刀尖侧面拦截",
            "completion_state": "元掌柜仍握刀柄，陈迹两指偏转刀尖，双方落到门槛两侧",
        })
        unit["combat_choreography_contract"] = {
            "initiator": "元掌柜",
            "objective": "右手持短刀直刺陈迹胸口",
            "spatial_axis": "元掌柜右肩—右肘—右腕—刀柄—刀尖—陈迹胸口",
            "causal_beats": [{
                "attack_intent": "元掌柜跨步送刀",
                "defense_response": "陈迹侧移并从刀尖侧面接近",
                "visible_consequence": "刀路偏出胸口",
                "end_state": "元掌柜仍握刀柄，陈迹两指接触刀尖",
            }],
            "terminal_state": {
                "winner": "陈迹", "loser": "元掌柜的首次刺击",
                "physical_result": "刀尖被偏转，人物与武器归属不变",
            },
        }
        unit["combat_action_library_binding"] = {
            "schema": "qingshan.combat_action_library_binding.v1",
            "canonical_match": True,
            "canonical_action_source_sha256": "b" * 64,
            "move_ids": ["GROUNDED_BLADE_LUNGE", "GROUNDED_TWO_FINGER_BLADE_INTERCEPT"],
            "role_bindings": {
                "initiator": "元掌柜", "target": "陈迹", "weapon_or_prop_owner": "元掌柜",
                "winner": "陈迹", "loser": "元掌柜的首次刺击",
            },
            "library_may_invent_story_action": False,
        }
        text = compile_h3_prompt(unit)
        self.assertIn("剧情专属物理链", text)
        self.assertIn("本场唯一初始发起者=元掌柜", text)
        self.assertIn("版本化打斗动作库绑定", text)
        self.assertIn("INFERRED_RECONSTRUCTED_NOT_ORIGINAL", text)
        self.assertIn("袖中短刀直刺/GROUNDED_BLADE_LUNGE", text)
        self.assertIn("两指夹刃卸力/GROUNDED_TWO_FINGER_BLADE_INTERCEPT", text)
        self.assertIn("动作库只翻译已授权剧情", text)
        self.assertIn("禁止字幕、UI、来源身份、IP名称和文字拟声", text)
        self.assertEqual(text.count(compile_binding_prompt(unit, model_family="minimax-h3")), 1)


if __name__ == "__main__":
    unittest.main()
