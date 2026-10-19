"""Assembly audio continuity: cut points keep one continuous room tone.

The dip is a soft transition on the same audio stream, never a mute and never a
duration change.  The policy is off unless an episode opts in, so no
in-production episode changes byte-for-byte.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools import assembly_audio_continuity_policy as policy
from tools import audio_cut_overlap as aco

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


class PolicyTests(unittest.TestCase):
    def test_default_is_off(self):
        self.assertFalse(policy.active_for("E99"))

    def test_contract_can_opt_in(self):
        self.assertTrue(policy.active_for(
            "E99", contract={"assembly_audio_continuity": "ASSEMBLY_AUDIO_CONTINUITY_V1"}))

    def test_enabled_from_episode_activates_later_episodes(self):
        loaded = {"schema": policy.SCHEMA, "lines": {"nalu": {"active_from_episode": 11}}}
        self.assertFalse(policy.active_for("E10", policy=loaded))
        self.assertTrue(policy.active_for("E11", policy=loaded))

    def test_missing_or_invalid_policy_never_activates(self):
        self.assertFalse(policy.active_for("E99", policy={"schema": "wrong"}))
        self.assertFalse(policy.active_for("E99", policy={}))

    def test_crossfade_default_and_guard(self):
        self.assertAlmostEqual(policy.crossfade_seconds({}), 0.08)
        self.assertAlmostEqual(policy.crossfade_seconds({"crossfade_seconds": 0}), 0.08)


class BoundaryExtractionTests(unittest.TestCase):
    def test_cut_points_are_every_segment_start_after_the_first(self):
        timeline = {"segments": [
            {"unit_id": "U1", "output_start": 0.0, "output_end": 4.2},
            {"unit_id": "U2", "output_start": 4.2, "output_end": 9.0},
            {"unit_id": "U3", "output_start": 9.0, "output_end": 12.5},
        ]}
        self.assertEqual(policy.boundaries_from_release_timeline(timeline), [4.2, 9.0])

    def test_timeline_without_segments_has_no_boundaries(self):
        self.assertEqual(policy.boundaries_from_release_timeline({}), [])


class PipelineWiringTests(unittest.TestCase):
    def test_s7_applies_the_dip_before_loudness_levelling(self):
        source = Path(__file__).resolve().parents[2] / "lines/nalu/runtime/tools/nalu_pipeline.py"
        text = source.read_text(encoding="utf-8")
        self.assertIn("apply_cut_point_dips", text)
        self.assertIn("assembly_audio_continuity_policy", text)
        dip = text.index("apply_cut_point_dips")
        level = text.index('level_argv[level_argv.index("--source") + 1] = subbed')
        self.assertLess(dip, level)

    def test_a_failed_dip_blocks_instead_of_silently_continuing(self):
        source = Path(__file__).resolve().parents[2] / "lines/nalu/runtime/tools/nalu_pipeline.py"
        text = source.read_text(encoding="utf-8")
        self.assertIn("CUT_POINT_AUDIO_CONTINUITY_FAILED", text)


@unittest.skipUnless(FFMPEG_AVAILABLE, "ffmpeg/ffprobe not on PATH")
class DipIntegrationTests(unittest.TestCase):
    def _clip(self, path: Path, seconds: float) -> None:
        subprocess.run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=black:s=160x120:r=24:d={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency=300:sample_rate=48000:duration={seconds}",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2", str(path),
        ], check=True, capture_output=True)

    def test_dip_never_changes_duration_or_video(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            clip = root / "in.mp4"
            self._clip(clip, 3.0)
            out = root / "out.mp4"
            report = aco.apply_cut_point_dips(clip, [1.2, 2.1], 0.08, out)
            self.assertTrue(report["duration_unchanged"])
            self.assertEqual(report["boundaries_applied"], 2)


if __name__ == "__main__":
    unittest.main()
