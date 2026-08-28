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
                observed["context"] = os.environ.get("QINGSHAN_DURABLE_SUBMITTER_CONTEXT")
                return {"data": {"task_id": "task-e43-test"}}

            prior = os.environ.pop("QINGSHAN_DURABLE_SUBMITTER_CONTEXT", None)
            try:
                with patch.object(submitter, "_request", side_effect=fake_request):
                    result = submitter.submit(row, root / "receipts", root / "transactions", "gpt-image-2-pro", "2K")
                transaction = json.loads(Path(submitter.ROOT / result["transaction"]).read_text(encoding="utf-8"))
                self.assertEqual(observed["context"], "1")
                self.assertIsNone(os.environ.get("QINGSHAN_DURABLE_SUBMITTER_CONTEXT"))
                self.assertEqual(transaction["episode"], "E43")
                self.assertEqual(transaction["state"], "SUBMITTED_TASK_ID_BOUND")
            finally:
                if prior is not None:
                    os.environ["QINGSHAN_DURABLE_SUBMITTER_CONTEXT"] = prior


if __name__ == "__main__":
    unittest.main()
