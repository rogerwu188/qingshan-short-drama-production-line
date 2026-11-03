"""Q2 frames: a new take never carries the frames of an older take (E12 2026-10-31)."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lines/nalu/runtime/tools"))

import video_q2_builder as vqb  # noqa: E402


class StaleFrameTests(unittest.TestCase):
    def test_frames_outside_the_measurement_are_parked_not_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = Path(tmp)
            for name in ("U_f01_0.333s.png", "U_f06_3.158s.png", "V_f01_0.100s.png"):
                (frames / name).write_bytes(b"x")
            parked = vqb.park_stale_frames("U", frames, [{"path": str(frames / "U_f01_0.333s.png")}])
            self.assertEqual(parked, ["U_f06_3.158s.png"])
            self.assertEqual(sorted(p.name for p in frames.glob("*.png")), ["U_f01_0.333s.png", "V_f01_0.100s.png"])
            self.assertTrue((frames / "_superseded" / "U_f06_3.158s.png").is_file())

    def test_prepare_merges_earlier_frames_only_from_the_same_take(self):
        source = (ROOT / "lines/nalu/runtime/tools/video_q2_builder.py").read_text(encoding="utf-8")
        merge = source[source.index("elif extraction.get(\"frames\"):"):source.index("ocr_rows = [run_ocr(")]
        self.assertIn("same_take", merge)
        self.assertIn("park_stale_frames(", merge)


if __name__ == "__main__":
    unittest.main()
