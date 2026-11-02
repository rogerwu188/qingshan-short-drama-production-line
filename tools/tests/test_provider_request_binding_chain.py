"""The data actually sent must be the data that was reviewed.

Line owner 2026-11-01, item 3.  Three gaps this file pins shut:

  * a record outside the policy said ``NOT_REQUIRED``, which reads as a pass —
    it now says ``UNENFORCED`` and carries a note saying nothing was checked;
  * the Q1 / SFE evidence records bound the review-request sha but not the task
    id, the prompt sha, the references (source + transport), the model or the
    payload — they carry a ``provider_request_binding`` block instead, with the
    fields that cannot exist yet present as ``null`` plus a reason;
  * nothing joined a provider receipt back to the reviewed record.  ``bind_receipt``
    does, keyed by the request sha on both sides, and refuses when the request on
    disk has changed since review.

Free and offline: no provider call, no network, every path a temp dir.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import tools.provider_request_digest as prd


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _policy(tmp: Path, **payload) -> Path:
    path = tmp / "policy.json"
    path.write_text(json.dumps({"enabled_episodes": [], "enabled_from_episode": None, **payload}),
                    encoding="utf-8")
    return path


def _reference_tree(tmp: Path) -> tuple[Path, Path]:
    prompt = tmp / "prompt.txt"
    prompt.write_text("PROMPT v1", encoding="utf-8")
    plate = tmp / "plate.png"
    plate.write_bytes(b"identity-plate")
    return prompt, plate


def _manifest_row(tmp: Path) -> tuple[dict, Path]:
    prompt, plate = _reference_tree(tmp)
    return {
        "manifest_task_key": "E99-S01-01-KEYFRAME-V1",
        "model": "gpt-image-2-pro",
        "prompt_file": str(prompt),
        "prompt_sha256": _sha(b"PROMPT v1"),
        "references": [
            {"role": "character", "entity_id": "CHAR-A", "view": "FRONT_NEUTRAL_HEADSHOT",
             "path": str(plate), "sha256": _sha(b"identity-plate")},
            {"role": "subspace_layout", "entity_id": "SUBSPACE-1", "kind": "SHOT_SUBSPACE_LAYOUT",
             "path": str(tmp / "gone.png"), "sha256": "a" * 64},
        ],
        "reviewed_request_sha256": "c" * 64,
    }, prompt


class UnenforcedIsNotAPassTest(unittest.TestCase):
    """Item 3: a policy that is off must not read as a pass."""

    def test_unbound_send_on_an_unenforced_episode_reports_unenforced(self):
        report = prd.require_reviewed_request({"task_key": "T", "episode": "E12"}, "y" * 64)
        self.assertEqual(report["status"], "UNENFORCED")
        self.assertEqual(report["enforcement"], "UNENFORCED")
        self.assertIn("UNENFORCED", report["note"])
        self.assertNotIn(report["status"], {"PASS", "MATCH", "NOT_REQUIRED"})

    def test_enforced_episode_without_a_binding_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = _policy(Path(tmp), enabled_episodes=["E99"])
            with mock.patch.object(prd, "POLICY", policy):
                with self.assertRaisesRegex(ValueError, "REVIEWED_REQUEST_NOT_BOUND"):
                    prd.require_reviewed_request({"task_key": "T", "episode": "E99"}, "y" * 64)

    def test_enforcement_status_is_never_a_pass_word(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = _policy(Path(tmp), enabled_episodes=["E99"], enabled_from_episode="E50")
            with mock.patch.object(prd, "POLICY", policy):
                self.assertEqual(prd.enforcement_status({"episode": "E99"}), "ENFORCED")
                self.assertEqual(prd.enforcement_status({"episode": "E50"}), "ENFORCED")
                self.assertEqual(prd.enforcement_status({"episode": "E49"}), "UNENFORCED")


class StagedRecordTest(unittest.TestCase):
    """Item 1: fields that cannot exist yet are null WITH a reason, never invented."""

    def test_before_any_post_the_task_id_is_null_and_explained(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(prd, "POLICY", _policy(Path(tmp))):
            row, _prompt = _manifest_row(Path(tmp))
            block = prd.binding_block(row, episode="E12", task_key="E12-S01-01",
                                      kind="KEYFRAME_VIDEO_SUBMIT",
                                      review_request_path=Path(tmp) / "req.json",
                                      review_request_sha256="d" * 64)
            self.assertEqual(block["stage"], prd.STAGE_REVIEWED)
            self.assertIsNone(block["task_id"])
            self.assertEqual(block["nulls"]["task_id"], "NOT_YET_ASSIGNED_BY_PROVIDER")
            self.assertIn("payload_sha256", block["nulls"])
            self.assertEqual(block["provider_request"]["prompt_sha256"], _sha(b"PROMPT v1"))
            self.assertEqual(block["provider_request"]["request_sha256"], "c" * 64)

    def test_a_missing_reference_is_recorded_not_dropped(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(prd, "POLICY", _policy(Path(tmp))):
            row, _prompt = _manifest_row(Path(tmp))
            block = prd.binding_block(row, episode="E12", task_key="T", kind="KEYFRAME_VIDEO_SUBMIT")
            roles = [entry["role"] for entry in block["references"]]
            self.assertEqual(roles, ["IDENTITY", "SPACE"])
            missing = [entry for entry in block["references"] if entry["status"] != "PRESENT"]
            self.assertEqual(len(missing), 1)
            self.assertEqual(missing[0]["role"], "SPACE")
            self.assertIn(f"references[{missing[0]['index']}].source_sha256", block["nulls"])
            # every reference names version + both shas keys, transport still unknown
            for entry in block["references"]:
                self.assertIn("version", entry)
                self.assertIn("source_sha256", entry)
                self.assertIn("transport_sha256", entry)
                self.assertIn(f"references[{entry['index']}].transport_sha256", block["nulls"])

    def test_an_unlisted_item_gets_no_invented_provider_row(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(prd, "POLICY", _policy(Path(tmp))):
            block = prd.binding_block(None, episode="E12", task_key="T", kind="KEYFRAME_VIDEO_SUBMIT")
            self.assertEqual(block["stage"], prd.STAGE_NO_PROVIDER_ROW)
            self.assertIn("provider_request", block["nulls"])
            self.assertIsNone(block["provider_request"]["request_sha256"])

    def test_disabled_policy_still_records_and_says_unenforced(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(prd, "POLICY", _policy(Path(tmp))):
            row, _prompt = _manifest_row(Path(tmp))
            block = prd.binding_block(row, episode="E12", task_key="T", kind="KEYFRAME_VIDEO_SUBMIT")
            self.assertEqual(block["policy"]["status"], "UNENFORCED")
            self.assertFalse(block["policy"]["binding_required"])


class BindingInvalidationTest(unittest.TestCase):
    """Item 3: change anything bound and the binding is invalid, re-review required."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self._policy_patch = mock.patch.object(prd, "POLICY", _policy(self.tmp, enabled_episodes=["E99"]))
        self._policy_patch.start()
        self.addCleanup(self._policy_patch.stop)
        self.prompt, self.plate = _reference_tree(self.tmp)
        self.row, _ = _manifest_row(self.tmp)

    def binding(self) -> dict:
        return prd.binding_block(self.row, episode="E99", task_key="T", kind="KEYFRAME_VIDEO_SUBMIT")

    def test_unchanged_request_is_valid(self):
        report = prd.binding_still_valid(self.binding(), prompt_text="PROMPT v1",
                                         reference_paths=[self.plate], model="gpt-image-2-pro")
        self.assertEqual(report["status"], prd.STATUS_VALID)
        self.assertFalse(report["re_review_required"])
        # the SPACE reference was already missing when the review was taken: a
        # coverage gap that is reported, not a change to the request
        self.assertEqual(report["references_missing"], [2])

    def test_changing_the_prompt_text_invalidates(self):
        report = prd.binding_still_valid(self.binding(), prompt_text="PROMPT v2",
                                         reference_paths=[self.plate], model="gpt-image-2-pro")
        self.assertEqual(report["status"], prd.STATUS_INVALID)
        self.assertIn("PROMPT_TEXT_CHANGED", report["reasons"])
        self.assertTrue(report["re_review_required"])

    def test_changing_a_reference_file_invalidates(self):
        binding = self.binding()          # bound while the file still matched
        self.plate.write_bytes(b"a different plate")
        report = prd.binding_still_valid(binding, prompt_text="PROMPT v1",
                                         reference_paths=[self.plate], model="gpt-image-2-pro")
        self.assertEqual(report["status"], prd.STATUS_INVALID)
        self.assertIn("REFERENCE_FILE_CHANGED:1:plate.png", report["reasons"])
        self.assertTrue(report["re_review_required"])

    def test_a_reference_changed_before_the_block_is_built_is_flagged(self):
        self.plate.write_bytes(b"changed on disk")
        row = dict(self.row)
        row["references"] = [dict(self.row["references"][0]),
                             dict(self.row["references"][1])]
        block = prd.binding_block(row, episode="E99", task_key="T", kind="KEYFRAME_VIDEO_SUBMIT")
        self.assertEqual(block["references"][0]["status"], "CHANGED_SINCE_AUTHORED")
        self.assertIn("references[1].source_sha256", block["nulls"])

    def test_changing_the_model_invalidates(self):
        report = prd.binding_still_valid(self.binding(), prompt_text="PROMPT v1",
                                         reference_paths=[self.plate], model="seedance-2.0-pro")
        self.assertEqual(report["status"], prd.STATUS_INVALID)
        self.assertIn("MODEL_CHANGED", report["reasons"])

    def test_changing_the_payload_invalidates(self):
        bound = {**self.binding(), "payload_sha256": "e" * 64}
        report = prd.binding_still_valid(bound, payload_sha="f" * 64)
        self.assertEqual(report["status"], prd.STATUS_INVALID)
        self.assertIn("PAYLOAD_CHANGED", report["reasons"])

    def test_a_record_with_no_request_digest_is_invalid_under_the_policy(self):
        unbound = prd.binding_block({**self.row, "reviewed_request_sha256": None},
                                    episode="E99", task_key="T", kind="KEYFRAME_VIDEO_SUBMIT")
        report = prd.binding_still_valid(unbound)
        self.assertEqual(report["status"], prd.STATUS_INVALID)
        self.assertIn("NO_REVIEWED_REQUEST_DIGEST_BOUND", report["reasons"])
        self.assertTrue(report["re_review_required"])

    def test_the_whole_request_digest_is_the_authority(self):
        report = prd.binding_still_valid(self.binding(), computed_request_sha256="9" * 64)
        self.assertEqual(report["status"], prd.STATUS_INVALID)
        self.assertIn("REQUEST_DIGEST_CHANGED", report["reasons"])


