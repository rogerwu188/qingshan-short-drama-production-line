import sys
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from poll_giggle_submit_report import (
    close_remote_generation_line,
    output_path,
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


if __name__ == "__main__":
    unittest.main()
