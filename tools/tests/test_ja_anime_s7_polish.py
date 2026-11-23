"""Deep review 1485 E09 (JA anime, 2026-11-23): the opening title sat across the speaker's eyes (InsightFace finds no
anime face, so the upper third was "clear"); subtitle rows split inside words (see test_subtitle_wrap_kinsoku)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lines/nalu/runtime/tools"))

import nalu_opening_title as title  # noqa: E402


class AnimeTitleBandTests(unittest.TestCase):
    def test_anime_without_measured_face_goes_to_the_lower_band(self):
        bands = title.title_bands("anime", [])
        self.assertEqual(bands, title.ANIME_NO_FACE_BANDS)
        placement = title.choose_title_band(1280, 160, [], bands)
        self.assertEqual(placement["band"], "LOWER")
        self.assertLessEqual(placement["top"] + 160, title.SUBTITLE_BAND_TOP * 1280)   # above the subtitles

    def test_live_action_and_measured_faces_keep_the_old_order(self):
        self.assertIs(title.title_bands("live_action", []), title.TITLE_BANDS)
        self.assertIs(title.title_bands(None, []), title.TITLE_BANDS)
        face = [[200.0, 300.0, 520.0, 640.0]]
        self.assertIs(title.title_bands("anime", face), title.TITLE_BANDS)
        self.assertEqual(title.choose_title_band(1280, 160, [])["band"], "UPPER_THIRD")

    def test_pipeline_passes_the_render_style(self):
        src = (ROOT / "lines/nalu/runtime/tools/nalu_pipeline.py").read_text(encoding="utf-8")
        self.assertIn("render_style=ctx_render_style(ctx))", src)


if __name__ == "__main__":
    unittest.main()
