import unittest

from tools.build_video_unit_grouping_spec import build, partition_scene
from tools.compile_video_unit_plan import compile_grouping_spec


class BuildVideoUnitGroupingSpecTests(unittest.TestCase):
    def test_h3_speaker_change_is_a_paid_task_boundary_but_sd2_is_unchanged(self):
        shots = [
            {
                "shot_id": "E99-S01-01", "duration_seconds": 3,
                "prompt_spec": {
                    "dialogue": "陈迹：先走。",
                    "action": {"primary_action": "陈迹转身"},
                },
            },
            {
                "shot_id": "E99-S01-02", "duration_seconds": 3,
                "prompt_spec": {
                    "dialogue": "姚老头：等等。",
                    "action": {"primary_action": "姚老头抬手"},
                },
            },
        ]
        h3_groups = partition_scene(shots, model="MiniMax-H3")
        sd2_groups = partition_scene(shots, model="seedance-2.0-pro")
        self.assertEqual([[row["shot_id"] for row in group] for group in h3_groups], [
            ["E99-S01-01"], ["E99-S01-02"],
        ])
        self.assertEqual(len(sd2_groups), 1)

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
