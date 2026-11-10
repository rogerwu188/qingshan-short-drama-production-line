"""A levelled release that FAILed is reused on S7 re-entry so its sha-bound loudness order still applies
(field device …1324 E03, 2026-11-09)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "lines" / "nalu" / "runtime" / "tools", ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import nalu_pipeline as npl  # noqa: E402


class ReuseLevelledTest(unittest.TestCase):
    def run_with(self, status: str):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            src, out, rep = d / "src.mp4", d / "levelled.mp4", d / "level.json"
            src.write_bytes(b"src"); out.write_bytes(b"out")
            rep.write_text(json.dumps({"status": status, "source_video_stream_sha256": "v",
                                       "output_video_stream_sha256": "v"}), encoding="utf-8")
            p = SimpleNamespace(leveled_audio_report=rep, final_levelled=out)
            fake = SimpleNamespace(stream_hash=lambda *_a: "v")
            with mock.patch.dict(sys.modules, {"level_native_release_audio": fake}):
                return npl._reusable_release_level(p, src)

    def test_fail_report_is_reused(self):
        reused = self.run_with("FAIL")
        self.assertIsNotNone(reused)
        self.assertEqual(reused["status"], "FAIL")

    def test_pass_still_reused_and_unknown_not(self):
        self.assertEqual(self.run_with("PASS")["status"], "PASS")
        self.assertIsNone(self.run_with("ERROR"))


if __name__ == "__main__":
    unittest.main()
