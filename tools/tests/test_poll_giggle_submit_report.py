import sys
import json
import threading
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from poll_giggle_submit_report import (
    close_remote_generation_line,
    output_path,
    poll,
    poll_workers,
    result_rows,
    safe_stem,
)


class PollGiggleSubmitReportTest(unittest.TestCase):
    def test_safe_stem_removes_path_and_space_characters(self) -> None:
        self.assertEqual(safe_stem(" DIA/014 R2 "), "DIA-014-R2")

    def test_result_rows_accepts_results_or_tasks(self) -> None:
        self.assertEqual(result_rows({"results": [{"task_id": "a"}]}), [{"task_id": "a"}])
        self.assertEqual(result_rows({"tasks": [{"task_id": "b"}]}), [{"task_id": "b"}])

    def test_output_path_is_stable_for_single_and_multiple_urls(self) -> None:
        out = Path("/tmp/out")
        self.assertEqual(output_path(out, "DIA-014", 1, 1), out / "DIA-014.mp4")
        self.assertEqual(output_path(out, "DIA-014", 2, 3), out / "DIA-014_02.mp4")

    def test_completed_harvest_auto_closes_remote_generation_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger_path = root / "ledger.json"
            report_path = root / "status.json"
            ledger_path.write_text(
                json.dumps(
                    {
                        "updated_at": "2026-07-16T20:00:00-07:00",
                        "events": [],
                        "parallel_lines": [
                            {
                                "line_id": "E18R_W1",
                                "blocked_by": "REMOTE_GENERATION",
                                "blocked_since_at": "2026-07-16T20:00:00-07:00",
                                "last_heartbeat_at": "2026-07-16T20:00:00-07:00",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            line = close_remote_generation_line(
                ledger_path,
                "E18R_W1",
                report_path,
                now="2026-07-16T20:05:00-07:00",
            )
            self.assertEqual(line["blocked_by"], "NONE")
            self.assertNotIn("blocked_since_at", line)
            saved = json.loads(ledger_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["parallel_lines"][0]["last_heartbeat_at"], "2026-07-16T20:05:00-07:00")
            self.assertIn("AUTO_CLOSE_TO_NONE", saved["events"][-1]["event"])

    def test_closeout_rejects_non_remote_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "ledger.json"
            ledger_path.write_text(
                json.dumps({"parallel_lines": [{"line_id": "E19_W1_W2", "blocked_by": "NONE"}]}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "not blocked by REMOTE_GENERATION"):
                close_remote_generation_line(ledger_path, "E19_W1_W2", Path(tmp) / "status.json")


class PollConcurrencyTest(unittest.TestCase):
    """K113: one poll tick queries the whole wave at once, order fixed.

    The old loop issued one query_task per submitted task in sequence, so a
    six-unit wave paid six serial HTTP round trips on every scheduler tick.
    """

    def _run(self, rows, fake_query, *, env=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = root / "submit.json"
            report.write_text(json.dumps({"results": rows}), encoding="utf-8")
            with mock.patch.dict("os.environ", {"GIGGLE_API_KEY": "MOCK", **(env or {})}), \
                 mock.patch("poll_giggle_submit_report.ensure_giggle_api_key", lambda: "MOCK"), \
                 mock.patch("poll_giggle_submit_report.query_task", fake_query):
                return poll(report, root / "out", root / "status.json", False)

    def test_tasks_are_queried_concurrently(self):
        barrier = threading.Barrier(4, timeout=4.0)

        def fake_query(_args):
            barrier.wait()  # a serial loop deadlocks here and fails the test
            return {"data": {"status": "running", "urls": []}}

        payload = self._run([{"task_key": f"U{i}", "task_id": f"t{i}"} for i in range(4)],
                            fake_query, env={"NALU_POLL_WORKERS": "4"})
        self.assertEqual(len(payload["results"]), 4)

    def test_status_rows_keep_the_submit_report_order(self):
        def fake_query(args):
            if args.task_id == "t0":
                threading.Event().wait(0.05)  # finishes last, must still be row 0
            return {"data": {"status": "completed", "urls": []}}

        payload = self._run([{"task_key": f"U{i}", "task_id": f"t{i}"} for i in range(3)],
                            fake_query, env={"NALU_POLL_WORKERS": "3"})
        self.assertEqual([row["task_key"] for row in payload["results"]],
                         ["U0", "U1", "U2"])

    def test_one_task_error_fails_the_whole_tick(self):
        def fake_query(args):
            if args.task_id == "t1":
                raise RuntimeError("provider query failed")
            return {"data": {"status": "running", "urls": []}}

        with self.assertRaisesRegex(RuntimeError, "provider query failed"):
            self._run([{"task_key": "U0", "task_id": "t0"},
                       {"task_key": "U1", "task_id": "t1"}],
                      fake_query, env={"NALU_POLL_WORKERS": "2"})

    def test_worker_count_defaults_and_honours_the_environment(self):
        with mock.patch.dict("os.environ", {"NALU_POLL_WORKERS": "3"}):
            self.assertEqual(poll_workers(), 3)
        with mock.patch.dict("os.environ", {"NALU_POLL_WORKERS": "not-a-number"}):
            self.assertEqual(poll_workers(), 6)
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(poll_workers(), 6)


if __name__ == "__main__":
    unittest.main()
