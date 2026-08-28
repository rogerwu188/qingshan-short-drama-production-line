import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.compile_video_unit_plan import compile_grouping_spec, validate_compiled_plan


def locked_camera(label="人物中景"):
    return {
        "shot_scale": "MEDIUM", "lens_intent": "50mm自然透视",
        "camera_height": "EYE_LEVEL", "camera_side": "AXIS_A",
        "axis_relation": "保持既定人物视线轴，不越轴",
        "motion_family": "LOCKED", "motion_direction": "NONE",
        "start_framing": label, "end_framing": label,
        "motivation": "让人物表演在稳定构图内自行发生",
    }


class CompileVideoUnitPlanTest(unittest.TestCase):
    def setUp(self):
        self.production = {
            "episode": "E99",
            "runtime_seconds": 20,
            "source": {"script_sha256": "abc"},
            "shots": [
                {"shot_id": "SH01", "scene_id": "S01", "duration_seconds": 5},
                {"shot_id": "SH02", "scene_id": "S01", "duration_seconds": 5},
                {"shot_id": "SH03", "scene_id": "S02", "duration_seconds": 10},
            ],
        }
        self.spec = {
            "episode": "E99",
            "source_script_sha256": "abc",
            "preferred_duration_seconds": {"minimum": 5, "maximum": 10},
            "groups": [
                {
                    "unit_id": "U01",
                    "editorial_shot_ids": ["SH01", "SH02"],
                    "action_unit": True,
                    "narrative_beat": "One continuous action in scene one.",
                    "camera_plan": locked_camera("双人中景"),
                },
                {
                    "unit_id": "U02",
                    "editorial_shot_ids": ["SH03"],
                    "action_unit": False,
                    "narrative_beat": "Scene two reaction.",
                    "camera_plan": locked_camera("人物反应中景"),
                },
            ],
        }

    def test_derives_count_and_durations_from_semantic_groups(self):
        plan = compile_grouping_spec(self.production, self.spec)

        self.assertEqual(plan["video_unit_count"], 2)
        self.assertEqual([unit["duration_seconds"] for unit in plan["units"]], [10, 10])
        self.assertEqual(plan["derivation"]["unit_count_source"], "LEN_OF_VALIDATED_SEMANTIC_GROUPS")
        validate_compiled_plan(self.production, plan)

    def test_rejects_cross_scene_group(self):
        self.spec["groups"] = [{
            "unit_id": "U01",
            "editorial_shot_ids": ["SH01", "SH02", "SH03"],
            "narrative_beat": "Invalid cross-scene group.",
            "camera_plan": locked_camera(),
        }]

        with self.assertRaisesRegex(ValueError, "crosses scene"):
            compile_grouping_spec(self.production, self.spec)

    def test_rejects_reordered_or_incomplete_shots(self):
        self.spec["groups"][0]["editorial_shot_ids"] = ["SH02", "SH01"]

        with self.assertRaisesRegex(ValueError, "source order"):
            compile_grouping_spec(self.production, self.spec)

    def test_rejects_preselected_count_or_average_duration_formula(self):
        self.spec["target_video_unit_count"] = 2
        self.spec["average_unit_duration_seconds"] = 10

        with self.assertRaisesRegex(ValueError, "formula fields are forbidden"):
            compile_grouping_spec(self.production, self.spec)

    def test_rejects_unexplained_short_preferred_exception(self):
        self.production["runtime_seconds"] = 14
        self.production["shots"][2]["duration_seconds"] = 4

        with self.assertRaisesRegex(ValueError, "exception reason"):
            compile_grouping_spec(self.production, self.spec)

    def test_rejects_declared_duration_not_equal_to_source_sum(self):
        plan = compile_grouping_spec(self.production, self.spec)
        broken = copy.deepcopy(plan)
        broken["units"][0]["duration_seconds"] = 11

        with self.assertRaisesRegex(ValueError, "source-shot sum"):
            validate_compiled_plan(self.production, broken)

    def test_rejects_missing_camera_plan(self):
        del self.spec["groups"][0]["camera_plan"]

        with self.assertRaisesRegex(ValueError, "camera_plan"):
            compile_grouping_spec(self.production, self.spec)

    def test_rejects_adjacent_repeated_dynamic_camera_direction(self):
        repeated = {
            "shot_scale": "MEDIUM_WIDE", "lens_intent": "35mm空间跟随",
            "camera_height": "EYE_LEVEL", "camera_side": "AXIS_A",
            "axis_relation": "保持既定人物视线轴，不越轴",
            "motion_family": "TRACK", "motion_direction": "LEFT_TO_RIGHT",
            "start_framing": "人物进入通道", "end_framing": "人物抵达门边",
            "motivation": "保持人物真实行进及其空间终点连续可读",
        }
        self.spec["groups"][0]["camera_plan"] = copy.deepcopy(repeated)
        self.spec["groups"][1]["camera_plan"] = copy.deepcopy(repeated)

        with self.assertRaisesRegex(ValueError, "repeat camera motion"):
            compile_grouping_spec(self.production, self.spec)

    def test_preserves_fractional_editorial_durations(self):
        self.production["shots"][0]["duration_seconds"] = 4.5
        self.production["shots"][1]["duration_seconds"] = 5.5
        plan = compile_grouping_spec(self.production, self.spec)
        self.assertEqual(plan["units"][0]["duration_seconds"], 10.0)

    def test_rejects_large_one_to_one_editorial_mapping(self):
        shots = [
            {"shot_id": f"S{i:02d}", "scene_id": "SC", "duration_seconds": 3}
            for i in range(12)
        ]
        production = {"episode": "E99", "runtime_seconds": 36, "source": {"script_sha256": "abc"}, "shots": shots}
        spec = {
            "episode": "E99", "source_script_sha256": "abc",
            "groups": [
                {"unit_id": f"U{i:02d}", "editorial_shot_ids": [shot["shot_id"]],
                 "narrative_beat": "fragment", "duration_exception_reason": "fragment",
                 "camera_plan": locked_camera(f"fragment-{i}")}
                for i, shot in enumerate(shots)
            ],
        }
        with self.assertRaisesRegex(ValueError, "one-to-one"):
            compile_grouping_spec(production, spec)


if __name__ == "__main__":
    unittest.main()
