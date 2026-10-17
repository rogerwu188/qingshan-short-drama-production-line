"""Plan §7 / §10 items 9, 10, 11: the review binds the request that is actually sent.

Free and offline.  Every provider call is replaced with a mock that fails the
test if it is reached, so "refused" provably means zero POSTs.
"""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import tools.provider_request_digest as prd
from tools.provider_request_digest import (
    bound_under_other_fingerprint,
    request_digest,
    require_no_silent_resubmission,
    require_reviewed_request,
)


def _digest(**overrides):
    base = dict(prompt_text="P", model="MiniMax-H3", duration=6, aspect_ratio="9:16",
                resolution="768p", reference_sha256=["a" * 64, "b" * 64], audio=["url:x"])
    base.update(overrides)
    return request_digest(**base)


class DigestCoversWhatIsSentTest(unittest.TestCase):
    """§10.9: changing prompt, reference order or a parameter changes the digest."""

    def test_each_sent_field_moves_the_digest(self):
        base = _digest()
        for change in (
            {"prompt_text": "P2"},
            {"reference_sha256": ["b" * 64, "a" * 64]},   # order only
            {"duration": 8},
            {"model": "seedance-2.0-pro"},
            {"resolution": "720p"},
            {"audio": ["url:y"]},
        ):
            self.assertNotEqual(_digest(**change), base, change)

    def test_identical_request_has_identical_digest(self):
        self.assertEqual(_digest(), _digest())


class ReviewBindingTest(unittest.TestCase):
    def test_mismatch_is_refused_even_without_the_policy(self):
        with self.assertRaisesRegex(ValueError, "REVIEWED_REQUEST_MISMATCH"):
            require_reviewed_request({"task_key": "T", "reviewed_request_sha256": "x" * 64}, "y" * 64)

    def test_match_passes(self):
        report = require_reviewed_request({"task_key": "T", "reviewed_request_sha256": "x" * 64}, "x" * 64)
        self.assertEqual(report["status"], "MATCH")

    def test_unbound_task_on_an_unenabled_episode_is_unaffected(self):
        report = require_reviewed_request({"task_key": "T", "episode": "E12"}, "y" * 64)
        self.assertEqual(report["status"], "NOT_REQUIRED")

    def test_enabled_episode_requires_a_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = Path(tmp) / "p.json"
            policy.write_text(json.dumps({"enabled_episodes": ["E99"]}), encoding="utf-8")
            with mock.patch.object(prd, "POLICY", policy):
                with self.assertRaisesRegex(ValueError, "REVIEWED_REQUEST_NOT_BOUND"):
                    require_reviewed_request({"task_key": "T", "episode": "E99"}, "y" * 64)


