"""Field E14 2026-11-15: a K073 write-off left one S5 keyframe blocked for good.

Line owner ruling A (2026-11-11): a lost response whose task id cannot be recovered is written off
and the task is submitted once more as a new attempt.  The keyframe keeps its fingerprint, so
``prior_submission_result`` met the written-off row and refused (``duplicate submit blocked by
transaction state CHARGED_WRITTEN_OFF_BY_ORDER``).  The video submitter got the single new attempt
on 2026-11-14; the image submitter now has the same rule: one new attempt, the written-off row is
archived beside the transaction, and a second write-off of the same task stays blocked.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import tools.submit_giggle_image_manifest as submitter  # noqa: E402

EP = "E14"
KEY = "E14-S02-04-KEYFRAME-V1"
SUFFIX = submitter.WRITTEN_OFF_ARCHIVE_SUFFIX
BLOCKED = submitter.DuplicateSubmissionBlocked


class ImageRetryOnceAfterChargedWriteOffTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = Path(self._tmp.name) / "workflow/tasks/giggle_submit_transactions" / EP
        self.store.mkdir(parents=True)
        self.task = {"task_key": KEY, "prompt_sha256": "p" * 64,
                     "reference_bindings": [{"role": "character", "sha256": "r" * 64}]}
        self.path = submitter.transaction_path(self.store, self.task)

    def _write(self, **fields) -> None:
        self.path.write_text(json.dumps({
            "task_key": KEY, "submission_fingerprint": submitter.submission_fingerprint(self.task), **fields,
        }), encoding="utf-8")

    def _written_off(self, attempt="a-1", at="2026-11-15T03:20:00Z") -> None:
        self._write(state="CHARGED_WRITTEN_OFF_BY_ORDER",
                    previous_state="RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION",
                    attempt_id=attempt, written_off_at=at, retry_guard="DO_NOT_RESUBMIT_THIS_FINGERPRINT",
                    written_off_without_charge_evidence="HTTP 502, no task id in the response")

    def test_written_off_keyframe_gets_one_new_attempt_and_the_row_is_archived(self):
        self._written_off()
        self.assertIsNone(submitter.prior_submission_result(self.task, self.store), "a new attempt may POST")
        archive = self.path.with_name(self.path.name + SUFFIX)
        kept = json.loads(archive.read_text(encoding="utf-8"))
        self.assertEqual(kept["state"], "CHARGED_WRITTEN_OFF_BY_ORDER")
        self.assertEqual(kept["written_off_without_charge_evidence"],
                         "HTTP 502, no task id in the response", "kept verbatim")
        self.assertEqual([p.name for p in self.store.glob("*.json")], [self.path.name],
                         "the archive is invisible to *.json store scans")

    def test_a_run_that_stops_before_its_intent_does_not_use_up_the_attempt(self):
        self._written_off()
        self.assertIsNone(submitter.prior_submission_result(self.task, self.store))
        # a pre-intent gate refused; the transaction is untouched and the next run asks again
        self.assertIsNone(submitter.prior_submission_result(self.task, self.store))

    def test_a_second_write_off_of_the_same_task_stays_blocked(self):
        self._written_off()
        self.assertIsNone(submitter.prior_submission_result(self.task, self.store))
        # the new attempt was POSTed (new attempt id), lost again and written off again
        self._written_off(attempt="a-2", at="2026-11-15T05:00:00Z")
        with self.assertRaisesRegex(BLOCKED, "CHARGED_WRITTEN_OFF_BY_ORDER"):
            submitter.prior_submission_result(self.task, self.store)
        kept = json.loads(self.path.with_name(self.path.name + SUFFIX).read_text(encoding="utf-8"))
        self.assertEqual(kept["attempt_id"], "a-1", "the first written-off row is not overwritten")

    def test_unreadable_archive_or_missing_write_off_time_fails_closed(self):
        self._write(state="CHARGED_WRITTEN_OFF_BY_ORDER", attempt_id="a-1")  # no written_off_at
        with self.assertRaisesRegex(BLOCKED, "CHARGED_WRITTEN_OFF_BY_ORDER"):
            submitter.prior_submission_result(self.task, self.store)
        self._written_off()
        self.path.with_name(self.path.name + SUFFIX).write_text("{not json", encoding="utf-8")
        with self.assertRaisesRegex(BLOCKED, "CHARGED_WRITTEN_OFF_BY_ORDER"):
            submitter.prior_submission_result(self.task, self.store)

    def test_unresolved_states_are_still_blocked(self):
        for state in ("RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION", "CHARGED_TASK_ID_MISSING",
                      "INTENT_RECORDED", "NEEDS_MANUAL_ATTRIBUTION"):
            self._write(state=state, attempt_id="a-1", written_off_at="2026-11-15T03:20:00Z")
            with self.assertRaisesRegex(BLOCKED, state):
                submitter.prior_submission_result(self.task, self.store)
        self.assertEqual([p.name for p in self.store.iterdir() if SUFFIX in p.name], [])


if __name__ == "__main__":
    unittest.main()
