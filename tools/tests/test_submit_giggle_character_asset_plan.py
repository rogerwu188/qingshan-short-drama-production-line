import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import submit_giggle_character_asset_plan as submitter


class CharacterAssetSubmitterTests(unittest.TestCase):
    def test_records_episode_and_scopes_durable_submitter_context(self):
        with tempfile.TemporaryDirectory(dir=submitter.ROOT) as temporary:
            root = Path(temporary)
            prompt = root / "prompt.txt"
            prompt.write_text("vertical historical character", encoding="utf-8")
            row = {
                "id": "CHAR-E43-TEST",
                "episode": "E43",
                "prompt_file": str(prompt),
                "prompt_sha256": submitter.hashlib.sha256(prompt.read_bytes()).hexdigest(),
                "reference_images": [],
                "reference_image_sha256s": [],
            }
            observed = {}

            def fake_request(endpoint, payload):
                from tools.giggle_api_client import _DURABLE_GENERATION_CONTEXT
                observed["context"] = _DURABLE_GENERATION_CONTEXT.get()
                return {"data": {"task_id": "task-e43-test"}}

            prior = os.environ.pop("QINGSHAN_DURABLE_SUBMITTER_CONTEXT", None)
            try:
                with patch.object(submitter, "_request", side_effect=fake_request):
                    result = submitter.submit(row, root / "receipts", root / "transactions", "gpt-image-2-pro", "2K")
                transaction = json.loads(Path(submitter.ROOT / result["transaction"]).read_text(encoding="utf-8"))
                self.assertTrue(observed["context"])
                self.assertIsNone(os.environ.get("QINGSHAN_DURABLE_SUBMITTER_CONTEXT"))
                self.assertEqual(transaction["episode"], "E43")
                self.assertEqual(transaction["state"], "SUBMITTED_TASK_ID_BOUND")
            finally:
                if prior is not None:
                    os.environ["QINGSHAN_DURABLE_SUBMITTER_CONTEXT"] = prior

    def test_missing_task_id_keeps_provider_response_in_transaction(self):
        with tempfile.TemporaryDirectory(dir=submitter.ROOT) as temporary:
            root = Path(temporary)
            prompt = root / "prompt.txt"
            prompt.write_text("vertical historical character", encoding="utf-8")
            row = {
                "id": "CHAR-E02-TEST",
                "episode": "E02",
                "prompt_file": str(prompt),
                "prompt_sha256": submitter.hashlib.sha256(prompt.read_bytes()).hexdigest(),
                "reference_images": [],
                "reference_image_sha256s": [],
            }
            body = {"code": 500, "msg": "payment failed", "uuid": "u-1", "data": None}
            with patch.object(submitter, "_request", return_value=body):
                with self.assertRaises(RuntimeError) as raised:
                    submitter.submit(row, root / "receipts", root / "transactions", "gpt-image-2-pro", "2K")
            self.assertIn("code=500", str(raised.exception))
            path = submitter.transaction_path(root / "transactions", row, "gpt-image-2-pro", "2K")
            transaction = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(transaction["state"], "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION")
            self.assertEqual(transaction["provider_response"], body)


    def test_dns_failure_is_recorded_as_not_charged_and_retryable(self):
        with tempfile.TemporaryDirectory(dir=submitter.ROOT) as temporary:
            root = Path(temporary)
            prompt = root / "prompt.txt"
            prompt.write_text("vertical historical character", encoding="utf-8")
            row = {"id": "CHAR-DNS-TEST", "episode": "E01", "prompt_file": str(prompt),
                   "prompt_sha256": submitter.hashlib.sha256(prompt.read_bytes()).hexdigest(),
                   "reference_images": [], "reference_image_sha256s": []}
            err = SystemExit("NETWORK: NOT_SENT_DNS_RESOLUTION_FAILED: <urlopen error [Errno -3] "
                             "Temporary failure in name resolution>")
            with patch.object(submitter, "_request", side_effect=err):
                with self.assertRaises(SystemExit):
                    submitter.submit(row, root / "receipts", root / "transactions", "gpt-image-2-pro", "2K")
            path = submitter.transaction_path(root / "transactions", row, "gpt-image-2-pro", "2K")
            transaction = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(transaction["state"], "NOT_CHARGED_RETRYABLE")
            self.assertIsNone(submitter.prior_submission(row, root / "transactions", "gpt-image-2-pro", "2K"))


if __name__ == "__main__":
    unittest.main()
