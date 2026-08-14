import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.build_remote_generation_credit_ledger import build


class RemoteGenerationCreditLedgerTests(unittest.TestCase):
    def test_legacy_success_and_failure_are_backfilled_without_estimation(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "receipt.json").write_text(
                json.dumps(
                    {
                        "episode": "E28",
                        "tasks": [
                            {"task_key": "pass", "tool_type": "video_generation", "task_id": "a", "state": "qa_pass", "submit_response": {"data": {"credit_cost": 135}}},
                            {"task_key": "fail", "tool_type": "video_generation", "task_id": "b", "state": "remote_failed_terminal", "submit_response": {"data": {"credit_cost": 135}}},
                            {"task_key": "unknown", "tool_type": "image_generation", "task_id": "c", "state": "image_pass", "submit_response": {"data": {"task_id": "c"}}},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            report = build(root)

        self.assertEqual(report["attempt_count"], 3)
        self.assertEqual(report["actual_credits_known_total"], 135)
        self.assertFalse(report["actual_total_complete"])
        self.assertEqual(report["episodes"]["E28"]["failed_zero_charge_count"], 1)
        self.assertEqual(report["episodes"]["E28"]["unknown_success_count"], 1)

    def test_local_qa_failure_after_completed_video_is_still_a_paid_success(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "receipt.json").write_text(
                json.dumps(
                    {
                        "episode": "E27",
                        "tasks": [
                            {
                                "task_key": "qa-fail",
                                "tool_type": "video_generation",
                                "task_id": "paid-output",
                                "state": "qa_failed_terminal",
                                "remote_status": "completed",
                                "output_path": "/tmp/generated.mp4",
                                "submit_response": {
                                    "data": {"task_id": "paid-output", "credit_cost": 135}
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            report = build(root)

        self.assertTrue(report["actions"][0]["success"])
        self.assertEqual(report["actions"][0]["actual_charged_credits"], 135)


if __name__ == "__main__":
    unittest.main()
