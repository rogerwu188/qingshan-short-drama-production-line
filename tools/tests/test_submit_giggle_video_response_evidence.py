import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SUBMITTER = ROOT / "tools/submit_giggle_video_manifest_v2.py"


class VideoSubmitResponseEvidenceTests(unittest.TestCase):
    def test_submitter_is_valid_python(self):
        ast.parse(SUBMITTER.read_text(encoding="utf-8"), filename=str(SUBMITTER))

    def test_received_response_without_task_id_is_not_mislabeled_as_response_lost(self):
        source = SUBMITTER.read_text(encoding="utf-8")
        branch = source.split('if not task_id:', 1)[1].split('receipt =', 1)[0]
        self.assertIn('classification = classify_no_task_id_response(response)', branch)
        self.assertIn('"provider_response": response', branch)
        self.assertIn('"provider_response_sha256": response_sha256', branch)
        self.assertIn('**classification', branch)
        self.assertNotIn('"state": "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION"', branch)

    def test_submitter_classifies_insufficient_credits_and_has_batch_fuse(self):
        source = SUBMITTER.read_text(encoding="utf-8")
        self.assertIn('"PROVIDER_INSUFFICIENT_CREDITS"', source)
        self.assertIn('"not_submitted_provider_insufficient_credits"', source)

    def test_submitter_dispatch_is_a_ready_queue_not_a_fixed_wave_barrier(self):
        """The scheduling shape is asserted by behaviour, not by source text.

        This test used to assert the literal string
        ``for offset in range(0, len(tasks), concurrency)``.  That pinned the fixed-wave
        barrier as if it were the contract, so the barrier could not be replaced without
        breaking a test that was protecting the thing being fixed (2026-10-13).  What
        actually matters is that a free submit slot is refilled from a ready queue rather
        than at a whole-batch boundary, and the behavioural proof of that lives in
        tools/tests/test_concurrent_dispatch_audit_repro.py
        (SubmitterFixedWaveBarrierRepro).  Here we only assert that the batch is not
        queued up front, which is what makes the insufficient-credits fuse able to stop
        dispatch at all.
        """
        import tools.submit_giggle_video_manifest_v2 as submitter

        source = SUBMITTER.read_text(encoding="utf-8")
        # the fuse must still be reachable: tasks are pulled one at a time from an iterator
        self.assertIn("task_iter = iter(tasks)", source)
        self.assertIn("FIRST_COMPLETED", source)
        # and the module still exposes the fuse + per-fingerprint lock it always had
        self.assertTrue(hasattr(submitter, "submit_one"))
        self.assertIn("fcntl", source)


if __name__ == "__main__":
    unittest.main()
