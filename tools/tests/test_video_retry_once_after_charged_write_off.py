"""Field E04 2026-11-14: a K073 write-off left four video units blocked for good.

Line owner ruling A (2026-11-11): a charge whose task id cannot be recovered is written off and
the unit is submitted once more as a new attempt.  The recompiled task keeps its fingerprint, so
``prior_bound`` met the written-off row and refused (``blocked by transaction state
CHARGED_WRITTEN_OFF_BY_ORDER``).  One new attempt is now let through; the written-off row is
archived beside the transaction, and a second write-off of the same unit stays blocked.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import tools.submit_giggle_video_manifest_v2 as submitter  # noqa: E402

EP = "E04"
KEY = "E04-VU-007"
SUFFIX = submitter.WRITTEN_OFF_ARCHIVE_SUFFIX


class RetryOnceAfterChargedWriteOffTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = Path(self._tmp.name) / "workflow/tasks/giggle_video_submit_transactions" / EP
        self.store.mkdir(parents=True)
        self.task = {"task_key": KEY, "prompt_sha256": "p" * 64, "reference_sha256": ["r" * 64]}
        self.path = submitter.transaction_path(self.store, self.task)

    def _write(self, **fields) -> None:
        self.path.write_text(json.dumps({
            "task_key": KEY, "submission_fingerprint": submitter.task_fingerprint(self.task), **fields,
        }), encoding="utf-8")

    def _written_off(self, attempt="a-1", at="2026-11-14T20:31:00Z") -> None:
        self._write(state="CHARGED_WRITTEN_OFF_BY_ORDER", previous_state="CHARGE_STATE_UNRESOLVED_BATCH",
                    attempt_id=attempt, written_off_at=at, retry_guard="DO_NOT_RESUBMIT_THIS_FINGERPRINT",
                    charge_evidence={"charged_credits": 42.5})

    def test_written_off_unit_gets_one_new_attempt_and_the_row_is_archived(self):
        self._written_off()
        self.assertIsNone(submitter.prior_bound(self.task, self.store), "a new attempt may POST")
        archive = self.path.with_name(self.path.name + SUFFIX)
        kept = json.loads(archive.read_text(encoding="utf-8"))
        self.assertEqual(kept["state"], "CHARGED_WRITTEN_OFF_BY_ORDER")
        self.assertEqual(kept["charge_evidence"], {"charged_credits": 42.5}, "kept verbatim")
        self.assertEqual([p.name for p in self.store.glob("*.json")], [self.path.name],
                         "the archive is invisible to *.json store scans")

    def test_a_run_that_stops_before_its_intent_does_not_use_up_the_attempt(self):
        self._written_off()
        self.assertIsNone(submitter.prior_bound(self.task, self.store))
        # a pre-intent gate refused; the transaction is untouched and the next run asks again
        self.assertIsNone(submitter.prior_bound(self.task, self.store))

    def test_a_second_write_off_of_the_same_unit_stays_blocked(self):
        self._written_off()
        self.assertIsNone(submitter.prior_bound(self.task, self.store))
        # the new attempt was POSTed (new attempt id), lost again and written off again
        self._written_off(attempt="a-2", at="2026-11-14T23:00:00Z")
        with self.assertRaisesRegex(RuntimeError, "CHARGED_WRITTEN_OFF_BY_ORDER"):
            submitter.prior_bound(self.task, self.store)
        kept = json.loads(self.path.with_name(self.path.name + SUFFIX).read_text(encoding="utf-8"))
        self.assertEqual(kept["attempt_id"], "a-1", "the first written-off row is not overwritten")

    def test_unreadable_archive_or_missing_write_off_time_fails_closed(self):
        self._write(state="CHARGED_WRITTEN_OFF_BY_ORDER", attempt_id="a-1")  # no written_off_at
        with self.assertRaisesRegex(RuntimeError, "CHARGED_WRITTEN_OFF_BY_ORDER"):
            submitter.prior_bound(self.task, self.store)
        self._written_off()
        self.path.with_name(self.path.name + SUFFIX).write_text("{not json", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "CHARGED_WRITTEN_OFF_BY_ORDER"):
            submitter.prior_bound(self.task, self.store)

    def test_unresolved_charge_states_are_still_blocked(self):
        for state in ("CHARGE_STATE_UNRESOLVED_BATCH", "CHARGED_TASK_ID_MISSING",
                      "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION"):
            self._write(state=state, attempt_id="a-1", written_off_at="2026-11-14T20:31:00Z")
            with self.assertRaisesRegex(RuntimeError, state):
                submitter.prior_bound(self.task, self.store)
        self.assertEqual([p.name for p in self.store.iterdir() if SUFFIX in p.name], [])


if __name__ == "__main__":
    unittest.main()
