import unittest

from tools.defect_tolerance_gate import evaluate


class DefectToleranceGateTests(unittest.TestCase):
    def test_single_middle_minor_within_budget_passes(self):
        report = {
            "episode": "E99", "shot_count": 20, "duration_seconds": 120,
            "defects": [{"severity": "MINOR", "scope": "SHOT", "shot_index": 10, "start_seconds": 50, "end_seconds": 54, "category": "wardrobe_detail"}],
        }
        self.assertEqual(evaluate(report)["status"], "PASS")

    def test_blocker_and_protected_zone_minor_fail(self):
        report = {
            "shot_count": 20, "duration_seconds": 120,
            "defects": [
                {"severity": "BLOCKER", "scope": "SHOT", "shot_index": 8, "category": "wrong_identity"},
                {"severity": "MINOR", "scope": "SHOT", "shot_index": 1, "start_seconds": 2, "end_seconds": 4, "category": "wardrobe_detail"},
            ],
        }
        result = evaluate(report)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any(item.startswith("minor_in_zero_tolerance_zone") for item in result["failures"]))

    def test_three_consecutive_same_minor_escalates(self):
        defects = [
            {"severity": "MINOR", "scope": "SHOT", "shot_index": index, "start_seconds": 30 + index, "end_seconds": 30.5 + index, "category": "same_artifact"}
            for index in (8, 9, 10)
        ]
        result = evaluate({"shot_count": 40, "duration_seconds": 120, "defects": defects})
        self.assertTrue(any(item.startswith("three_consecutive_same_minor_escalates") for item in result["failures"]))

    def test_conditional_admission_cannot_override_audience(self):
        result = evaluate({"shot_count": 20, "duration_seconds": 120, "defects": [], "conditional_admission_overrides": ["AUDIENCE_SCORE_PRE_RELEASE"]})
        self.assertIn("conditional_admission_cannot_override:AUDIENCE_SCORE_PRE_RELEASE", result["failures"])


if __name__ == "__main__":
    unittest.main()
