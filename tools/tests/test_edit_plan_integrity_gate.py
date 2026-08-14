import unittest

from tools.edit_plan_integrity_gate import evaluate_plan_rows, renderer_source_failures


class EditPlanIntegrityGateTests(unittest.TestCase):
    def test_normal_timestamp_reset_is_allowed(self):
        self.assertEqual(renderer_source_failures("setpts=PTS-STARTPTS"), [])

    def test_speed_change_and_interpolation_are_rejected(self):
        failures = renderer_source_failures("setpts=1.2*PTS,minterpolate=fps=30")
        self.assertIn("forbidden_renderer_operation:setpts_speed_change", failures)
        self.assertIn("forbidden_renderer_operation:frame_interpolation", failures)

    def test_source_overrun_and_fps_mismatch_are_rejected(self):
        failures = evaluate_plan_rows(
            [
                {
                    "source_id": "A",
                    "in_sec": 5.0,
                    "duration_sec": 6.0,
                    "source_duration_sec": 10.0,
                    "source_fps": 24.0,
                }
            ],
            30.0,
        )
        self.assertTrue(any(item.startswith("source_window_exceeds_media:A") for item in failures))
        self.assertTrue(any(item.startswith("target_source_fps_mismatch:A") for item in failures))


if __name__ == "__main__":
    unittest.main()
