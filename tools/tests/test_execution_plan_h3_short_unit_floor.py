import unittest
from unittest import mock

from tools import video_execution_plan_compiler as c


class H3ShortUnitFloorTest(unittest.TestCase):
    """E29 S5: the director's 2 s REACTION unit must pass the H3 duration check when HopsAPI takes 2 s."""

    def test_floor_follows_live_h3_limit(self):
        with mock.patch("tools.h3_limits.min_unit_seconds", return_value=2):
            self.assertEqual(c._h3_min_unit_seconds(), 2.0)

    def test_floor_never_above_historical_three(self):
        with mock.patch("tools.h3_limits.min_unit_seconds", return_value=4):
            self.assertEqual(c._h3_min_unit_seconds(), 3.0)

    def test_two_second_unit_not_rejected_for_duration(self):
        unit = {"unit_id": "E29-VU-023", "model": "minimax-h3", "duration_seconds": 2.0, "ordered_prompt_specs": []}
        model = next(k for k, v in c.MODEL_FAMILY_BY_NAME.items() if v == "MINIMAX_H3")
        unit["model"] = model
        unit["ordered_prompt_specs"] = [{"action": {"t0_seconds": 0, "t1_seconds": 2}}]
        with mock.patch("tools.h3_limits.min_unit_seconds", return_value=2):
            try:
                c.compile_video_execution_plan(unit, preproduction_only=True)
            except Exception as exc:  # later checks may reject this toy unit; only the duration gate matters
                self.assertNotIn("VIDEO_DURATION_OUT_OF_RANGE", str(exc))

    def test_one_second_unit_still_rejected(self):
        model = next(k for k, v in c.MODEL_FAMILY_BY_NAME.items() if v == "MINIMAX_H3")
        unit = {"unit_id": "U", "model": model, "duration_seconds": 1.0,
                "ordered_prompt_specs": [{"action": {"t0_seconds": 0, "t1_seconds": 1}}]}
        with mock.patch("tools.h3_limits.min_unit_seconds", return_value=2):
            with self.assertRaisesRegex(ValueError, "VIDEO_DURATION_OUT_OF_RANGE"):
                c.compile_video_execution_plan(unit, preproduction_only=True)


if __name__ == "__main__":
    unittest.main()
