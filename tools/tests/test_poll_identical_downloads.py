"""poll_giggle_submit_report: byte-identical clips from distinct URLs collapse to one take (E12 VU-003)."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import poll_giggle_submit_report as poll  # noqa: E402


class CollapseIdenticalDownloadsTests(unittest.TestCase):
    def test_identical_bytes_become_the_single_take_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / "U_01.mp4", Path(tmp) / "U_02.mp4"
            a.write_bytes(b"clip"); b.write_bytes(b"clip")
            single = Path(tmp) / "U.mp4"
            self.assertEqual(poll.collapse_identical_downloads([str(a), str(b)], single), [str(single)])
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["U.mp4"])

    def test_different_takes_keep_indexed_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / "U_01.mp4", Path(tmp) / "U_02.mp4"
            a.write_bytes(b"take-1"); b.write_bytes(b"take-2")
            files = [str(a), str(b)]
            self.assertEqual(poll.collapse_identical_downloads(files, Path(tmp) / "U.mp4"), files)
            self.assertFalse((Path(tmp) / "U.mp4").exists())


if __name__ == "__main__":
    unittest.main()
