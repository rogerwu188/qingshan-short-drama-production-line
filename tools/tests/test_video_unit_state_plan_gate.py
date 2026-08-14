import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.video_unit_state_plan_gate import validate_plan


class VideoUnitStatePlanGateTest(unittest.TestCase):
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
        self.plan = {
            "episode": "E99",
            "source_script_sha256": "abc",
            "editorial_shot_count": 3,
            "video_unit_count": 2,
            "runtime_seconds": 20,
            "duration_policy_seconds": {"minimum": 8, "maximum": 15},
            "state_pool_count": 3,
            "units": [
                {
                    "unit_id": "U01",
                    "scene_id": "S01",
                    "duration_seconds": 10,
                    "action_unit": True,
                    "editorial_shot_ids": ["SH01", "SH02"],
                    "state_task_keys": ["A"],
                    "planned_reference_image_count": 1,
                    "anchor_count_decision": {
                        "planned_reference_image_count": 1,
                        "reason": "One stable start frame can drive this continuous combat action without a state jump.",
                        "criteria": {
                            "continuous_motion_from_single_start": True,
                            "identity_or_space_reanchor": False,
                            "prop_ownership_transition": False,
                            "non_interpolable_terminal_state": False,
                        },
                        "anchor_roles": ["performance_start"],
                        "action_design_class": "continuous_combat",
                    },
                },
                {
                    "unit_id": "U02",
                    "scene_id": "S02",
                    "duration_seconds": 10,
                    "action_unit": False,
                    "editorial_shot_ids": ["SH03"],
                    "state_task_keys": ["B", "C"],
                    "planned_reference_image_count": 2,
                    "anchor_count_decision": {
                        "planned_reference_image_count": 2,
                        "reason": "The identity changes screen position, so a second spatial re-anchor prevents a discontinuity.",
                        "criteria": {
                            "continuous_motion_from_single_start": False,
                            "identity_or_space_reanchor": True,
                            "prop_ownership_transition": False,
                            "non_interpolable_terminal_state": False,
                        },
                        "anchor_roles": ["performance_start", "spatial_reanchor"],
                        "action_design_class": "state_reanchor",
                    },
                    "keyframe_interpolation_gate": {"status": "PASS", "adjacent_pairs_checked": 1},
                },
            ],
        }
        self.images = [{
            "episode": "E99",
            "source_script_sha256": "abc",
            "tasks": [{"task_key": value} for value in "ABC"],
        }]

    def test_distinguishes_editorial_shots_from_generation_units(self):
        report = validate_plan(self.production, self.plan, self.images)

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["distinction"]["editorial_shots"], 3)
        self.assertEqual(report["distinction"]["video_generation_units"], 2)

    def test_rejects_shot_count_used_as_unit_count(self):
        self.plan["video_unit_count"] = 3

        report = validate_plan(self.production, self.plan, self.images)

        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any(row["check"] == "video_unit_count" for row in report["failures"]))

    def test_rejects_duplicate_state_assignment(self):
        self.plan["units"][1]["state_task_keys"] = ["A", "C"]

        report = validate_plan(self.production, self.plan, self.images)

        self.assertEqual(report["status"], "FAIL")
        failure = next(row for row in report["failures"] if row["check"] == "state_task_exact_coverage")
        self.assertEqual(failure["duplicates"], ["A"])

    def test_action_unit_can_use_one_anchor_when_action_design_justifies_it(self):
        report = validate_plan(self.production, self.plan, self.images)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["units"][0]["planned_reference_image_count"], 1)

    def test_rejects_unit_seconds_that_do_not_equal_editorial_shot_sum(self):
        self.plan["units"][0]["duration_seconds"] = 11
        self.plan["units"][1]["duration_seconds"] = 9

        report = validate_plan(self.production, self.plan, self.images)

        self.assertEqual(report["status"], "FAIL")
        mismatches = [row for row in report["failures"] if row["check"] == "unit_duration_exact_script_sum"]
        self.assertEqual(len(mismatches), 2)

    def test_allows_documented_short_atomic_beat_without_padding(self):
        self.production["runtime_seconds"] = 17
        self.production["shots"][2]["duration_seconds"] = 7
        self.plan["runtime_seconds"] = 17
        self.plan["duration_policy_seconds"] = {"minimum": 4, "maximum": 15}
        self.plan["preferred_duration_seconds"] = {"minimum": 8, "maximum": 15}
        self.plan["units"][1]["duration_seconds"] = 7
        self.plan["units"][1]["duration_exception_reason"] = "Atomic reaction beat; script duration is authoritative."

        report = validate_plan(self.production, self.plan, self.images)

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(len(report["runtime"]["documented_preferred_range_exceptions"]), 1)


if __name__ == "__main__":
    unittest.main()
