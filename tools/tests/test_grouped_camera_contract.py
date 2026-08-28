import copy
import unittest

from tools.grouped_camera_contract import (
    compile_camera_prompt,
    validate_camera_plan,
    validate_camera_sequence,
)


def track(direction="LEFT_TO_RIGHT"):
    return {
        "shot_scale": "MEDIUM_WIDE", "lens_intent": "35mm交代行进空间",
        "camera_height": "EYE_LEVEL", "camera_side": "AXIS_A",
        "axis_relation": "保持既定人物视线轴，不越轴",
        "motion_family": "TRACK", "motion_direction": direction,
        "start_framing": "人物进入通道", "end_framing": "人物抵达门边",
        "motivation": "只为保持人物真实行进及其空间终点连续可读",
    }


class GroupedCameraContractTest(unittest.TestCase):
    def test_compiles_explicit_direction_and_single_move_rule(self):
        text = compile_camera_prompt(track(), source_id="U1")
        self.assertIn("由画面左向右", text)
        self.assertIn("禁止反向复位或重复运动", text)

    def test_rejects_generic_follow_action_language(self):
        plan = track()
        plan["motivation"] = "镜头随主要动作平稳调整景别"
        with self.assertRaisesRegex(ValueError, "generic camera language"):
            validate_camera_plan(plan, source_id="U1")

    def test_rejects_adjacent_same_direction(self):
        units = [
            {"unit_id": "U1", "camera_plan": track()},
            {"unit_id": "U2", "camera_plan": copy.deepcopy(track())},
        ]
        with self.assertRaisesRegex(ValueError, "repeat camera motion"):
            validate_camera_sequence(units)


if __name__ == "__main__":
    unittest.main()
