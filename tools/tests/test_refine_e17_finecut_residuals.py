import json
import unittest
from pathlib import Path

from tools.refine_e17_finecut_residuals import ROOT, refine


class E17FinecutResidualRefinementTest(unittest.TestCase):
    def test_actual_plan_preserves_frames_and_removes_short_segments(self):
        plan = json.loads((ROOT / "configs/e17_remake_pacing_finecut_plan_v1_20260716.json").read_text(encoding="utf-8"))
        result = refine(plan)
        self.assertEqual(result["expected_frames"], 3966)
        self.assertEqual(sum(row["expected_frames"] for row in result["segments"]), 3966)
        self.assertEqual(result["pacing_summary"]["segments_under_0_8_seconds"], 0)
        self.assertEqual(result["pacing_summary"]["finecut_segment_count"], 49)


if __name__ == "__main__":
    unittest.main()
