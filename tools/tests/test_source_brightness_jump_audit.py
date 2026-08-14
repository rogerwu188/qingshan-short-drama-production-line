import unittest
from unittest.mock import Mock, patch

from tools.run_regression_ci import source_brightness_audit_stats
from tools.source_brightness_jump_audit import FRAME_SIZE, audit, validate_threshold


class SourceBrightnessJumpAuditTests(unittest.TestCase):
    @patch("tools.source_brightness_jump_audit.subprocess.run")
    def test_rejects_day_night_jump(self, run):
        run.return_value = Mock(
            returncode=0,
            stdout=bytes([30]) * FRAME_SIZE + bytes([90]) * FRAME_SIZE,
            stderr=b"",
        )
        report = audit(Mock(), Mock(), 25.0)
        self.assertEqual(report["status"], "FAIL_BRIGHTNESS_JUMP")

    @patch("tools.source_brightness_jump_audit.subprocess.run")
    def test_accepts_stable_source(self, run):
        run.return_value = Mock(
            returncode=0,
            stdout=bytes([40]) * FRAME_SIZE + bytes([50]) * FRAME_SIZE,
            stderr=b"",
        )
        report = audit(Mock(), Mock(), 25.0)
        self.assertEqual(report["status"], "PASS")

    def test_rejects_relaxed_threshold(self):
        self.assertEqual(validate_threshold(25.0), [])
        self.assertTrue(validate_threshold(25.01))

    def test_regression_ci_rejects_missing_or_relaxed_audits(self):
        missing = source_brightness_audit_stats([], required=True)
        self.assertEqual(missing["status"], "FAIL")
        relaxed = source_brightness_audit_stats(
            [{"status": "PASS", "fail_threshold": 30.0, "video": "source.mp4"}],
            required=True,
        )
        self.assertIn(
            "source_brightness_threshold_relaxed:0:30.000",
            relaxed["failures"],
        )


if __name__ == "__main__":
    unittest.main()
