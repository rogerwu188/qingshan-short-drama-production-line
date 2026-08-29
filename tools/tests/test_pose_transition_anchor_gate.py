import unittest

from tools.pose_transition_anchor_gate import evaluate


class PoseTransitionAnchorGateTest(unittest.TestCase):
    def test_standing_to_squat_without_result_anchor_fails(self):
        unit = {
            "unit_id": "VU010",
            "ordered_prompt_specs": [{"action": {
                "start_state": "陈迹直立抹墙", "completion_state": "陈迹半蹲马步停住",
            }}],
            "reference_images": [{"role": "ADMITTED_SCENE_START_STATE"}],
        }
        self.assertEqual(evaluate(unit)["status"], "FAIL")

    def test_pose_change_with_terminal_anchor_passes(self):
        unit = {
            "unit_id": "VU010",
            "ordered_prompt_specs": [{"action": {
                "start_state": "陈迹直立抹墙", "completion_state": "陈迹半蹲马步停住",
            }}],
            "reference_images": [
                {"role": "ADMITTED_SCENE_START_STATE"},
                {"role": "NON_INTERPOLABLE_RESULT_STATE"},
            ],
        }
        self.assertEqual(evaluate(unit)["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
