import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from giggle_credit_statements import parse_utc, reconcile_rows  # noqa: E402


class CreditStatementTests(unittest.TestCase):
    def test_parse_utc_accepts_compact_local_offset(self):
        parsed = parse_utc("2026-07-23T05:42:46-0700")
        self.assertEqual(parsed, datetime(2026, 7, 23, 12, 42, 46, tzinfo=timezone.utc))

    def test_exact_image_batch_sums_authoritative_credits(self):
        rows = [
            {
                "event_type": "Pay",
                "event_description": "SingleGenerateImage",
                "credit": "-11",
                "created_at": f"2026-07-21 21:03:{second:02d}",
                "model": "gpt-image-2-pro",
            }
            for second in (27, 31, 39)
        ]
        result = reconcile_rows(
            rows,
            start=datetime(2026, 7, 21, 21, 3, 20, tzinfo=timezone.utc),
            end=datetime(2026, 7, 21, 21, 3, 45, tzinfo=timezone.utc),
            expected_count=3,
            event_description="SingleGenerateImage",
            model="gpt-image-2-pro",
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["charged_credits"], 33)

    def test_count_mismatch_is_fail(self):
        result = reconcile_rows(
            [],
            start=datetime(2026, 7, 21, tzinfo=timezone.utc),
            end=datetime(2026, 7, 22, tzinfo=timezone.utc),
            expected_count=1,
            event_description="SingleGenerateImage",
            model="gpt-image-2-pro",
        )
        self.assertEqual(result["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
