import unittest

from tools.video_unit_grouping_gate import evaluate, validate_task_bindings


class VideoUnitGroupingGateTests(unittest.TestCase):
    def plan(self):
        return {
            "schema": "qingshan.video_unit_grouping_plan.v1",
            "editorial_shot_count": 12,
            "video_unit_count": 2,
            "average_video_unit_duration_seconds": 6,
            "preferred_duration_seconds": {"minimum": 5, "maximum": 8},
            "derivation": {"unit_count_selected_in_advance": False, "formula_division_used": False},
            "units": [
                {"unit_id": "U01", "duration_seconds": 6, "editorial_shot_ids": [f"S{i}" for i in range(6)]},
                {"unit_id": "U02", "duration_seconds": 6, "editorial_shot_ids": [f"S{i}" for i in range(6, 12)]},
            ],
        }

    def test_accepts_semantically_grouped_units(self):
        self.assertEqual(evaluate(self.plan())["status"], "PASS")

    def test_accepts_transition_contract_v2_schema(self):
        plan = self.plan()
        plan["schema"] = "qingshan.video_unit_grouping_plan.v2_transition_contract"
        self.assertEqual(evaluate(plan)["status"], "PASS")

    def test_rejects_one_video_per_editorial_shot(self):
        plan = self.plan()
        plan["video_unit_count"] = 12
        plan["units"] = [
            {"unit_id": f"U{i}", "duration_seconds": 1, "duration_exception_reason": "x", "editorial_shot_ids": [f"S{i}"]}
            for i in range(12)
        ]
        self.assertIn("editorial_shot_to_video_unit_one_to_one_forbidden", evaluate(plan)["failures"])

    def test_checks_paid_task_binding(self):
        failures = validate_task_bindings(self.plan(), [{
            "unit_id": "U01", "duration_seconds": 7, "editorial_shot_ids": ["S0"]
        }])
        self.assertEqual(len(failures), 2)
