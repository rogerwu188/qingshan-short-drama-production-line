import unittest

from tools.build_video_unit_grouping_spec import build, partition_scene, _partition_scene, _group_camera_direction
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

    def test_group_camera_direction_reads_only_explicit_authored_plans(self):
        explicit = [{"prompt_spec": {"camera_plan": {"motion_direction": "PUSH_IN"}}}]
        locked = [{"prompt_spec": {"camera_plan": {"motion_direction": "NONE"}}}]
        semantic = [{"prompt_spec": {"action": {"primary_action": "beat"}}}]
        self.assertEqual(_group_camera_direction(explicit), "PUSH_IN")
        self.assertIsNone(_group_camera_direction(locked))
        self.assertIsNone(_group_camera_direction(semantic))

    def test_camera_rhythm_is_never_a_reason_a_scene_fails_to_partition(self):
        # Four same-direction shots force at least two groups (MAX_BEATS_PER_UNIT
        # caps a single group at three), and every possible split still repeats
        # PUSH_IN adjacently -- there is no camera-safe partition at all.
        # Enforcing the constraint must raise internally, and the public
        # partition_scene() must fall back rather than propagate that failure.
        shots = [
            {"shot_id": f"E99-S03-{i:02d}", "scene_id": "S03", "duration_seconds": 3,
             "prompt_spec": {"camera_plan": {"motion_direction": "PUSH_IN"}}}
            for i in range(4)
        ]
        with self.assertRaises(ValueError):
            _partition_scene(shots, model=None, recent_directions=[], enforce_camera=True)
        groups = partition_scene(shots, recent_directions=[])
        self.assertEqual(sum(len(g) for g in groups), 4)

    def test_build_threads_camera_rhythm_across_a_scene_boundary(self):
        # Two scenes, each producing one PUSH_IN unit when considered alone --
        # this reproduces the real E08 failure shape: no violation is visible
        # within either scene individually, only in the cross-scene sequence.
        manifest = {"episode": "E99", "model": None, "shots": [
            {"shot_id": "E99-S01-01", "scene_id": "S01", "duration_seconds": 6,
             "prompt_spec": {"camera_plan": {"motion_family": "DOLLY", "motion_direction": "PUSH_IN"}}},
            {"shot_id": "E99-S02-01", "scene_id": "S02", "duration_seconds": 6,
             "prompt_spec": {"camera_plan": {"motion_family": "DOLLY", "motion_direction": "PUSH_IN"}}},
        ]}
        _production, spec = build(manifest, "abc")
        directions = [row["camera_plan"].get("motion_direction") for row in spec["groups"]]
        # Both units are forced (each scene has exactly one shot: the
        # whole-scene exemption applies to both), so the adjacent PUSH_IN
        # repeat cannot be avoided by regrouping -- the point of this test is
        # that build() ran to completion instead of raising, proving
        # recent_directions was threaded into the second scene's call at all.
        self.assertEqual(directions, ["PUSH_IN", "PUSH_IN"])

    def test_camera_rhythm_prefers_a_pricier_valid_partition_over_a_cheaper_violation(self):
        # Cheapest duration-only partition is [E,F],[G,H] -> PUSH_IN, PUSH_IN
        # (adjacent repeat). A valid, camera-safe alternative exists
        # ([E],[F,G,H] -> PUSH_IN, CLOCKWISE) at a higher duration cost; the
        # camera-aware DP must pick it over the cheaper violating one.
        shots = [
            {"shot_id": "E99-S02-E", "duration_seconds": 3, "prompt_spec": {"camera_plan": {"motion_direction": "PUSH_IN"}}},
            {"shot_id": "E99-S02-F", "duration_seconds": 3, "prompt_spec": {"camera_plan": {"motion_direction": "CLOCKWISE"}}},
            {"shot_id": "E99-S02-G", "duration_seconds": 3, "prompt_spec": {"camera_plan": {"motion_direction": "PUSH_IN"}}},
            {"shot_id": "E99-S02-H", "duration_seconds": 2, "prompt_spec": {"camera_plan": {"motion_direction": "CLOCKWISE"}}},
        ]
        plain = _partition_scene(shots, model=None, recent_directions=[], enforce_camera=False)
        self.assertEqual([_group_camera_direction(g) for g in plain], ["PUSH_IN", "PUSH_IN"])
        aware = partition_scene(shots, recent_directions=[])
        self.assertEqual([_group_camera_direction(g) for g in aware], ["PUSH_IN", "CLOCKWISE"])
        self.assertEqual([s["shot_id"] for s in aware[0]], ["E99-S02-E"])
        self.assertEqual([s["shot_id"] for s in aware[1]], ["E99-S02-F", "E99-S02-G", "E99-S02-H"])
