import json
import unittest

from tools.tune_e17_scene_boundary_brightness import ROOT, SHOT_EQ_BRIGHTNESS, tune


class E17SceneBoundaryBrightnessTuneTest(unittest.TestCase):
    def test_tune_is_shot_local_and_frame_exact(self):
        plan = json.loads((ROOT / "configs/e17_remake_pacing_finecut_plan_v2_20260716.json").read_text(encoding="utf-8"))
        result = tune(plan)
        self.assertEqual(sum(row["expected_frames"] for row in result["segments"]), 3966)
        tuned = [index for index, row in enumerate(result["segments"], start=1) if "scene_boundary_tune" in row]
        self.assertEqual(tuned, sorted(SHOT_EQ_BRIGHTNESS))


if __name__ == "__main__":
    unittest.main()
