import unittest

from tools.pacing_style_gate import evaluate


class PacingStyleGateTests(unittest.TestCase):
    def ci(self):
        return {
            "static_hold_gate": {"status": "PASS"},
            "freeze": {"freeze_ratio": 0.01},
            "frame_repeat": {"near_duplicate_ratio": 0.02},
            "thresholds": {"freeze_ratio_max": 0.03, "near_duplicate_ratio_max": 0.10},
        }

    def test_motivated_native_cadence_passes(self):
        plan = {"segments": [
            {"source_id": "S1", "duration_sec": 1.8, "is_insert": True},
            {"source_id": "S2", "duration_sec": 7.0, "long_take_motivation": "完整对白与权力反转不中断"},
        ]}
        self.assertEqual(evaluate(self.ci(), plan)["status"], "PASS")

    def test_long_insert_and_retime_fail(self):
        plan = {"segments": [{"source_id": "S1", "duration_sec": 3.0, "is_insert": True, "speed_factor": 0.8}]}
        result = evaluate(self.ci(), plan)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("insert_duration_exceeds_2s" in item for item in result["failures"]))
        self.assertTrue(any("retime_or_slow_motion_forbidden" in item for item in result["failures"]))


if __name__ == "__main__":
    unittest.main()
