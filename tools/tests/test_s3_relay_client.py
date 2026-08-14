import importlib.util
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
CLIENT_PATH = ROOT / "workflow/s3_relay/relay_client.py"
SPEC = importlib.util.spec_from_file_location("s3_relay_client", CLIENT_PATH)
CLIENT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLIENT)


class S3RelaySafetyTests(unittest.TestCase):
    def _checklist(self, root: Path, enabled=True) -> Path:
        path = root / "checklist.json"
        checks = {name: enabled for name in CLIENT.REQUIRED_CHECKS}
        path.write_text(json.dumps({"checks": checks}), encoding="utf-8")
        return path

    def test_complete_checklist_allows_public_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = root / "handshake.md"
            payload.write_text("Public relay handshake confirmation.", encoding="utf-8")
            CLIENT.validate_public_upload(payload, self._checklist(root))

    def test_incomplete_checklist_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = root / "handshake.md"
            payload.write_text("Public relay handshake confirmation.", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "checklist incomplete"):
                CLIENT.validate_public_upload(payload, self._checklist(root, enabled=False))

    def test_secret_pattern_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = root / "bad.md"
            payload.write_text("AWS_SECRET_ACCESS_KEY=do-not-publish", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "sensitive token"):
                CLIENT.validate_public_upload(payload, self._checklist(root))

    def test_env_file_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = root / "relay.env"
            payload.write_text("SAFE=NO", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "file type"):
                CLIENT.validate_public_upload(payload, self._checklist(root))

    def test_path_like_slug_fails(self):
        with self.assertRaisesRegex(ValueError, "invalid public object slug"):
            CLIENT._safe_slug("../a secret.md")

    def test_delivery_key_uses_files_channel_and_safe_slug(self):
        old_prefix = os.environ.get("S3_RELAY_PREFIX")
        os.environ["S3_RELAY_PREFIX"] = "relay/test"
        try:
            self.assertEqual(CLIENT._delivery_key("E20_V7.mp4"), "relay/test/files/E20_V7.mp4")
        finally:
            if old_prefix is None:
                os.environ.pop("S3_RELAY_PREFIX", None)
            else:
                os.environ["S3_RELAY_PREFIX"] = old_prefix

    def test_delivery_key_rejects_path_like_slug(self):
        old_prefix = os.environ.get("S3_RELAY_PREFIX")
        os.environ["S3_RELAY_PREFIX"] = "relay/test"
        try:
            with self.assertRaisesRegex(ValueError, "invalid public object slug"):
                CLIENT._delivery_key("../E20.mp4")
        finally:
            if old_prefix is None:
                os.environ.pop("S3_RELAY_PREFIX", None)
            else:
                os.environ["S3_RELAY_PREFIX"] = old_prefix

    def test_large_mp4_uses_sequential_multipart_upload_by_default(self):
        class FakeS3:
            def __init__(self, size):
                self.size = size
                self.upload = None

            def upload_file(self, filename, bucket, key, ExtraArgs, Config):
                self.upload = {
                    "filename": filename,
                    "bucket": bucket,
                    "key": key,
                    "content_type": ExtraArgs["ContentType"],
                    "concurrency": Config.max_request_concurrency,
                }

            def head_object(self, Bucket, Key):
                return {"ContentLength": self.size}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "large_final.mp4"
            video.write_bytes(b"0" * (8 * 1024 * 1024))
            fake = FakeS3(video.stat().st_size)
            env = {
                "S3_RELAY_PREFIX": "relay/test",
                "S3_RELAY_BUCKET": "test-bucket",
            }
            with mock.patch.dict(os.environ, env, clear=False), \
                 mock.patch.object(CLIENT, "_client", return_value=fake), \
                 mock.patch.object(CLIENT, "_read_manifest", return_value={}), \
                 mock.patch.object(CLIENT, "_write_manifest"):
                result = CLIENT.deliver_file(video, "large_final.mp4", self._checklist(root))
            self.assertEqual(fake.upload["concurrency"], 1)
            self.assertEqual(fake.upload["content_type"], "video/mp4")
            self.assertEqual(result["size_bytes"], video.stat().st_size)
            self.assertTrue(result["remote_size_verified"])

    def test_send_allocates_from_bucket_list_truth_when_manifest_lags(self):
        class FakeS3:
            def list_objects_v2(self, **kwargs):
                return {
                    "Contents": [
                        {"Key": "relay/test/c2sc/0094_existing.md"},
                        {"Key": "relay/test/c2sc/0091_older.md"},
                    ]
                }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = root / "message.md"
            payload.write_text("Public state reconciliation.", encoding="utf-8")
            written = {}

            def capture_put(s3, key, body, content_type):
                written["key"] = key

            env = {"S3_RELAY_PREFIX": "relay/test", "S3_RELAY_BUCKET": "test-bucket"}
            manifest = {"channels": {"c2sc": {"seq": 93}}}
            with mock.patch.dict(os.environ, env, clear=False), \
                 mock.patch.object(CLIENT, "_client", return_value=FakeS3()), \
                 mock.patch.object(CLIENT, "_read_manifest", return_value=manifest), \
                 mock.patch.object(CLIENT, "_write_manifest"), \
                 mock.patch.object(CLIENT, "_put", side_effect=capture_put):
                sequence = CLIENT.send("c2sc", payload, "reconcile.md", self._checklist(root))

            self.assertEqual(sequence, 95)
            self.assertEqual(written["key"], "relay/test/c2sc/0095_reconcile.md")

    def test_poll_reads_bucket_objects_beyond_stale_manifest_cursor(self):
        class FakeS3:
            def list_objects_v2(self, **kwargs):
                return {"Contents": [{"Key": "relay/test/sc2c/0094_new.md"}]}

            def get_object(self, Bucket, Key):
                return {"Body": BytesIO(b"new remote receipt")}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = {"S3_RELAY_PREFIX": "relay/test", "S3_RELAY_BUCKET": "test-bucket"}
            manifest = {"channels": {"sc2c": {"seq": 90}}}
            with mock.patch.dict(os.environ, env, clear=False), \
                 mock.patch.object(CLIENT, "_client", return_value=FakeS3()), \
                 mock.patch.object(CLIENT, "_read_manifest", return_value=manifest):
                pulled = CLIENT.poll("sc2c", 90, root / "inbox")

            self.assertEqual([path.name for path in pulled], ["0094_new.md"])
            self.assertEqual(pulled[0].read_bytes(), b"new remote receipt")


if __name__ == "__main__":
    unittest.main()
