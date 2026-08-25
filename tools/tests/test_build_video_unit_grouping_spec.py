import unittest

from tools.build_video_unit_grouping_spec import build
from tools.compile_video_unit_plan import compile_grouping_spec


class BuildVideoUnitGroupingSpecTests(unittest.TestCase):
    def test_groups_contiguous_shots_without_crossing_scene(self):
        manifest = {"episode": "E99", "shots": []}
        for scene in ("S01", "S02"):
            for index in range(6):
                manifest["shots"].append({
                    "shot_id": f"E99-{scene}-{index:02d}", "duration_seconds": 1.5,
                    "prompt_spec": {"action": {"primary_action": f"beat {index}"}},
                })
        production, spec = build(manifest, "abc")
        plan = compile_grouping_spec(production, spec)
        self.assertEqual(plan["editorial_shot_count"], 12)
        self.assertLess(plan["video_unit_count"], 12)
        self.assertTrue(all(len(unit["editorial_shot_ids"]) > 1 for unit in plan["units"]))
        self.assertEqual({unit["scene_id"] for unit in plan["units"]}, {"S01", "S02"})
