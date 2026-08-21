import unittest

from tools.human_realism_prompt_contract import (
    build_expression_realism_block,
    build_keyframe_realism_block,
    validate_human_realism_prompt,
)


class HumanRealismPromptContractTest(unittest.TestCase):
    def lock(self):
        return {
            "char_chenji": {
                "name": "陈迹",
                "immutable": {"age": "二十余岁", "gender": "男性"},
            }
        }

    def test_close_character_keyframe_has_real_optics_and_anti_plastic_detail(self):
        prompt = build_keyframe_realism_block(
            character_ids=["char_chenji"],
            character_locks=self.lock(),
            shot_scale="近景特写",
            lens_intent="克制肖像",
            action="陈迹听见门外脚步后抬眼",
            expression_arc="平静到警觉",
            eyeline_target="右前方门缝",
        )
        self.assertIn("85mm", prompt)
        self.assertIn("f/2", prompt)
        self.assertIn("毛孔", prompt)
        self.assertIn("不对称", prompt)
        self.assertIn("湿润反射", prompt)
        self.assertIn("塑料皮", prompt)
        self.assertIn("磨皮", prompt)
        self.assertEqual([], validate_human_realism_prompt(prompt))

    def test_wide_character_keyframe_preserves_spatial_scale(self):
        prompt = build_keyframe_realism_block(
            character_ids=["char_chenji"],
            character_locks=self.lock(),
            shot_scale="大远景",
            lens_intent="空间定场",
            action="陈迹穿过前厅",
        )
        self.assertIn("35mm", prompt)
        self.assertIn("f/4", prompt)
        self.assertIn("真实环境尺度", prompt)

    def test_expression_contract_is_stimulus_to_residual_performance_chain(self):
        prompt = build_expression_realism_block(
            expression_arc="怀疑到确认后仍保留戒备",
            action="对手递来沾霜纸片",
            framing="中近景",
        )
        for clause in ("动作", "视线", "下眼睑", "肩颈", "手指张力", "残余"):
            self.assertIn(clause, prompt)
        self.assertIn("AI式标准微笑", prompt)
        self.assertEqual([], validate_human_realism_prompt(prompt))

    def test_generic_beauty_prompt_fails_adopted_contract(self):
        failures = validate_human_realism_prompt("漂亮人物，电影感，高级光影")
        self.assertGreaterEqual(len(failures), 6)
        self.assertTrue(any(row["check"] == "skin_microtexture" for row in failures))


if __name__ == "__main__":
    unittest.main()
