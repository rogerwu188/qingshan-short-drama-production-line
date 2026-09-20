import fcntl
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools/storyclaw_audio_provider.py"
SPEC = importlib.util.spec_from_file_location("storyclaw_audio_provider", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class StoryClawAudioProviderTest(unittest.TestCase):
    @staticmethod
    def _paid_env(key="secret"):
        return {
            "GIGGLE_API_KEY": key,
            "NALU_PAID_CONFIG_LOCK": "1",
            "NALU_PAID_AUTHORIZATION_REF": "ORDER-TEST-1",
            "NALU_PAID_ORDER_SEQ": "1",
            "NALU_SUPERVISOR_ORDERS_SHA256": "a" * 64,
        }

    def test_cli_help_exposes_compatible_commands(self):
        for command in ("speech-generate", "bgm-generate"):
            completed = subprocess.run(
                [sys.executable, str(MODULE_PATH), command, "--help"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIn("--transaction", completed.stdout)
            self.assertIn("--paid", completed.stdout)

    def test_dry_run_needs_no_key_and_never_writes_or_posts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            transaction = root / "transactions/speech.json"
            with patch.dict(os.environ, {}, clear=True), patch.object(
                MODULE, "_api_post"
            ) as post:
                result = MODULE.generate_speech(
                    "测试对白",
                    root / "audio",
                    voice_id="voice-1",
                    emotion="克制",
                    transaction=transaction,
                )
            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "DRY_RUN")
            self.assertFalse(result["providerPostAllowed"])
            self.assertFalse(transaction.exists())
            post.assert_not_called()

    def test_relative_transaction_path_is_rejected_before_network(self):
        with patch.object(MODULE, "_api_post") as post:
            with self.assertRaisesRegex(MODULE.AudioProviderError, "absolute path"):
                MODULE.generate_bgm(
                    "restrained instrumental pulse",
                    "/tmp/audio",
                    transaction="relative/transaction.json",
                    paid=True,
                )
            post.assert_not_called()

    def test_paid_request_requires_both_config_and_line_owner_authority(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"GIGGLE_API_KEY": "secret"}, clear=True
        ), patch.object(MODULE, "_api_post") as post:
            with self.assertRaisesRegex(MODULE.AudioProviderError, "paid authority"):
                MODULE.generate_speech(
                    "测试对白", Path(tmp) / "audio",
                    voice_id="voice-1", emotion="克制",
                    transaction=Path(tmp) / "transaction.json", paid=True,
                )
            post.assert_not_called()

    def test_voice_catalog_is_read_only_and_normalized(self):
        with patch.object(MODULE, "_get", return_value={
            "code": 200,
            "data": [
                {"voice_id": "v1", "name": "Voice One", "gender": "female"},
                {"name": "missing id"},
            ],
        }) as get:
            result = MODULE.list_speech_voices()
        get.assert_called_once_with(MODULE.VOICES_ENDPOINT, {})
        self.assertTrue(result["ok"])
        self.assertEqual(result["voices"], [{
            "voice_id": "v1", "voice_name": "Voice One", "style": None,
            "gender": "female", "age": None, "language": None,
        }])

    def test_paid_speech_persists_locked_intent_then_binds_and_completes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            transaction = root / "transactions/speech.json"
            key = "test-key-that-must-never-be-persisted"
            observed = {}

            def post(endpoint, payload):
                self.assertEqual(endpoint, MODULE.SPEECH_ENDPOINT)
                intent = json.loads(transaction.read_text(encoding="utf-8"))
                self.assertEqual(intent["state"], "INTENT_RECORDED")
                self.assertEqual(intent["provider_post_count"], 1)
                observed["intent"] = intent
                return {"code": 200, "data": {"task_id": "speech-task-1"}}

            def download(url, destination, *, overwrite):
                self.assertEqual(url, "https://signed.example/speech.mp3")
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"speech-bytes")
                return {
                    "path": str(destination),
                    "size": destination.stat().st_size,
                    "sha256": MODULE._sha256_file(destination),
                    "contentType": "audio/mpeg",
                }

            with patch.dict(os.environ, self._paid_env(key), clear=True), patch.object(
                MODULE, "_api_post", side_effect=post
            ) as post_mock, patch.object(
                MODULE,
                "_api_query",
                return_value={
                    "code": 200,
                    "data": {
                        "status": "completed",
                        "urls": ["https://signed.example/speech.mp3"],
                    },
                },
            ), patch.object(MODULE, "_download", side_effect=download), patch.object(
                MODULE.time, "sleep", return_value=None
            ), patch.object(MODULE.fcntl, "flock", wraps=fcntl.flock) as flock:
                result = MODULE.generate_speech(
                    "测试对白",
                    root / "audio",
                    voice_id="voice-1",
                    emotion="克制",
                    transaction=transaction,
                    paid=True,
                    poll_interval_seconds=2,
                    timeout_seconds=10,
                )

            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["taskId"], "speech-task-1")
            self.assertEqual(result["capability"], "AGENTCUT-SPEECH-001")
            post_mock.assert_called_once()
            self.assertTrue(any(call.args[1] == fcntl.LOCK_EX for call in flock.call_args_list))
            persisted_text = transaction.read_text(encoding="utf-8")
            persisted = json.loads(persisted_text)
            self.assertEqual(persisted["state"], "TERMINAL_COMPLETED")
            self.assertEqual(persisted["task_id"], "speech-task-1")
            self.assertNotIn(key, persisted_text)
            self.assertNotIn("https://signed.example", persisted_text)
            self.assertNotIn("测试对白", persisted_text)
            self.assertNotIn("x-auth", persisted_text)
            self.assertEqual(observed["intent"]["request"]["text_sha256"], result["textSha256"])

    def test_lost_post_response_is_quarantined_and_never_reposted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            transaction = root / "lost.json"
            with patch.dict(os.environ, self._paid_env(), clear=True), patch.object(
                MODULE, "_api_post", side_effect=TimeoutError("ambiguous")
            ) as post:
                with self.assertRaisesRegex(MODULE.AudioProviderError, "quarantined"):
                    MODULE.generate_bgm(
                        "instrumental suspense",
                        root / "audio",
                        transaction=transaction,
                        paid=True,
                    )
                self.assertEqual(post.call_count, 1)
                persisted = json.loads(transaction.read_text(encoding="utf-8"))
                self.assertEqual(persisted["state"], "RESPONSE_LOST")

                post.side_effect = AssertionError("must not POST again")
                with self.assertRaises(MODULE.DuplicateSubmissionBlocked):
                    MODULE.generate_bgm(
                        "instrumental suspense",
                        root / "audio",
                        transaction=transaction,
                        paid=True,
                    )
                self.assertEqual(post.call_count, 1)

    def test_bound_task_resumes_query_without_second_post(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            transaction = root / "resume.json"
            with patch.dict(os.environ, self._paid_env(), clear=True), patch.object(
                MODULE,
                "_api_post",
                return_value={"code": 200, "data": {"task_id": "resume-task"}},
            ) as post, patch.object(
                MODULE, "_api_query", side_effect=TimeoutError("query unavailable")
            ), patch.object(MODULE.time, "sleep", return_value=None):
                with self.assertRaisesRegex(MODULE.AudioProviderError, "rerun to resume"):
                    MODULE.generate_bgm(
                        "quiet instrumental bed",
                        root / "audio",
                        transaction=transaction,
                        paid=True,
                    )
            self.assertEqual(post.call_count, 1)
            self.assertEqual(
                json.loads(transaction.read_text(encoding="utf-8"))["state"],
                "TASK_ID_BOUND_QUERY_PENDING",
            )

            def download(_url, destination, *, overwrite):
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"bgm")
                return {
                    "path": str(destination),
                    "size": 3,
                    "sha256": MODULE._sha256_file(destination),
                    "contentType": "audio/mpeg",
                }

            with patch.dict(os.environ, self._paid_env(), clear=True), patch.object(
                MODULE, "_api_post"
            ) as second_post, patch.object(
                MODULE,
                "_api_query",
                return_value={
                    "code": 200,
                    "data": {"status": "completed", "urls": ["https://signed.example/bgm.mp3"]},
                },
            ), patch.object(MODULE, "_download", side_effect=download), patch.object(
                MODULE.time, "sleep", return_value=None
            ):
                result = MODULE.generate_bgm(
                    "quiet instrumental bed",
                    root / "audio",
                    transaction=transaction,
                    paid=True,
                )
            second_post.assert_not_called()
            self.assertTrue(result["ok"])
            self.assertEqual(result["taskId"], "resume-task")

    def test_bgm_compatible_result_has_all_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            transaction = root / "bgm.json"

            def download(url, destination, *, overwrite):
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(url.encode("utf-8"))
                return {
                    "path": str(destination),
                    "size": destination.stat().st_size,
                    "sha256": MODULE._sha256_file(destination),
                    "contentType": "audio/mpeg",
                }

            with patch.dict(os.environ, self._paid_env(), clear=True), patch.object(
                MODULE,
                "_api_post",
                return_value={"code": 200, "data": {"task_id": "bgm-task"}},
            ), patch.object(
                MODULE,
                "_api_query",
                return_value={
                    "code": 200,
                    "data": {"status": "completed", "urls": ["url-a", "url-b"]},
                },
            ), patch.object(MODULE, "_download", side_effect=download), patch.object(
                MODULE.time, "sleep", return_value=None
            ):
                result = MODULE.generate_bgm(
                    "restrained instrumental score",
                    root / "audio",
                    transaction=transaction,
                    paid=True,
                )
            self.assertEqual(result["capability"], "AGENTCUT-BGM-001")
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["urlCount"], 2)
            self.assertEqual(len(result["files"]), 2)
            self.assertFalse(result["releaseEligible"])

    def test_partial_bgm_download_resumes_without_replacing_first_file_or_posting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            transaction = root / "bgm-resume.json"
            first_calls = []

            def interrupted_download(url, destination, *, overwrite):
                first_calls.append(url)
                if url == "url-b":
                    raise OSError("download interrupted")
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"first")
                return {
                    "path": str(destination),
                    "size": 5,
                    "sha256": MODULE._sha256_file(destination),
                    "contentType": "audio/mpeg",
                }

            completed_query = {
                "code": 200,
                "data": {"status": "completed", "urls": ["url-a", "url-b"]},
            }
            with patch.dict(os.environ, self._paid_env(), clear=True), patch.object(
                MODULE,
                "_api_post",
                return_value={"code": 200, "data": {"task_id": "bgm-resume-task"}},
            ) as post, patch.object(
                MODULE, "_api_query", return_value=completed_query
            ), patch.object(
                MODULE, "_download", side_effect=interrupted_download
            ), patch.object(MODULE.time, "sleep", return_value=None):
                with self.assertRaisesRegex(OSError, "interrupted"):
                    MODULE.generate_bgm(
                        "measured instrumental underscore",
                        root / "audio",
                        transaction=transaction,
                        paid=True,
                    )
            self.assertEqual(post.call_count, 1)
            self.assertEqual(first_calls, ["url-a", "url-b"])
            saved = json.loads(transaction.read_text(encoding="utf-8"))
            self.assertEqual(saved["state"], "TASK_ID_BOUND_COMPLETED_DOWNLOAD_PENDING")
            self.assertEqual(len(saved["downloaded_files"]), 1)

            second_calls = []

            def resumed_download(url, destination, *, overwrite):
                second_calls.append(url)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"second")
                return {
                    "path": str(destination),
                    "size": 6,
                    "sha256": MODULE._sha256_file(destination),
                    "contentType": "audio/mpeg",
                }

            with patch.dict(os.environ, self._paid_env(), clear=True), patch.object(
                MODULE, "_api_post"
            ) as second_post, patch.object(
                MODULE, "_api_query", return_value=completed_query
            ), patch.object(
                MODULE, "_download", side_effect=resumed_download
            ), patch.object(MODULE.time, "sleep", return_value=None):
                result = MODULE.generate_bgm(
                    "measured instrumental underscore",
                    root / "audio",
                    transaction=transaction,
                    paid=True,
                )
            second_post.assert_not_called()
            self.assertEqual(second_calls, ["url-b"])
            self.assertTrue(result["ok"])
            self.assertEqual(len(result["files"]), 2)

    def test_download_is_atomic_and_records_digest_without_url(self):
        class Response:
            headers = {"Content-Type": "audio/mpeg"}

            def __init__(self):
                self.chunks = [b"abc", b"def", b""]

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _size):
                return self.chunks.pop(0)

        with tempfile.TemporaryDirectory() as tmp, patch.object(
            MODULE.urllib.request, "urlopen", return_value=Response()
        ):
            destination = Path(tmp) / "nested/audio.mp3"
            receipt = MODULE._download(
                "https://signed.example/audio.mp3", destination, overwrite=False
            )
            self.assertEqual(destination.read_bytes(), b"abcdef")
            self.assertEqual(receipt["sha256"], MODULE._sha256_file(destination))
            self.assertNotIn("url", receipt)
            self.assertEqual(list(destination.parent.glob("*.partial")), [])


if __name__ == "__main__":
    unittest.main()
