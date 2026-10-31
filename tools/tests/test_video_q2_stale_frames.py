"""Q2 frame extraction parks the frames of an older take (E12 2026-10-31)."""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lines/nalu/runtime/tools"))

import video_q2_builder as vqb  # noqa: E402


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "needs ffmpeg")
class StaleFrameTests(unittest.TestCase):
    def test_new_take_parks_frames_of_the_old_take(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            clip = tmp / "U.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=24:duration=2",
                            "-pix_fmt", "yuv420p", str(clip)], check=True)
            frames = tmp / "frames"
            old = frames / "U_f01_0.287s.png"
            frames.mkdir()
            old.write_bytes(b"old take")
            out = vqb.extract_frames("U", clip, frames, 3)
            self.assertEqual(out["status"], "OK")
            self.assertEqual(out["stale_frames_parked"], ["U_f01_0.287s.png"])
            self.assertEqual(sorted(p.name for p in frames.glob("*.png")),
                             sorted(Path(row["path"]).name for row in out["frames"]))
            self.assertTrue((frames / "_superseded" / old.name).is_file())


if __name__ == "__main__":
    unittest.main()
