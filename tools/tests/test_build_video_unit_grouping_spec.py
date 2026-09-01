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
        self.assertLess(len(spec["groups"]), 12)
        self.assertTrue(all(len(unit["editorial_shot_ids"]) > 1 for unit in spec["groups"]))
        self.assertEqual(
            len(spec["transition_authoring_required"]),
            len(spec["groups"]) - 1,
        )
        with self.assertRaisesRegex(ValueError, "transition_contract is required"):
            compile_grouping_spec(production, spec)

    def test_never_packs_more_than_three_beats(self):
        manifest = {"episode": "E99", "shots": []}
        for index in range(5):
            manifest["shots"].append({
                "shot_id": f"E99-S01-{index:02d}", "scene_id": "S01",
                "duration_seconds": 2,
                "prompt_spec": {
                    "action": {
                        "primary_action": f"combat beat {index}",
                        "action_kind": "COMBAT" if index < 3 else "PHYSICAL_ACTION",
                    },
                },
            })
        _production, spec = build(manifest, "abc")
        self.assertTrue(all(len(row["editorial_shot_ids"]) <= 3 for row in spec["groups"]))
