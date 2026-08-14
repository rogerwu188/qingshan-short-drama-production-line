import unittest

from tools.video_prompt_action_density_gate import validate_action_timeline


def segment(
    start,
    end,
    action="主体=陈迹；动作=跨步拔刀；接触点=右手与刀柄；方向=向前并向上；终态=刀身离鞘且刀尖朝向对手",
    result="刀身离鞘且陈迹重心落在前脚",
):
    return {
        "start_seconds": start,
        "end_seconds": end,
        "actions": [action],
        "state_change": result,
        "action_budget_seconds": end - start,
    }


class VideoPromptActionDensityGateTests(unittest.TestCase):
    def test_dense_contiguous_timeline_passes(self):
        report = validate_action_timeline(
            [segment(0, 2), segment(2, 4), segment(4, 6)],
            6,
            source_id="SHOT-1",
        )
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["action_budget_seconds"], 6)

    def test_empty_interval_is_blocked(self):
        report = validate_action_timeline(
            [{"start_seconds": 0, "end_seconds": 2, "actions": [], "state_change": "人物位置改变"}],
            2,
            source_id="SHOT-2",
        )
        self.assertIn("BLOCK_SUBMIT_ACTION_SEGMENT_EMPTY:SHOT-2:1", report["failures"])

    def test_static_placeholder_is_blocked(self):
        report = validate_action_timeline(
            [segment(0, 2, action="主体=陈迹；动作=先稳定站位；接触点=双脚与地面；方向=原地；终态=仍在原位")],
            2,
            source_id="SHOT-3",
        )
        self.assertIn("BLOCK_SUBMIT_ACTION_PLACEHOLDER:SHOT-3:1:稳定站位", report["failures"])

    def test_generic_motion_without_physics_fields_is_blocked(self):
        report = validate_action_timeline(
            [segment(0, 2, action="人物跨步拔刀")],
            2,
            source_id="SHOT-GENERIC",
        )
        self.assertTrue(any(item.startswith("BLOCK_SUBMIT_ACTION_PHYSICS_FIELD_MISSING:SHOT-GENERIC:1") for item in report["failures"]))

    def test_duration_above_budget_is_blocked(self):
        row = segment(0, 3)
        row["action_budget_seconds"] = 2
        report = validate_action_timeline([row], 3, source_id="SHOT-4")
        self.assertIn("BLOCK_SUBMIT_DURATION_EXCEEDS_ACTION_BUDGET:SHOT-4:3.000>2.000", report["failures"])

    def test_gap_and_overlong_interval_are_blocked(self):
        report = validate_action_timeline(
            [segment(0, 2), segment(2.5, 6)],
            6,
            source_id="SHOT-5",
        )
        self.assertTrue(any(item.startswith("BLOCK_SUBMIT_ACTION_TIMELINE_GAP_OR_OVERLAP:SHOT-5:2") for item in report["failures"]))
        self.assertIn("BLOCK_SUBMIT_ACTION_SEGMENT_TOO_LONG:SHOT-5:2:3.500", report["failures"])


if __name__ == "__main__":
    unittest.main()
