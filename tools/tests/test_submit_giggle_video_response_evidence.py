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
        self.assertIn("for offset in range(0, len(tasks), concurrency)", source)


if __name__ == "__main__":
    unittest.main()
