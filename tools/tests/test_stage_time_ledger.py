"""tools/stage_time_ledger.py tests: pure-function unit tests, offline, tempdir-based.
No real episode paths touched, mirroring tools/tests/test_ad_tail_package.py's structure.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import stage_time_ledger as stl  # noqa: E402


class WallSecondsTests(unittest.TestCase):
    def test_computes_positive_duration(self) -> None:
        self.assertEqual(stl.wall_seconds("2026-09-26T00:00:00Z", "2026-09-26T00:05:30Z"), 330.0)

    def test_missing_timestamps_are_zero(self) -> None:
        self.assertEqual(stl.wall_seconds(None, "2026-09-26T00:00:00Z"), 0.0)
        self.assertEqual(stl.wall_seconds("2026-09-26T00:00:00Z", None), 0.0)

    def test_end_before_start_is_zero_never_negative(self) -> None:
        self.assertEqual(stl.wall_seconds("2026-09-26T00:05:00Z", "2026-09-26T00:00:00Z"), 0.0)


class ClassifyBreakdownTests(unittest.TestCase):
    def test_review_required_status_is_human_wait(self) -> None:
        b = stl.classify_breakdown("REVIEW_REQUIRED", [], 100.0)
        self.assertEqual(b, {"compute": 0.0, "remote_wait": 0.0, "human_wait": 100.0, "idle": 0.0})

    def test_human_review_step_name_is_human_wait(self) -> None:
        steps = [{"name": "s6_q2_admission", "paid": False}]
        b = stl.classify_breakdown("PASS", steps, 50.0)
        self.assertEqual(b["human_wait"], 50.0)

    def test_paid_step_is_remote_wait(self) -> None:
        steps = [{"name": "s5_submit", "paid": True}]
        b = stl.classify_breakdown("PASS", steps, 200.0)
        self.assertEqual(b["remote_wait"], 200.0)

    def test_no_signal_is_idle(self) -> None:
        steps = [{"name": "s1_selfcheck", "paid": False}]
        b = stl.classify_breakdown("PASS", steps, 5.0)
        self.assertEqual(b["idle"], 5.0)

    def test_human_wait_takes_priority_over_paid(self) -> None:
        steps = [{"name": "s6_q2_admission", "paid": True}]
        b = stl.classify_breakdown("PASS", steps, 10.0)
        self.assertEqual(b["human_wait"], 10.0)
        self.assertEqual(b["remote_wait"], 0.0)


class AppendEventAndSummaryTests(unittest.TestCase):
    def test_append_event_writes_one_line_and_accumulates(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            e1 = stl.append_event(episode="E09", stage="S1", status="PASS",
                                  started_at="2026-09-26T00:00:00Z", finished_at="2026-09-26T00:01:00Z",
                                  credits=0, attempt=1, steps=[], work_root=root)
            self.assertEqual(e1["wall_seconds"], 60.0)
            self.assertEqual(e1["episode_cumulative_seconds"], 60.0)
            e2 = stl.append_event(episode="E09", stage="S2", status="PASS",
                                  started_at="2026-09-26T00:01:00Z", finished_at="2026-09-26T00:03:00Z",
                                  credits=10, attempt=1, steps=[], work_root=root)
            self.assertEqual(e2["wall_seconds"], 120.0)
            self.assertEqual(e2["episode_cumulative_seconds"], 180.0)
            self.assertEqual(e2["episode_cumulative_credits"], 10)
            path = stl.ledger_path("E09", work_root=root)
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[0])["stage"], "S1")

    def test_reroll_appends_new_event_never_overwrites(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stl.append_event(episode="E09", stage="S6", status="BLOCKED",
                             started_at="2026-09-26T00:00:00Z", finished_at="2026-09-26T00:10:00Z",
                             credits=100, attempt=1, steps=[], work_root=root)
            stl.append_event(episode="E09", stage="S6", status="PASS",
                             started_at="2026-09-26T00:10:00Z", finished_at="2026-09-26T00:20:00Z",
                             credits=100, attempt=2, steps=[], work_root=root)
            path = stl.ledger_path("E09", work_root=root)
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            attempts = [json.loads(line)["attempt"] for line in lines]
            self.assertEqual(attempts, [1, 2])

    def test_episode_summary_uses_last_event_per_stage(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stl.append_event(episode="E09", stage="S6", status="BLOCKED",
                             started_at="2026-09-26T00:00:00Z", finished_at="2026-09-26T00:10:00Z",
                             credits=100, attempt=1, steps=[], work_root=root)
            stl.append_event(episode="E09", stage="S6", status="PASS",
                             started_at="2026-09-26T00:10:00Z", finished_at="2026-09-26T00:20:00Z",
                             credits=50, attempt=2, steps=[], work_root=root)
            summary = stl.episode_summary("E09", work_root=root)
            self.assertEqual(summary["stages"]["S6"]["status"], "PASS")
            self.assertEqual(summary["stages"]["S6"]["attempt"], 2)
            self.assertEqual(summary["event_count"], 2)

    def test_empty_ledger_summary_is_safe(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            summary = stl.episode_summary("E99", work_root=Path(td))
            self.assertEqual(summary["stages"], {})
            self.assertEqual(summary["total_wall_seconds"], 0.0)
            self.assertEqual(summary["event_count"], 0)


if __name__ == "__main__":
    unittest.main()
