import json
import unittest

from tools.build_e17_scene_timeline import ROOT, build


class E17SceneTimelineTest(unittest.TestCase):
    def test_actual_refined_plan_binds_every_shot(self):
        plan = json.loads((ROOT / "configs/e17_remake_pacing_finecut_plan_v2_20260716.json").read_text(encoding="utf-8"))
        result = build(plan)
        self.assertEqual(result["expected_frames"], 3966)
        self.assertEqual(len(result["shots"]), 49)
        self.assertTrue(all(row["scene_id"] for row in result["shots"]))
        self.assertEqual(result["shots"][-1]["scene_id"], "CARD-E17-NALU")


if __name__ == "__main__":
    unittest.main()
