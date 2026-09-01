import unittest

from tools.sd2_background_ecology_contract import (
    build_background_ecology_contract,
    build_weather_visibility_contract,
    compile_background_ecology_prompt_block,
)


def spec(*, weather, cast, primary, action, motion=None, kind="DIALOGUE"):
    return {
        "scene_state": {
            "weather": weather,
            "weather_provenance": {
                "source_type": "TEST_SOURCE", "source_ref": "TEST-SCENE",
                "visibility_mode": "AUTHORED",
            },
        },
        "cast": [{"character": name} for name in cast],
        "role_semantic_disambiguation": {"primary_actor": primary},
        "action": {"primary_action": action, "action_kind": kind},
        "visual_design": {"environmental_motion": motion or ["烛焰低幅摆动"]},
        "ambient_life": {
            "grade": "A", "motion_trend": "前中后景错峰微动",
            "first_frame_state": "首帧所有可见实体已在动作中",
            "reaction_progression": "主事件发生后背景依次反应并保持",
        },
    }


class Sd2BackgroundEcologyContractTest(unittest.TestCase):
    def test_group_is_split_into_asynchronous_depth_cohorts(self):
        unit = {"ordered_prompt_specs": [spec(
            weather="夜，街面干燥", cast=["陈迹", "围观人群"], primary="陈迹",
            action="陈迹走进人群", motion=["前景衣摆与后景灯焰不同步微动"],
        )]}
        contract = build_background_ecology_contract(unit)
        block = compile_background_ecology_prompt_block(contract)
        self.assertEqual(contract["status"], "PASS")
        self.assertEqual(contract["grade"], "A")
        self.assertIn("近层", block)
        self.assertIn("中层", block)
        self.assertIn("远层", block)
        self.assertIn("错峰", block)
        self.assertIn("不冻结", block)

    def test_dry_interior_keeps_rain_offscreen(self):
        unit = {"ordered_prompt_specs": [spec(
            weather="雨夜；雨声隔着窗纸从北面来，屋里干燥、闷，灯焰不动",
            cast=["陈迹"], primary="陈迹", action="陈迹折纸",
        )]}
        contract = build_weather_visibility_contract(unit)
        self.assertEqual(contract["mode"], "OFFSCREEN_AUDIBLE_ONLY")
        self.assertIn("画内禁止雨丝", contract["prompt"])

    def test_dry_interior_threshold_limits_visible_rain(self):
        unit = {"ordered_prompt_specs": [spec(
            weather="雨夜；厅里干燥，雨声只从大门一侧进来",
            cast=["来人"], primary="来人", action="大门被踹开，来人跨过门槛",
        )]}
        contract = build_weather_visibility_contract(unit)
        self.assertEqual(contract["mode"], "THRESHOLD_INTRUSION_ONLY")
        self.assertIn("阈值", contract["prompt"])

    def test_no_rain_forbids_undeclared_weather_template(self):
        unit = {"ordered_prompt_specs": [spec(
            weather="晴日下午，庭院干燥", cast=["陈迹"], primary="陈迹", action="陈迹抬眼",
        )]}
        contract = build_weather_visibility_contract(unit)
        self.assertEqual(contract["mode"], "NO_UNDECLARED_WEATHER")
        self.assertIn("禁止自动添加雨", contract["prompt"])


if __name__ == "__main__":
    unittest.main()
