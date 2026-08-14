import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tools import submit_giggle_task_manifest as submitter


class SubmitGiggleVideoGenerationGuardTest(unittest.TestCase):
    def test_blocked_credit_gate_stops_before_duplicate_scan(self):
        gate = {
            "status": "BLOCKED_VIDEO_CREDIT_LIMIT_EXCEEDED",
            "actual_charged_credits_known_total": 51024,
            "effective_limit_credits": 5000,
        }
        with TemporaryDirectory() as tmp:
            report = Path(tmp) / "gate.json"
            with (
                patch.object(submitter, "evaluate_episode_credit_gate", return_value=gate),
                patch.object(submitter, "credit_report_path", return_value=report),
                patch.object(submitter, "find_existing_paid_candidate") as find_existing,
            ):
                observed, failures = submitter.evaluate_video_submission_guards(
                    {"episode": "E28"},
                    [{"source_id": "U09", "prompt_path": "prompt.txt", "reference_images": []}],
                )

        self.assertEqual(observed, gate)
        self.assertIn("actual=51024", failures[0])
        find_existing.assert_not_called()

    def test_passing_gate_adds_fingerprint_and_blocks_exact_duplicate(self):
        gate = {
            "status": "PASS",
            "actual_charged_credits_known_total": 100,
            "effective_limit_credits": 5000,
        }
        task = {"source_id": "U01", "prompt_path": "prompt.txt", "reference_images": []}
        with TemporaryDirectory() as tmp:
            report = Path(tmp) / "gate.json"
            with (
                patch.object(submitter, "evaluate_episode_credit_gate", return_value=gate),
                patch.object(submitter, "credit_report_path", return_value=report),
                patch.object(submitter, "generation_fingerprint", return_value="fingerprint"),
                patch.object(
                    submitter,
                    "find_existing_paid_candidate",
                    return_value={"task_id": "paid-existing"},
                ),
            ):
                _, failures = submitter.evaluate_video_submission_guards(
                    {"episode": "E29"}, [task]
                )

        self.assertEqual(task["generation_fingerprint"], "fingerprint")
        self.assertIn("task_id=paid-existing", failures[0])

    def test_video_manifest_requires_explicit_episode(self):
        gate, failures = submitter.evaluate_video_submission_guards(
            {}, [{"source_id": "U01"}]
        )
        self.assertIsNone(gate)
        self.assertEqual(failures, ["FAIL_VIDEO_CREDIT_GATE:EPISODE_REQUIRED"])


if __name__ == "__main__":
    unittest.main()
