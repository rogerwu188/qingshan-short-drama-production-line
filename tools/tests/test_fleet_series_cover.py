"""Dashboard series cover (line owner 2026-11-13, option A): a still from the latest final cut, uploaded only
when that final cut changes."""
from __future__ import annotations

import base64
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "nalu-claude-code" / "scripts"))

import fleet_sync  # noqa: E402

FFMPEG = shutil.which("ffmpeg")


@unittest.skipUnless(FFMPEG and shutil.which("ffprobe"), "ffmpeg/ffprobe not installed")
class SeriesCoverTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.engine, self.runtime = root / "engine", root / "runtime"
        self.cut = self.runtime / "runtime" / "deliverables" / "E03" / "E03_final_9x16.mp4"
        self.cut.parent.mkdir(parents=True)
        self.engine.mkdir()
        subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=720x1280:d=4:r=24",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(self.cut)], check=True)
        self.cp = SimpleNamespace(roots=lambda: (self.engine, self.runtime))
        self.posts = []

    def tearDown(self):
        self._tmp.cleanup()

    def _req(self, method, path, body=None, token=""):
        self.posts.append((method, path, body))
        return 200, {"ok": True}

    def test_cover_is_a_small_jpeg_from_the_final_cut(self):
        data, meta = fleet_sync.series_cover(self.engine, self.runtime)
        self.assertTrue(data.startswith(b"\xff\xd8"))
        self.assertLess(len(data), fleet_sync.COVER_MAX_BYTES)
        self.assertEqual(meta["episode"], "E03")

    def test_uploaded_once_until_the_final_cut_changes(self):
        with mock.patch.object(fleet_sync, "_req", side_effect=self._req):
            self.assertEqual(fleet_sync.cover_tick(self.cp, "tok", now=10_000), "UPLOADED:200")
            self.assertIsNone(fleet_sync.cover_tick(self.cp, "tok", now=10_100), "rate limited")
            self.assertEqual(fleet_sync.cover_tick(self.cp, "tok", now=20_000), "UNCHANGED")
        self.assertEqual(len(self.posts), 1)
        method, path, body = self.posts[0]
        self.assertEqual((method, path), ("POST", "/v1/cover"))
        self.assertTrue(base64.b64decode(body["image_b64"]).startswith(b"\xff\xd8"))

    def test_no_final_cut_no_upload(self):
        self.cut.unlink()
        with mock.patch.object(fleet_sync, "_req", side_effect=self._req):
            self.assertEqual(fleet_sync.cover_tick(self.cp, "tok", now=10_000), "NO_FINAL_CUT")
        self.assertEqual(self.posts, [])


if __name__ == "__main__":
    unittest.main()