class SilentResubmissionTest(unittest.TestCase):
    """§10.11: a task already bound under another fingerprint is not re-POSTed silently."""

    def _store(self, tmp):
        (Path(tmp) / "T__aaaaaaaaaaaaaaaa.json").write_text(json.dumps(
            {"task_key": "T", "submission_fingerprint": "a" * 64,
             "state": "SUBMITTED_TASK_ID_BOUND", "task_id": "tid-1"}), encoding="utf-8")

    def test_detects_a_bound_record_under_another_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._store(tmp)
            self.assertEqual(bound_under_other_fingerprint(Path(tmp), "T", "b" * 64), ["a" * 64])
            self.assertEqual(bound_under_other_fingerprint(Path(tmp), "T", "a" * 64), [])

    def test_enabled_episode_requires_an_explicit_supersede(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._store(tmp)
            policy = Path(tmp) / "p.json"
            policy.write_text(json.dumps({"enabled_episodes": ["E99"]}), encoding="utf-8")
            with mock.patch.object(prd, "POLICY", policy):
                with self.assertRaisesRegex(ValueError, "BOUND_UNDER_OTHER_FINGERPRINT"):
                    require_no_silent_resubmission({"task_key": "T", "episode": "E99"}, Path(tmp), "b" * 64)
                require_no_silent_resubmission(
                    {"task_key": "T", "episode": "E99", "supersedes_submission_fingerprints": ["a" * 64]},
                    Path(tmp), "b" * 64)

    def test_unenabled_episode_keeps_todays_reroll_flow(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._store(tmp)
            require_no_silent_resubmission({"task_key": "T", "episode": "E12"}, Path(tmp), "b" * 64)


class VideoSubmitterZeroPostTest(unittest.TestCase):
    """§10.10: a binding failure at the real entrypoint makes zero POSTs and no intent record."""

    def test_mismatch_refuses_before_intent_and_before_post(self):
        import tools.submit_giggle_video_manifest_v2 as submitter
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            prompt = tmp / "p.txt"; prompt.write_text("PROMPT", encoding="utf-8")
            ref = tmp / "r.png"; ref.write_bytes(b"ref")
            task = {
                "task_key": "E99-VU-001", "episode": "E99", "model": "MiniMax-H3",
                "duration_seconds": 6, "resolution": "768p", "aspect_ratio": "9:16",
                "prompt_file": str(prompt), "prompt_sha256": hashlib.sha256(b"PROMPT").hexdigest(),
                "reference_images": [str(ref)], "reference_sha256": [hashlib.sha256(b"ref").hexdigest()],
                "reviewed_request_sha256": "0" * 64,
            }
            def forbidden(*_a, **_k):
                raise AssertionError("provider POST reached")
            with mock.patch.object(submitter, "_request", forbidden), \
                 mock.patch("tools.episode_prompt_batch_gate.require_generation_batch", lambda *a, **k: None), \
                 mock.patch.object(submitter, "prompt_scope_gate_active", lambda _t: False), \
                 mock.patch.object(submitter, "_reference_image_transport",
                                   lambda _t: ([{"base64": "cmVm"}], [])), \
                 mock.patch.object(submitter, "task_fingerprint", lambda _t: "f" * 64):
                with self.assertRaisesRegex(ValueError, "REVIEWED_REQUEST_MISMATCH"):
                    submitter.submit_one(task, tmp / "receipts", tmp / "tx")
            self.assertFalse((tmp / "tx").exists() and any((tmp / "tx").glob("*.json")),
                             "a refused request must leave no intent record")

    def test_matching_binding_reaches_the_provider(self):
        import tools.submit_giggle_video_manifest_v2 as submitter
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            prompt = tmp / "p.txt"; prompt.write_text("PROMPT", encoding="utf-8")
            ref = tmp / "r.png"; ref.write_bytes(b"ref")
            task = {
                "task_key": "E99-VU-002", "episode": "E99", "model": "MiniMax-H3",
                "duration_seconds": 6, "resolution": "768p", "aspect_ratio": "9:16",
                "prompt_file": str(prompt), "prompt_sha256": hashlib.sha256(b"PROMPT").hexdigest(),
                "reference_images": [str(ref)], "reference_sha256": [hashlib.sha256(b"ref").hexdigest()],
            }
            task["reviewed_request_sha256"] = prd.task_request_digest(
                task, prompt_text="PROMPT", reference_paths=[ref], duration=6, audio=[])["request_sha256"]
            reached = []
            def fake_request(*_a, **_k):
                reached.append(1)
                raise RuntimeError("stop after the POST attempt")
            with mock.patch.object(submitter, "_request", fake_request), \
                 mock.patch("tools.episode_prompt_batch_gate.require_generation_batch", lambda *a, **k: None), \
                 mock.patch.object(submitter, "prompt_scope_gate_active", lambda _t: False), \
                 mock.patch.object(submitter, "_reference_image_transport",
                                   lambda _t: ([{"base64": "cmVm"}], [])), \
                 mock.patch.object(submitter, "task_fingerprint", lambda _t: "f" * 64), \
                 mock.patch.object(submitter, "paid_video_submission_context", mock.MagicMock()):
                try:
                    submitter.submit_one(task, tmp / "receipts", tmp / "tx")
                except Exception:
                    pass
            self.assertEqual(reached, [1], "a matching review must not block the request")
            intent = json.loads(next((tmp / "tx").glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual(intent["request_binding"]["status"], "MATCH")
            self.assertEqual(intent["sent_reference_sha256"], [hashlib.sha256(b"ref").hexdigest()])


if __name__ == "__main__":
    unittest.main()
