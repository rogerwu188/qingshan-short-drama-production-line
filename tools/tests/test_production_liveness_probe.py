#!/usr/bin/env python3
"""Tests for the external production liveness probe.

Roger, 2026-07-18 (`ROGER-20260718-EXTERNAL-WATCHDOG`):
「codex 的生产线经常会停下来，怎么让他修改自己的定时巡检机制，确保生产线主流程不会停」

The existing watchdog could not answer this because it runs inside the loop it
watches. These tests pin the two properties that make this probe different:
it judges from artifacts rather than self-declared fields, and it does not
count the supervisor's own output as production activity.
"""

import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.production_liveness_probe import (
    ALIVE_SECONDS,
    STALLED_SECONDS,
    _is_supervisor_artifact,
    current_line_handles,
    probe,
    target_active_line_count,
)


class SupervisorOutputExclusionTest(unittest.TestCase):
    """The watchdog must not observe its own footsteps and call the line alive."""

    def test_supervisor_paths_are_excluded(self):
        for path in (
            "/repo/qa/gate_repair_20260718/E19R_metrics.json",
            "/repo/workflow/script_review/reviews/E31.md",
            "/repo/codex_docs/CLAUDE_TO_CODEX.md",
            "/repo/workflow/dashboard/status.json",
            "/repo/workflow/time_ledger/E20_time_ledger.json",
            "/repo/workflow/storyclaw_outbox/STORYCLAW_OUTBOX_POLLER_RECEIPT.md",
            "/repo/workflow/s3_relay/outbox/C2SC-489.md",
            "/repo/workflow/tasks/E20_TASK.md",
            "/repo/qa/cl2x299_watchdog_20260718.json",
            "/repo/qa/watchdog/production_liveness_probe_latest.json",
            "/repo/workflow/watchdog_heartbeat.log",
        ):
            self.assertTrue(_is_supervisor_artifact(path), path)

    def test_production_paths_are_counted(self):
        for path in (
            "/repo/configs/e20_dialogue_beat_sheet_v1.json",
            "/repo/exports/e20/final_package/e20.mp4",
            "/repo/working_assets/e20_giggle/E20-B01.mp4",
        ):
            self.assertFalse(_is_supervisor_artifact(path), path)


class StateThresholdTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "configs").mkdir()
        self.artifact = self.root / "configs" / "e20_plan.json"
        self.artifact.write_text("{}", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _probe_at(self, age_seconds: float):
        mtime = time.time() - age_seconds
        import os

        os.utime(self.artifact, (mtime, mtime))
        return probe(self.root)

    def test_recent_artifact_is_alive(self):
        self.assertEqual(self._probe_at(60)["state"], "ALIVE")

    def test_idle_beyond_thirty_minutes_is_slow(self):
        result = self._probe_at(ALIVE_SECONDS + 120)
        self.assertEqual(result["state"], "SLOW")
        self.assertFalse(result["action_required"])

    def test_idle_beyond_an_hour_is_stalled_and_demands_action(self):
        result = self._probe_at(STALLED_SECONDS + 120)
        self.assertEqual(result["state"], "STALLED")
        self.assertTrue(result["action_required"])

    def test_ledger_is_reported_but_never_decides(self):
        """Self-declared heartbeat fields must not influence the verdict.

        All four live ledgers were in breach on field validity alone when this
        was written (E18R and E19R carried no `last_heartbeat_at` at all), while
        the line was in fact working. Fields describe the form; mtimes describe
        the work.
        """
        result = self._probe_at(60)
        self.assertEqual(result["state"], "ALIVE")
        self.assertIn("self_declared_ledger_FOR_REFERENCE_ONLY", result)
        self.assertEqual(result["evidence_basis"], "filesystem_mtime_excluding_supervisor_output")


class HistoricalStallReplayTest(unittest.TestCase):
    """Replay of the real 2026-07-18 stall.

    Production artifacts per hour (PDT): 00h=58, 01h=42, 02h=12, 03-06h=0,
    07h=1, 08h=8, 09h=14, 10h=16. The gap ran 02:26 -> 07:51, i.e. 325 minutes,
    and nothing detected or reported it. With a 60-minute stall threshold the
    probe reports STALLED from 03:26, which is 265 minutes before the line
    recovered on its own.
    """

    STALL_START_TO_RECOVERY_MINUTES = 325

    def test_hourly_replay_flags_the_dead_zone(self):
        stall_minutes = self.STALL_START_TO_RECOVERY_MINUTES
        detect_after = STALLED_SECONDS / 60
        self.assertLess(detect_after, stall_minutes)
        lead_time = stall_minutes - detect_after
        self.assertGreaterEqual(lead_time, 240, "probe must beat self-recovery by hours, not minutes")

    def test_thresholds_not_loosened_past_the_observed_stall(self):
        """A threshold above the observed gap would have missed it entirely."""
        self.assertLess(STALLED_SECONDS / 60, self.STALL_START_TO_RECOVERY_MINUTES)
        self.assertLessEqual(STALLED_SECONDS, 3600)


class EmptyRepoTest(unittest.TestCase):
    def test_no_artifacts_is_unknown_not_alive(self):
        with TemporaryDirectory() as tmp:
            result = probe(Path(tmp))
            self.assertEqual(result["state"], "UNKNOWN")
            self.assertTrue(result["action_required"])


class ConcurrencyTargetTest(unittest.TestCase):
    def test_single_episode_debug_override_is_effective_target(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy_dir = root / "workflow" / "production_line"
            policy_dir.mkdir(parents=True)
            (policy_dir / "THREE_EPISODE_CONCURRENCY_POLICY.json").write_text(
                '{"target_concurrent_episode_lines":3,"runtime_override":{"target_concurrent_episode_lines":1}}',
                encoding="utf-8",
            )
            self.assertEqual(target_active_line_count(root), 1)


class ReleasedEpisodeExclusionTest(unittest.TestCase):
    def test_released_episode_is_not_a_live_handle(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            production = root / "workflow" / "production_line"
            release = root / "workflow" / "release" / "e20"
            production.mkdir(parents=True)
            release.mkdir(parents=True)
            (production / "ACTIVE_EPISODE_LINES_LATEST.json").write_text(
                '{"parallel_lines":[{"episode":"E20","local_pid":99999}]}',
                encoding="utf-8",
            )
            (release / "E20_RELEASE.json").write_text(
                '{"status":"RELEASED_YOUTUBE_AND_DOUYIN"}',
                encoding="utf-8",
            )

            self.assertEqual(current_line_handles(root), [])


class ActiveReceiptOverrideTest(unittest.TestCase):
    def test_new_running_receipt_overrides_stale_snapshot_evidence(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            production = root / "workflow" / "production_line"
            tasks = root / "workflow" / "tasks"
            production.mkdir(parents=True)
            tasks.mkdir(parents=True)
            stale = tasks / "E28_OLD_SUBMIT_RECEIPT.json"
            stale.write_text('{"episode":"E28","status":"BATCH_COMPLETE","tasks":[]}', encoding="utf-8")
            (production / "ACTIVE_EPISODE_LINES_LATEST.json").write_text(
                '{"parallel_lines":[{"episode":"E28","evidence":"workflow/tasks/E28_OLD_SUBMIT_RECEIPT.json"}]}',
                encoding="utf-8",
            )
            live = tasks / "E28_U09_NEW_SUBMIT_RECEIPT.json"
            live.write_text(
                '{"episode":"E28","status":"REMOTE_RUNNING","tasks":[{"task_id":"task-live","state":"remote_running"}]}',
                encoding="utf-8",
            )

            lines = current_line_handles(root)
            self.assertEqual(lines[0]["task_id"], "task-live")
            self.assertTrue(lines[0]["remote_active"])
            self.assertEqual(lines[0]["evidence"], str(live))

    def test_stale_snapshot_task_ids_do_not_make_batch_running_text_active(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            production = root / "workflow" / "production_line"
            tasks = root / "workflow" / "tasks"
            production.mkdir(parents=True)
            tasks.mkdir(parents=True)
            receipt = tasks / "E27_OLD_RECEIPT.json"
            receipt.write_text('{"episode":"E27","status":"BATCH_RUNNING","tasks":[]}', encoding="utf-8")
            (production / "ACTIVE_EPISODE_LINES_LATEST.json").write_text(
                '{"parallel_lines":[{"episode":"E27","evidence":"workflow/tasks/E27_OLD_RECEIPT.json","task_ids":["old-task"]}]}',
                encoding="utf-8",
            )

            lines = current_line_handles(root)
            self.assertFalse(lines[0]["remote_active"])
            self.assertEqual(lines[0]["task_ids"], [])

    def test_terminal_batch_status_overrides_stale_child_submitted_state(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            production = root / "workflow" / "production_line"
            tasks = root / "workflow" / "tasks"
            production.mkdir(parents=True)
            tasks.mkdir(parents=True)
            receipt = tasks / "E28_COMPLETE_RECEIPT.json"
            receipt.write_text(
                '{"episode":"E28","status":"BATCH_COMPLETE_WITH_ISOLATED_FAILURES","tasks":[{"task_id":"old-task","state":"submitted"}]}',
                encoding="utf-8",
            )
            (production / "ACTIVE_EPISODE_LINES_LATEST.json").write_text(
                '{"parallel_lines":[{"episode":"E28","evidence":"workflow/tasks/E28_COMPLETE_RECEIPT.json"}]}',
                encoding="utf-8",
            )

            lines = current_line_handles(root)
            self.assertFalse(lines[0]["remote_active"])
            self.assertEqual(lines[0]["task_ids"], [])

    def test_old_running_receipt_is_not_current_remote_activity(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            production = root / "workflow" / "production_line"
            tasks = root / "workflow" / "tasks"
            production.mkdir(parents=True)
            tasks.mkdir(parents=True)
            receipt = tasks / "E27_RUNNING_RECEIPT.json"
            receipt.write_text(
                '{"episode":"E27","status":"REMOTE_RUNNING","tasks":[{"task_id":"old-task","state":"remote_running"}]}',
                encoding="utf-8",
            )
            stale = time.time() - ALIVE_SECONDS - 60
            os.utime(receipt, (stale, stale))
            (production / "ACTIVE_EPISODE_LINES_LATEST.json").write_text(
                '{"parallel_lines":[{"episode":"E27","evidence":"workflow/tasks/E27_RUNNING_RECEIPT.json"}]}',
                encoding="utf-8",
            )

            lines = current_line_handles(root)
            self.assertFalse(lines[0]["remote_active"])
            self.assertEqual(lines[0]["liveness_reason"], "NO_LIVE_HANDLE")


if __name__ == "__main__":
    unittest.main()
