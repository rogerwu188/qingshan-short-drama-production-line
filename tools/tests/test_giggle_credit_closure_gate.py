import unittest

from tools.giggle_credit_closure_gate import validate


def ledger():
    return {
        "schema": "qingshan.giggle_credit_ledger.v1",
        "submitted_task_count": 2,
        "image_task_count": 1,
        "video_task_count": 1,
        "unknown_media_task_count": 0,
        "actual_credits_total": "PENDING_ACCOUNT_RECONCILIATION",
        "balance_before": None,
        "balance_after": None,
        "tasks": [
            {"task_id": "A", "media_type": "image"},
            {"task_id": "B", "media_type": "video"},
        ],
    }


class GiggleCreditClosureGateTests(unittest.TestCase):
    def test_task_count_backfill_passes_without_credit_closure(self):
        self.assertEqual(validate(ledger())["status"], "PASS")

    def test_release_finance_closure_requires_actual_credits(self):
        report = validate(ledger(), require_actual_credits=True)
        self.assertIn("actual_credits_total_not_reconciled", report["failures"])

    def test_verified_balance_delta_passes(self):
        payload = ledger()
        payload.update(
            {
                "actual_credits_total": 120,
                "balance_before": 1000,
                "balance_after": 880,
            }
        )
        self.assertEqual(validate(payload, require_actual_credits=True)["status"], "PASS")

    def test_rejects_count_or_balance_mismatch(self):
        payload = ledger()
        payload.update(
            {
                "submitted_task_count": 3,
                "actual_credits_total": 100,
                "balance_before": 1000,
                "balance_after": 850,
            }
        )
        report = validate(payload, require_actual_credits=True)
        self.assertIn("submitted_task_count_mismatch:3:2", report["failures"])
        self.assertIn("balance_delta_does_not_match_actual_credits", report["failures"])


if __name__ == "__main__":
    unittest.main()
