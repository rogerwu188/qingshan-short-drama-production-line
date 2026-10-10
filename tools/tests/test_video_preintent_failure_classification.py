#!/usr/bin/env python3
"""A pre-intent refusal in the same batch must not quarantine a declined POST.

nalu E11 wave 9 (2026-10-10): VU-003 was refused by the prompt scope gate before any intent
record (no POST, nothing to charge) and VU-026 died on a DNS failure.  The ledger window held
exactly as many pay rows as known task ids (2 == 2), which is the e24 condition for
VERIFIED_ZERO_RETRYABLE, but ``all(_provider_declined(...))`` also ran over VU-003, whose error
text has no transport marker, so the whole batch became CHARGE_STATE_UNRESOLVED_BATCH and the
durable guard refused to POST VU-026 again.  A pay row beyond the known task ids must still
quarantine (the money-safety property is unchanged).
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools import submit_giggle_video_manifest_v2 as video


class PreIntentFailureDoesNotQuarantineTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tx = Path(self._tmp.name)
        self.posted_tx = self.tx / "VU-026.json"
        self.posted_tx.write_text(json.dumps({"state": "RESPONSE_LOST", "provider_response": None,
                                              "error": "NETWORK: <urlopen error [Errno 8] nodename nor servname provided, or not known>"}))

    def tearDown(self):
        self._tmp.cleanup()

    def failures(self):
        return [
            {"task_key": "VU-003", "state": "submit_failed_before_intent",
             "error": "VU-003 PROMPT_SCOPE_CONFLICT_GATE_FAILED (not charged, no intent recorded)",
             "transaction": str(self.tx / "VU-003.json"), "pre_intent_block": "x"},
            {"task_key": "VU-026", "state": "submit_failed",
             "error": "NETWORK: <urlopen error [Errno 8] nodename nor servname provided, or not known>",
             "transaction": str(self.posted_tx)},
        ]

    def test_ledger_equal_known_settles_the_declined_post(self):
        failures = self.failures()
        summary = video.classify_failures(failures, 2, 2, self.tx)
        self.assertEqual(summary, "PROVIDER_DECLINED_AND_LEDGER_ROWS_EQUAL_KNOWN_TASK_IDS")
        self.assertEqual(json.loads(self.posted_tx.read_text())["state"], "VERIFIED_ZERO_RETRYABLE")
        self.assertEqual(failures[0]["credit_status"], "NOT_CHARGED_NO_INTENT_RECORDED")

    def test_an_extra_pay_row_still_keeps_it_out_of_retry(self):
        failures = self.failures()
        video.classify_failures(failures, 2, 3, self.tx)
        self.assertNotEqual(json.loads(self.posted_tx.read_text())["state"], "VERIFIED_ZERO_RETRYABLE")


if __name__ == "__main__":
    unittest.main()