class ReceiptBindingTest(unittest.TestCase):
    """Item 2: the post-receipt binder joins on the request sha, and refuses drift."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self._policy_patch = mock.patch.object(prd, "POLICY", _policy(self.tmp, enabled_episodes=["E99"]))
        self._policy_patch.start()
        self.addCleanup(self._policy_patch.stop)
        self.request = self.tmp / "review_request.json"
        self.request.write_text(json.dumps({"kind": "keyframe", "items": []}), encoding="utf-8")
        self.request_sha = _sha(self.request.read_bytes())
        self.row, _ = _manifest_row(self.tmp)
        self.binding = prd.binding_block(self.row, episode="E99", task_key="E99-S01-01",
                                         kind="KEYFRAME_VIDEO_SUBMIT",
                                         review_request_path=self.request,
                                         review_request_sha256=self.request_sha)
        self.transaction = {
            "schema": "qingshan.giggle_submit_transaction.v1",
            "task_key": "E99-S01-01", "attempt_id": "attempt-1",
            "submission_fingerprint": "f" * 64, "state": "SUBMITTED_TASK_ID_BOUND",
            "task_id": "provider-task-1",
            "request_binding": {"request_sha256": "c" * 64},
            "sent_reference_sha256": ["1" * 64, "2" * 64],
            "provider_response": {"task_id": "provider-task-1", "code": 0,
                                  "data": {"task_id": "provider-task-1"}},
        }

    def test_receipt_binds_the_task_id_to_the_same_record(self):
        bound = prd.bind_receipt(self.binding, self.transaction, request_path=self.request)
        self.assertEqual(bound["stage"], prd.STAGE_BOUND)
        self.assertEqual(bound["task_id"], "provider-task-1")
        self.assertNotIn("task_id", bound["nulls"])
        self.assertEqual([row["transport_sha256"] for row in bound["references"]],
                         ["1" * 64, "2" * 64])
        self.assertNotIn("references[1].transport_sha256", bound["nulls"])
        self.assertEqual(bound["provider_echo"]["task_id"], "provider-task-1")
        self.assertEqual(bound["transaction"]["state"], "SUBMITTED_TASK_ID_BOUND")
        # the semantic digest is unchanged by the bind: it is the join key
        self.assertEqual(bound["provider_request"]["request_sha256"], "c" * 64)

    def test_a_transaction_for_another_request_is_refused(self):
        other = {**self.transaction, "request_binding": {"request_sha256": "9" * 64}}
        with self.assertRaisesRegex(ValueError, "RECEIPT_FOR_ANOTHER_REQUEST"):
            prd.bind_receipt(self.binding, other, request_path=self.request)

    def test_a_transaction_without_a_request_binding_is_refused(self):
        other = {key: value for key, value in self.transaction.items() if key != "request_binding"}
        with self.assertRaisesRegex(ValueError, "RECEIPT_NOT_REQUEST_BOUND"):
            prd.bind_receipt(self.binding, other, request_path=self.request)

    def test_a_request_changed_since_review_is_refused(self):
        self.request.write_text(json.dumps({"kind": "keyframe", "items": ["changed"]}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "REQUEST_SHA_CHANGED_SINCE_REVIEW"):
            prd.bind_receipt(self.binding, self.transaction, request_path=self.request)

    def test_a_transaction_without_a_task_id_is_refused(self):
        for state, task_id in ((None, "provider-task-1"), ("INTENT_RECORDED", None)):
            other = {**self.transaction, "state": state, "task_id": task_id}
            with self.assertRaisesRegex(ValueError, "TASK_ID_NOT_BOUND"):
                prd.bind_receipt(self.binding, other, request_path=self.request)

    def test_a_record_with_no_request_sha_cannot_be_bound(self):
        bare = prd.binding_block(None, episode="E99", task_key="T", kind="KEYFRAME_VIDEO_SUBMIT")
        with self.assertRaisesRegex(ValueError, "HAS_NO_REQUEST_SHA"):
            prd.bind_receipt(bare, self.transaction, request_path=self.request)

    def test_an_already_rebound_record_keeps_one_task_id(self):
        bound = prd.bind_receipt(self.binding, self.transaction, request_path=self.request)
        with self.assertRaisesRegex(ValueError, "RECEIPT_FOR_ANOTHER_REQUEST"):
            prd.bind_receipt(bound, {**self.transaction, "request_binding": {"request_sha256": "9" * 64}},
                             request_path=self.request)


class TransactionFileRoundTripTest(unittest.TestCase):
    """Bind from the real on-disk transaction shape, via the CLI, in a temp dir."""

    def test_cli_binds_a_transaction_file_into_a_record_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            transactions = tmp / "giggle_submit_transactions" / "E99"
            transactions.mkdir(parents=True)
            record_path = tmp / "admission_request.json"
            record = {"kind": "KEYFRAME_VIDEO_SUBMIT",
                      "provider_request_binding": prd.binding_block(
                          _manifest_row(tmp)[0], episode="E12", task_key="E99-S01-01",
                          kind="KEYFRAME_VIDEO_SUBMIT")}
            record_path.write_text(json.dumps(record), encoding="utf-8")
            transaction = {
                "schema": "qingshan.giggle_submit_transaction.v1",
                "task_key": "E99-S01-01", "submission_fingerprint": "a" * 64,
                "state": "SUBMITTED_TASK_ID_BOUND", "task_id": "task-42",
                "request_binding": {"request_sha256": "c" * 64},
                "sent_reference_sha256": [],
                "provider_response": {"task_id": "task-42"},
            }
            transaction_path = transactions / f"E99-S01-01__{'a' * 16}.json"
            transaction_path.write_text(json.dumps(transaction), encoding="utf-8")

            with mock.patch.object(prd, "POLICY", _policy(tmp)):
                code = prd.main(["bind-receipt", "--record", str(record_path),
                                 "--transaction", str(transaction_path),
                                 "--binding-key", "provider_request_binding"])
            self.assertEqual(code, 0)
            written = json.loads(record_path.read_text(encoding="utf-8"))
            self.assertEqual(written["provider_request_binding"]["task_id"], "task-42")
            self.assertEqual(written["provider_request_binding"]["stage"], prd.STAGE_BOUND)


if __name__ == "__main__":
    unittest.main()
