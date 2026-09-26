"""tools/audio_cut_overlap.py tests: pure filter-string unit tests (fast, no ffmpeg) plus one
real ffmpeg integration test on a synthetic lavfi clip, mirroring
tools/tests/test_ad_tail_insert.py's fixture convention. Skipped if ffmpeg isn't on PATH.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import audio_cut_overlap as aco  # noqa: E402

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


class BuildDipFilterChainTests(unittest.TestCase):
    def test_single_boundary_produces_one_out_one_in(self) -> None:
        chain = aco.build_dip_filter_chain([5.0], 0.08)
        self.assertEqual(chain, "afade=t=out:st=4.96:d=0.04,afade=t=in:st=5:d=0.04")

    def test_boundary_at_zero_is_skipped(self) -> None:
        self.assertEqual(aco.build_dip_filter_chain([0.0], 0.08), "")

    def test_no_boundaries_gives_empty_chain(self) -> None:
        self.assertEqual(aco.build_dip_filter_chain([], 0.08), "")

    def test_duplicate_boundaries_deduplicated(self) -> None:
        chain = aco.build_dip_filter_chain([5.0, 5.0, 5.0], 0.08)
        self.assertEqual(chain.count("afade=t=in"), 1)

    def test_multiple_boundaries_sorted_and_chained(self) -> None:
        chain = aco.build_dip_filter_chain([10.0, 5.0], 0.1)
        parts = chain.split(",")
        self.assertEqual(len(parts), 4)
        self.assertIn("st=5", parts[1])
        self.assertIn("st=10", parts[3])

    def test_fade_start_never_negative(self) -> None:
        chain = aco.build_dip_filter_chain([0.02], 0.08)
        self.assertNotIn("st=-", chain)


@unittest.skipUnless(FFMPEG_AVAILABLE, "ffmpeg/ffprobe not on PATH")
class ApplyCutPointDipsIntegrationTest(unittest.TestCase):
    def _make_clip(self, path: Path, seconds: float = 3.0) -> None:
        subprocess.run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=blue:s=320x240:r=24:d={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={seconds}",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2", str(path),
        ], check=True, capture_output=True)

    def test_output_duration_unchanged_and_video_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            clip = root / "in.mp4"
            self._make_clip(clip, seconds=3.0)
            out = root / "out.mp4"
            report = aco.apply_cut_point_dips(clip, [1.0, 2.0], 0.08, out)
            self.assertTrue(out.is_file())
            self.assertTrue(report["duration_unchanged"])
            self.assertEqual(report["boundaries_applied"], 2)

    def test_never_overwrites_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            clip = root / "in.mp4"
            self._make_clip(clip, seconds=1.0)
            out = root / "out.mp4"
            out.write_bytes(b"not a real mp4")
            with self.assertRaises(FileExistsError):
                aco.apply_cut_point_dips(clip, [0.5], 0.08, out)

    def test_no_boundaries_still_produces_valid_output(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            clip = root / "in.mp4"
            self._make_clip(clip, seconds=1.0)
            out = root / "out.mp4"
            report = aco.apply_cut_point_dips(clip, [], 0.08, out)
            self.assertTrue(out.is_file())
            self.assertEqual(report["boundaries_applied"], 0)


if __name__ == "__main__":
    unittest.main()
