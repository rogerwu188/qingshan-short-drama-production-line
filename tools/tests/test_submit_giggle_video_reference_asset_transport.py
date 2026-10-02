"""Over-limit reference images travel as registered asset ids, not base64 (nalu throughput review 2026-10-02).

Two HTTP 524s on E10-VU-020 (37 MB of references -> ~51 MB base64 body) were the upstream cause of a
charged-but-untracked submission.  The fix registers each reference through the same asset path audio
references already use and sends ``{"asset_id": ...}`` entries.  These tests mock both the upload and
the POST -- no network call is ever made.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import submit_giggle_video_manifest_v2 as video


class ReferenceAssetTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.refs = []
        for index in range(3):
            path = self.root / f"ref-{index}.png"
            path.write_bytes(b"\x89PNG" + bytes([index]) * 64)
            self.refs.append(path)
        self.receipts = self.root / "receipts"
        self.transactions = self.root / "transactions"

    def _task(self, *, task_key="E10-U01-V2"):
        digest = "0" * 64
        prompt_file = self.root / f"{task_key}.txt"
        prompt_file.write_text("provider prompt", encoding="utf-8")
        return {
            "task_key": task_key, "episode": "E10", "unit_id": f"{task_key}-UNIT",
            "model": "seedance-2.0-pro", "duration_seconds": 4, "resolution": "720p",
            "prompt_file": str(prompt_file), "prompt_sha256": digest,
            "reference_images": [str(path) for path in self.refs],
            "reference_sha256": [digest for _ in self.refs],
        }

    def _over_limit(self):
        return patch.object(video, "REFERENCE_PAYLOAD_RAW_LIMIT_BYTES", 1)

    @staticmethod
    def _by_path(path):
        return {"asset_id": f"asset-{Path(path).name}"}

    @staticmethod
    def _expected_ids(refs):
        return [f"asset-{Path(path).name}" for path in refs]

    # -- over threshold: asset ids, recorded, fingerprint differs ------------------------------- #

    def test_over_threshold_registers_each_reference_as_asset_id(self):
        task = self._task()
        with self._over_limit(), patch.object(
            video, "_registered_asset", side_effect=self._by_path
        ) as register, patch.object(video, "_image_list") as base64_list:
            payload = video.reference_image_payload(task)
            base64_list.assert_not_called()
        self.assertEqual(register.call_count, len(self.refs))
        self.assertEqual([row["asset_id"] for row in payload], self._expected_ids(self.refs))
        self.assertNotIn("base64", json.dumps(payload))
        self.assertEqual(task["reference_image_asset_ids"], self._expected_ids(self.refs))

    def test_second_call_reuses_registered_ids_without_re_uploading(self):
        task = self._task()
        with self._over_limit(), patch.object(
            video, "_registered_asset", side_effect=self._by_path
        ) as register:
            first = video.reference_image_payload(task)
            second = video.reference_image_payload(task)
        self.assertEqual(register.call_count, len(self.refs))
        self.assertEqual(first, second)

    def test_asset_transport_fingerprint_differs_from_base64_for_same_unit(self):
        task = self._task()
        with patch.object(video, "REFERENCE_PAYLOAD_RAW_LIMIT_BYTES", 10 ** 12):
            base64_fingerprint = video.task_fingerprint(task)
        with self._over_limit():
            asset_fingerprint = video.task_fingerprint(task)
        self.assertNotEqual(base64_fingerprint, asset_fingerprint)

    def test_asset_transport_fingerprint_is_stable_across_registration(self):
        task = self._task()
        with self._over_limit(), patch.object(video, "_registered_asset", side_effect=self._by_path):
            before = video.task_fingerprint(task)
            video.reference_image_payload(task)  # registers and stamps ids onto the task
            after = video.task_fingerprint(task)
            self.assertEqual(video.reference_transport(task), video.REFERENCE_ASSET_TRANSPORT)
        self.assertEqual(before, after)

    # -- over threshold full POST: one POST, ids in payload and intent ------------------------- #

    def test_over_threshold_submission_posts_asset_ids_once_and_records_intent(self):
        task = self._task()
        with self._over_limit(), \
             patch.object(video, "prior_bound", return_value=None), \
             patch("tools.episode_prompt_batch_gate.require_generation_batch"), \
             patch.object(video, "sha256", return_value="0" * 64), \
             patch.object(video, "_registered_asset", side_effect=self._by_path) as register, \
             patch.object(video, "_request", return_value={"data": {"task_id": "task-123"}}) as post:
            result = video.submit_one(task, self.receipts, self.transactions)
        self.assertEqual(result["task_id"], "task-123")
        self.assertEqual(post.call_count, 1)
        payload = post.call_args.args[1]
        self.assertTrue(payload["images"])
        self.assertTrue(all(set(row) == {"asset_id"} for row in payload["images"]))
        self.assertEqual(register.call_count, len(self.refs))
        transaction = json.loads(Path(video.resolve(result["transaction"])).read_text(encoding="utf-8"))
        self.assertEqual(transaction["reference_transport"], video.REFERENCE_ASSET_TRANSPORT)
        self.assertEqual(transaction["reference_image_asset_ids"], self._expected_ids(self.refs))
        self.assertEqual(transaction["state"], "SUBMITTED_TASK_ID_BOUND")

    # -- bound-task recovery: zero uploads, zero POSTs ----------------------------------------- #

    def test_bound_task_recovery_uploads_nothing_and_posts_nothing(self):
        task = self._task()
        # Bind the task to a real transaction on disk whose fingerprint matches this task, so
        # prior_bound() (not a mock) drives the early return -- exactly the recovery path a re-entry
        # takes.  sha256 is left real; the prompt/reference files exist and match their recorded SHAs.
        digest = video.sha256(Path(task["prompt_file"]))
        task["prompt_sha256"] = digest
        task["reference_sha256"] = [video.sha256(path) for path in self.refs]
        self.transactions.mkdir(parents=True)
        with self._over_limit():
            fingerprint = video.task_fingerprint(task)
        (self.transactions / f"{task['task_key']}__{fingerprint[:16]}.json").write_text(json.dumps({
            "submission_fingerprint": fingerprint, "state": "SUBMITTED_TASK_ID_BOUND",
            "task_id": "task-already-bound", "receipt": None, "provider_response": None,
        }), encoding="utf-8")
        with self._over_limit(), \
             patch("tools.episode_prompt_batch_gate.require_generation_batch"), \
             patch.object(video, "_registered_asset") as register, \
             patch.object(video, "_request") as post:
            result = video.submit_one(task, self.receipts, self.transactions)
        self.assertEqual(result["task_id"], "task-already-bound")
        self.assertTrue(result["recovered_from_transaction"])
        register.assert_not_called()
        post.assert_not_called()

    # -- under threshold: unchanged payload and fingerprint ------------------------------------ #

    def test_under_threshold_keeps_base64_transport_and_unchanged_fingerprint(self):
        task = self._task()
        base64_rows = [{"base64": "AAA"}, {"base64": "BBB"}, {"base64": "CCC"}]
        with patch.object(video, "REFERENCE_PAYLOAD_RAW_LIMIT_BYTES", 10 ** 12), \
             patch.object(video, "_registered_asset") as register, \
             patch.object(video, "_image_list", return_value=base64_rows):
            payload = video.reference_image_payload(task)
            fingerprint = video.task_fingerprint(task)
            self.assertIsNone(video.reference_transport(task))
        register.assert_not_called()
        self.assertEqual(payload, base64_rows)
        # no reference_transport key is added to the contract when nothing is over the limit
        self.assertNotIn("reference_transport", json.dumps(fingerprint))

    # -- upload failure: not charged, no POST, pre-intent convention --------------------------- #

    def test_upload_failure_does_not_charge_or_post_and_leaves_no_transaction(self):
        task = self._task()
        with self._over_limit(), \
             patch.object(video, "prior_bound", return_value=None), \
             patch("tools.episode_prompt_batch_gate.require_generation_batch"), \
             patch.object(video, "sha256", return_value="0" * 64), \
             patch.object(video, "_registered_asset", side_effect=RuntimeError("upload exploded")), \
             patch.object(video, "_request") as post:
            with self.assertRaisesRegex(RuntimeError, "upload exploded"):
                video.submit_one(task, self.receipts, self.transactions)
        post.assert_not_called()
        self.assertFalse(self.transactions.exists() and list(self.transactions.glob("*.json")))


if __name__ == "__main__":
    unittest.main()
