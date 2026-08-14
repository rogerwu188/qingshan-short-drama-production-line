import unittest

from tools.shot_space_camera_constraint_gate import evaluate_task


class ShotSpaceCameraConstraintGateTest(unittest.TestCase):
    def cross_task(self):
        return {
            "task_key": "U04-A2",
            "prompt_contract": {
                "source_action": "阴神穿窗掠过雨城并抵达西市暗楼窗外",
                "spatial_continuity": {
                    "mode": "CROSS_SPACE_TRANSITION",
                    "policy_source": "PER_UNIT_SCRIPT_CONTENT",
                    "origin_scene_id": "medical-hall",
                    "destination_scene_id": "west-market-tower",
                    "anchor_scope": "DESTINATION_REANCHOR",
                },
            },
            "reference_bindings": [
                {"role": "destination_scene", "entity_id": "west-market-tower"}
            ],
        }

    def test_cross_space_same_scene_lock_is_rejected(self):
        result = evaluate_task(self.cross_task(), "保持同场景同机位，阴神抵达暗楼")
        self.assertEqual(result["status"], "FAIL")
        self.assertIn(
            "CROSS_SPACE_LOCKED_TO_ORIGIN_SCENE_OR_CAMERA",
            [row["code"] for row in result["failures"]],
        )

    def test_cross_space_destination_anchor_passes(self):
        result = evaluate_task(self.cross_task(), "允许切换到西市暗楼外的新机位")
        self.assertEqual(result["status"], "PASS")

    def test_cross_action_cannot_be_declared_same_space(self):
        task = self.cross_task()
        task["prompt_contract"]["spatial_continuity"] = {
            "mode": "SAME_SPACE_CONTINUOUS",
            "policy_source": "PER_UNIT_SCRIPT_CONTENT",
        }
        result = evaluate_task(task, "连续动作")
        self.assertEqual(result["status"], "FAIL")
        self.assertIn(
            "AUTHORED_CROSS_SPACE_ACTION_MISCLASSIFIED_AS_SAME_SPACE",
            [row["code"] for row in result["failures"]],
        )


if __name__ == "__main__":
    unittest.main()
