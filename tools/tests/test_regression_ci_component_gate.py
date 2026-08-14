import unittest

from tools.regression_ci_component_gate import FROZEN_PROFILE, evaluate


class RegressionCiComponentGateTests(unittest.TestCase):
    def test_component_passes_only_from_actual_ci_component(self):
        result = evaluate(
            {"status": "PASS", "static_hold_gate": {"status": "PASS", "rows": []}},
            "FINAL-STATIC-HOLD",
        )
        self.assertEqual(result["status"], "PASS")

    def test_missing_component_fails_closed(self):
        self.assertEqual(evaluate({"status": "PASS"}, "FINAL-AUDIO-BED-CONTINUITY")["status"], "FAIL")

    def test_frozen_profile_rejects_drift(self):
        good = {
            "threshold_profile": FROZEN_PROFILE,
            "threshold_override_audit": {"status": "NOT_REQUESTED"},
        }
        self.assertEqual(evaluate(good, "FROZEN-THRESHOLD-PROFILE")["status"], "PASS")
        self.assertEqual(evaluate({**good, "threshold_profile": "changed"}, "FROZEN-THRESHOLD-PROFILE")["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
