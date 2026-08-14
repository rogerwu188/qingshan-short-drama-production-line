import unittest

from tools.release_signoff_integrity_gate import evaluate_release_signoff


class ReleaseSignoffIntegrityGateTests(unittest.TestCase):
    def test_watch_cannot_override_ci_fail(self):
        result = evaluate_release_signoff(
            "E18",
            {"status": "FAIL", "failures": ["motion_redline"]},
            {"status": "PASS_WITH_WARNINGS"},
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("ci_fail_cannot_be_overridden_by_watch_gate", result["failures"])

    def test_watch_can_reject_ci_pass(self):
        result = evaluate_release_signoff(
            "E18",
            {"status": "PASS", "failures": []},
            {"status": "FAIL"},
        )
        self.assertEqual(result["status"], "FAIL")

    def test_verified_roger_override_is_accepted(self):
        result = evaluate_release_signoff(
            "E18",
            {"status": "FAIL", "failures": ["motion_redline"]},
            {"status": "PASS_WITH_WARNINGS"},
            override_ref="ROGER-18",
            audit_text="## [ROGER-18] E18 release override\nRoger approved the E18 CI override.",
        )
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["roger_override_verified"])


if __name__ == "__main__":
    unittest.main()
