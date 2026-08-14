#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import io
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "tools/s3_episode_archive.py"
SPEC = importlib.util.spec_from_file_location("s3_episode_archive", PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Body(io.BytesIO):
    pass


class FakeS3:
    def __init__(self) -> None:
        self.data = b""
        self.metadata = {}

    def upload_file(self, path, _bucket, _key, ExtraArgs):
        self.data = Path(path).read_bytes()
        self.metadata = ExtraArgs["Metadata"]

    def head_object(self, **_kwargs):
        return {"ContentLength": len(self.data), "Metadata": self.metadata}

    def get_object(self, **_kwargs):
        return {"Body": Body(self.data)}


class S3EpisodeArchiveTests(unittest.TestCase):
    def test_upload_is_verified_by_head_and_full_stream_readback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "final.mp4"
            source.write_bytes(b"final-video-bytes")
            result = MODULE.upload_and_verify(
                source,
                project_id="project-1",
                episode="E01",
                version="v2",
                bucket="shared",
                key="published-finals/project-1/E01/v2/final.mp4",
                endpoint=None,
                client=FakeS3(),
            )
        self.assertEqual(result["status"], "VERIFIED")
        self.assertTrue(result["head_verified"])
        self.assertTrue(result["stream_readback_verified"])
        self.assertEqual(result["source_sha256"], result["remote_sha256"])

    def test_key_is_project_episode_and_version_scoped(self) -> None:
        key = MODULE.normalized_key("factory", "p1", "E09", "v3", "final.mp4")
        self.assertEqual(key, "factory/published-finals/p1/E09/v3/final.mp4")


if __name__ == "__main__":
    unittest.main()
