import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.compile_video_unit_plan import compile_grouping_spec, validate_compiled_plan


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
            "groups": [
                {
                    "unit_id": "U01",
                    "editorial_shot_ids": ["SH01", "SH02"],
                    "action_unit": True,
                    "narrative_beat": "One continuous action in scene one.",
                },
                {
                    "unit_id": "U02",
                    "editorial_shot_ids": ["SH03"],
                    "action_unit": False,
                    "narrative_beat": "Scene two reaction.",
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
        self.production["runtime_seconds"] = 17
        self.production["shots"][2]["duration_seconds"] = 7

        with self.assertRaisesRegex(ValueError, "exception reason"):
            compile_grouping_spec(self.production, self.spec)

    def test_rejects_declared_duration_not_equal_to_source_sum(self):
        plan = compile_grouping_spec(self.production, self.spec)
        broken = copy.deepcopy(plan)
        broken["units"][0]["duration_seconds"] = 11

        with self.assertRaisesRegex(ValueError, "source-shot sum"):
            validate_compiled_plan(self.production, broken)


if __name__ == "__main__":
    unittest.main()
