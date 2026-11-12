"""Fleet 2026-11-12: S6 takes the provider terminally failed at zero cost stayed bound forever.

Every device's first S6 wave failed remotely at once (``Provider error``, cost 0).  The rows kept
``SUBMITTED_TASK_ID_BOUND``, so the planner said "6 already bound" and the submitter returned
``remote_running`` -- poll only, no recovery.  A zero-cost terminal take is now released to a new
attempt (at most ZERO_COST_TERMINAL_RETRY_LIMIT times), the failed take archived beside it.
"""
from __future__ import annotations

import fcntl
import json
import sys
import threading
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import tools.submit_giggle_video_manifest_v2 as submitter  # noqa: E402
from tools.video_live_binding import (ZERO_COST_TERMINAL_RETRY_LIMIT, live_bindings,  # noqa: E402
                                      zero_cost_retryable)

EP = "E02"
KEY = "E02-VU-001"


def _task() -> dict:
    return {"task_key": KEY, "prompt_sha256": "p" * 64, "reference_sha256": ["r" * 64]}


class ZeroCostTerminalRetryTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.store = self.root / "workflow/tasks/giggle_video_submit_transactions" / EP
        self.store.mkdir(parents=True)
        self.task = _task()
        self.path = submitter.transaction_path(self.store, self.task)

    def tearDown(self):
        self._tmp.cleanup()

    def _bound(self, task_id="tsk_dead", **extra) -> None:
        self.path.write_text(json.dumps({
            "schema": "qingshan.giggle_video_submit_transaction.v1", "task_key": KEY,
            "submission_fingerprint": submitter.task_fingerprint(self.task), "state": "SUBMITTED_TASK_ID_BOUND",
            "task_id": task_id, "provider": "hopsapi", "prompt_sha256": "p" * 64, **extra}), encoding="utf-8")

    def _failed(self, task_id="tsk_dead") -> None:
        self._bound(task_id, provider_remote_status="failed", remote_terminal_state="failed",
                    provider_cost_credits=0.0, provider_failure="Provider error")

    def _row(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def test_zero_cost_terminal_take_is_released_and_archived(self):
        self._failed()
        self.assertIsNone(submitter.prior_bound(self.task, self.store), "a new attempt may POST")
        row = self._row()
        self.assertEqual(row["state"], "VERIFIED_ZERO_RETRYABLE")
        self.assertEqual(row["released_task_id"], "tsk_dead")
        archives = [p.name for p in self.store.iterdir() if ".zero_cost_failed." in p.name]
        self.assertEqual(len(archives), 1)
        archived = json.loads((self.store / archives[0]).read_text(encoding="utf-8"))
        self.assertEqual(archived["task_id"], "tsk_dead", "the failed take is kept verbatim")
        self.assertEqual([p.name for p in self.store.glob("*.json")], [self.path.name],
                         "the archive is invisible to *.json store scans")

    def test_running_take_is_still_polled_not_posted(self):
        self._bound("tsk_live")
        prior = submitter.prior_bound(self.task, self.store)
        self.assertEqual((prior or {}).get("state"), "remote_running")
        self.assertEqual(self._row()["state"], "SUBMITTED_TASK_ID_BOUND")

    def test_charged_terminal_take_is_never_released(self):
        self._bound(provider_remote_status="failed", remote_terminal_state="failed", provider_cost_credits=12.4)
        self.assertEqual((submitter.prior_bound(self.task, self.store) or {}).get("state"), "remote_running")
        self.assertFalse(zero_cost_retryable(self.path, self._row()))

    def test_unsettled_terminal_take_is_not_released(self):
        self._bound(provider_remote_status="failed", remote_terminal_state="failed")  # no cost recorded yet
        self.assertFalse(zero_cost_retryable(self.path, self._row()))

    def test_retry_limit_keeps_the_last_failure_bound(self):
        for n in range(ZERO_COST_TERMINAL_RETRY_LIMIT):
            self._failed(f"tsk_dead_{n}")
            self.assertIsNone(submitter.prior_bound(self.task, self.store))
        self._failed("tsk_dead_last")
        self.assertFalse(zero_cost_retryable(self.path, self._row()))
        self.assertEqual((submitter.prior_bound(self.task, self.store) or {}).get("state"), "remote_running")
        self.assertEqual(self._row()["task_id"], "tsk_dead_last", "past the limit nothing is rewritten")

    def test_release_under_the_submitters_lock_does_not_self_deadlock(self):
        # fleet 2026-11-12 (296675c): submit_one holds the transaction flock while prior_bound runs
        self._failed()
        out = {}
        def run():
            with self.path.with_suffix(".lock").open("a") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                out["prior"] = submitter.prior_bound(self.task, self.store)
        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        worker.join(5)
        self.assertFalse(worker.is_alive(), "prior_bound deadlocked on the lock its caller holds")
        self.assertIsNone(out["prior"])
        self.assertEqual(self._row()["state"], "VERIFIED_ZERO_RETRYABLE")

    def test_released_row_is_not_a_live_binding(self):
        self._failed()
        submitter.prior_bound(self.task, self.store)
        self.assertEqual(live_bindings(self.store, KEY, root=self.root, episode=EP), [])


if __name__ == "__main__":
    unittest.main()
