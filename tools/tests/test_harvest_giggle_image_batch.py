import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from tools.harvest_giggle_image_batch import (
    batch_credit_assignment,
    explicit_credit,
    harvest_workers,
    poll_once,
)


class ExplicitCreditTests(unittest.TestCase):
    def test_finds_nested_numeric_field(self):
        self.assertEqual(explicit_credit({"data": {"billing": {"credits_used": 135}}}), 135)

    def test_does_not_guess_from_unrelated_number(self):
        self.assertIsNone(explicit_credit({"data": {"duration": 15, "task_id": "abc"}}))

    def test_ignores_boolean(self):
        self.assertIsNone(explicit_credit({"credit": True}))

    def test_assigns_uniform_exact_batch_ledger(self):
        source = {
            "credit_reconciliation": {
                "status": "PASS",
                "matched_count": 2,
                "statement_rows": [{"credit": "-11"}, {"credit": "-11"}],
            }
        }
        self.assertEqual(batch_credit_assignment(source, 2)[0], 11)

    def test_refuses_nonuniform_or_count_mismatch(self):
        source = {
            "credit_reconciliation": {
                "status": "PASS",
                "matched_count": 2,
                "statement_rows": [{"credit": "-11"}, {"credit": "-22"}],
            }
        }
        self.assertIsNone(batch_credit_assignment(source, 2)[0])
        self.assertIsNone(batch_credit_assignment(source, 3)[0])


class HarvestConcurrencyTest(unittest.TestCase):
    """K114: one harvest tick queries the whole image batch at once, order fixed.

    A 50-task S3/S5 image batch is polled every 15 s by the --watch loop; the old
    loop issued one query_task and one download per task in sequence, so every
    tick paid ~50 serial HTTP round trips.
    """

    def _run(self, rows, fake_query, *, env=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = root / "submit.json"
            report.write_text(json.dumps({"episode": "E99", "results": rows}), encoding="utf-8")
            with mock.patch.dict("os.environ", env or {}), \
                 mock.patch("tools.harvest_giggle_image_batch.query_task", fake_query):
                return poll_once(report, root / "out", root / "raw")

    def test_tasks_are_queried_concurrently(self):
        barrier = threading.Barrier(4, timeout=4.0)

        def fake_query(_args):
            barrier.wait()  # a serial loop deadlocks here and fails the test
            return {"data": {"status": "running", "urls": []}}

        payload = self._run([{"task_key": f"T{i}", "task_id": f"id{i}"} for i in range(4)],
                            fake_query, env={"NALU_HARVEST_WORKERS": "4"})
        self.assertEqual(len(payload["results"]), 4)

    def test_status_rows_keep_the_submit_report_order(self):
        def fake_query(args):
            if args.task_id == "id0":
                threading.Event().wait(0.05)  # finishes last, must still be row 0
            return {"data": {"status": "completed", "urls": []}}

        payload = self._run([{"task_key": f"T{i}", "task_id": f"id{i}"} for i in range(3)],
                            fake_query, env={"NALU_HARVEST_WORKERS": "3"})
        self.assertEqual([row["task_key"] for row in payload["results"]], ["T0", "T1", "T2"])

    def test_one_task_error_fails_the_whole_tick(self):
        def fake_query(args):
            if args.task_id == "id1":
                raise RuntimeError("provider query failed")
            return {"data": {"status": "running", "urls": []}}

        with self.assertRaisesRegex(RuntimeError, "provider query failed"):
            self._run([{"task_key": "T0", "task_id": "id0"},
                       {"task_key": "T1", "task_id": "id1"}],
                      fake_query, env={"NALU_HARVEST_WORKERS": "2"})

    def test_worker_count_defaults_and_honours_the_environment(self):
        with mock.patch.dict("os.environ", {"NALU_HARVEST_WORKERS": "3"}):
            self.assertEqual(harvest_workers(), 3)
        with mock.patch.dict("os.environ", {"NALU_HARVEST_WORKERS": "nope"}):
            self.assertEqual(harvest_workers(), 6)
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(harvest_workers(), 6)


if __name__ == "__main__":
    unittest.main()
