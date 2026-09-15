import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools.credit_window_isolation import (
    EXACT_LABEL_NEVER_EMITTED,
    PASS_LABEL,
    PASS_STATUS,
    isolate_credit_windows,
)

ROOT = Path(__file__).resolve().parents[2]
EVENT = "GenerateMusic"


def _tx(key, intent, response):
    return {"key": key, "intent": intent, "response": response}


def _row(created_at, credit=-8, event=EVENT, kind="Pay"):
    return {"created_at": created_at, "event_description": event, "event_type": kind, "credit": credit}


# Three sequential windows: tx N's response stamp IS tx N+1's intent stamp (no slack).
SEQUENTIAL = [
    _tx("cue-1", "2026-01-01T05:56:00Z", "2026-01-01T05:57:10Z"),
    _tx("cue-2", "2026-01-01T05:57:10Z", "2026-01-01T05:58:15Z"),
    _tx("cue-3", "2026-01-01T05:58:15Z", "2026-01-01T05:59:20Z"),
]
ONE_ROW_EACH = [
    _row("2026-01-01 05:50:00", credit=-11, event="GenerateImage"),  # older page tail, other event
    _row("2026-01-01 05:56:02"),
    _row("2026-01-01 05:57:12"),
    _row("2026-01-01 05:58:17"),
]


class CreditWindowIsolationTests(unittest.TestCase):
    def test_three_sequential_windows_one_row_each(self):
        results = isolate_credit_windows(SEQUENTIAL, ONE_ROW_EACH, event_description=EVENT)
        self.assertEqual([PASS_STATUS] * 3, [r["status"] for r in results])
        self.assertEqual([8.0, 8.0, 8.0], [r["net"] for r in results])
        self.assertEqual([1, 1, 1], [len(r["matched_rows"]) for r in results])
        for result in results:
            self.assertEqual("SUBMIT_WINDOW", result["isolation"])
            self.assertEqual(PASS_LABEL, result["ledger_label"])
            self.assertNotEqual(EXACT_LABEL_NEVER_EMITTED, result["ledger_label"])

    def test_row_on_abutting_boundary_belongs_to_the_later_window(self):
        rows = [_row("2026-01-01 05:50:00", event="GenerateImage"), _row("2026-01-01 05:56:02"),
                _row("2026-01-01 05:57:10"), _row("2026-01-01 05:58:17")]
        results = isolate_credit_windows(SEQUENTIAL, rows, event_description=EVENT)
        self.assertEqual([PASS_STATUS] * 3, [r["status"] for r in results])
        self.assertEqual("2026-01-01 05:57:10", results[1]["matched_rows"][0]["created_at"])

    def test_overlapping_windows_fail_both_transactions(self):
        overlapping = [
            _tx("a", "2026-01-01T05:56:00Z", "2026-01-01T05:57:10Z"),
            _tx("b", "2026-01-01T05:57:05Z", "2026-01-01T05:58:15Z"),
            _tx("c", "2026-01-01T05:58:15Z", "2026-01-01T05:59:20Z"),
        ]
        results = isolate_credit_windows(overlapping, ONE_ROW_EACH, event_description=EVENT)
        self.assertEqual(["FAIL_WINDOW_OVERLAP", "FAIL_WINDOW_OVERLAP", PASS_STATUS],
                         [r["status"] for r in results])
        self.assertEqual("b", results[0]["overlaps"])
        self.assertIsNone(results[0]["net"])

    def test_statement_page_too_short(self):
        # The page's oldest row (05:57:12) is newer than the first two window starts, so those
        # windows may be missing rows and fail closed; the third window is still covered.
        rows = [_row("2026-01-01 05:57:12"), _row("2026-01-01 05:58:17")]
        results = isolate_credit_windows(SEQUENTIAL, rows, event_description=EVENT)
        self.assertEqual(["FAIL_STATEMENT_PAGE_TOO_SHORT", "FAIL_STATEMENT_PAGE_TOO_SHORT", PASS_STATUS],
                         [r["status"] for r in results])
        self.assertEqual(["FAIL_STATEMENT_PAGE_TOO_SHORT"] * 3,
                         [r["status"] for r in isolate_credit_windows(SEQUENTIAL, [], event_description=EVENT)])

    def test_exactly_one_pay_row_rule_and_refund_net(self):
        rows = [
            _row("2026-01-01 05:50:00", event="GenerateImage"),
            _row("2026-01-01 05:56:02"),
            _row("2026-01-01 05:56:30", credit=8, kind="Refund"),
            _row("2026-01-01 05:57:12"),
            _row("2026-01-01 05:57:40"),  # second Pay row inside cue-2
            _row("2026-01-01 05:58:17", credit=-400, event="GenerateVideo"),  # foreign event, not booked
        ]
        results = isolate_credit_windows(SEQUENTIAL, rows, event_description=EVENT)
        self.assertEqual(PASS_STATUS, results[0]["status"])
        self.assertEqual((8.0, 8.0, 0.0), (results[0]["paid"], results[0]["refunded"], results[0]["net"]))
        self.assertEqual("FAIL_WINDOW_PAY_ROW_COUNT_2", results[1]["status"])
        self.assertEqual("FAIL_WINDOW_PAY_ROW_COUNT_0", results[2]["status"])
        self.assertEqual(["GenerateVideo"], results[2]["other_events_in_window"])

    def test_missing_timestamps_fail_closed(self):
        results = isolate_credit_windows([{"key": "x", "intent": "2026-01-01T05:56:00Z"}], ONE_ROW_EACH)
        self.assertEqual("FAIL_WINDOW_TIMESTAMPS_MISSING", results[0]["status"])

    def test_cli_runs_offline_and_reports_exact_false(self):
        with tempfile.TemporaryDirectory() as directory:
            tx_path, st_path = Path(directory) / "tx.json", Path(directory) / "st.json"
            tx_path.write_text(json.dumps(SEQUENTIAL), encoding="utf-8")
            st_path.write_text(json.dumps({"list": ONE_ROW_EACH}), encoding="utf-8")
            run = subprocess.run([sys.executable, str(ROOT / "tools/credit_window_isolation.py"),
                                  "--transactions", str(tx_path), "--statements", str(st_path),
                                  "--event-description", EVENT],
                                 cwd=directory, capture_output=True, text=True)
        self.assertEqual(0, run.returncode, run.stderr)
        report = json.loads(run.stdout)
        self.assertEqual("PASS", report["status"])
        self.assertIs(report["exact_per_task"], False)


if __name__ == "__main__":
    unittest.main()
