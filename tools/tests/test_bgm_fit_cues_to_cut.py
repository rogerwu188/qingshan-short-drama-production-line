"""The episode bed's entry is delayed to fit the selective-BGM policy on the release cut (field device …1324 E03)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "lines" / "nalu" / "runtime" / "tools", ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import nalu_selective_bgm as bgm  # noqa: E402


class FitCuesToCutTest(unittest.TestCase):
    def test_bed_entry_delayed_to_meet_policy(self):
        content = 236.0
        windows = {"BED": (5.2, 236.0)}  # 97.8 % coverage, 5.2 s ambience
        delays = bgm.fit_cues_to_cut(windows, content)
        t0, t1 = windows["BED"]
        covered = t1 - t0
        self.assertLessEqual(covered / content, bgm.MAX_COVERAGE_RATIO)
        self.assertGreaterEqual(content - covered, bgm.MIN_AMBIENCE_ONLY_SECONDS)
        self.assertGreater(delays["BED"], 0)

    def test_compliant_plan_unchanged(self):
        windows = {"A": (20.0, 80.0)}
        self.assertEqual(bgm.fit_cues_to_cut(windows, 110.0), {})
        self.assertEqual(windows["A"], (20.0, 80.0))

    def test_never_below_min_cue(self):
        windows = {"A": (0.0, 9.0)}
        bgm.fit_cues_to_cut(windows, 10.0)
        self.assertGreaterEqual(windows["A"][1] - windows["A"][0], bgm.MIN_CUE_SECONDS)


if __name__ == "__main__":
    unittest.main()
