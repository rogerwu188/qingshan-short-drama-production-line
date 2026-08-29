import unittest

from tools.media_boundary_acceptance import DECISION_DOMAINS, evaluate_boundary_decision


class MediaBoundaryAcceptanceTest(unittest.TestCase):
    def test_missing_real_media_decision_fails_closed(self):
        self.assertEqual(evaluate_boundary_decision(None), ["REAL_MEDIA_VISUAL_DECISION_MISSING"])

    def test_all_continuity_domains_are_required(self):
        decision = {domain: "PASS" for domain in DECISION_DOMAINS}
        decision["reviewer"] = "codex-visual-review"
        self.assertEqual(evaluate_boundary_decision(decision), [])
        decision["pose_and_blocking_continuity"] = "FAIL"
        self.assertTrue(any("pose_and_blocking_continuity" in item for item in evaluate_boundary_decision(decision)))


if __name__ == "__main__":
    unittest.main()
