import unittest

from tools.video_unit_anchor_count_gate import evaluate


def unit(count, reason, keys=None, continuity=None):
    value = {
        "unit_id": "E99-CW-U01",
        "planned_reference_image_count": count,
        "anchor_count_decision": {
            "planned_reference_image_count": count,
            "reason": reason,
            "criteria": {
                "continuous_motion_from_single_start": count == 1,
                "identity_or_space_reanchor": count > 1,
                "prop_ownership_transition": False,
                "non_interpolable_terminal_state": False,
            },
            "anchor_roles": ["performance_start"] + [f"reanchor_{i}" for i in range(2, count + 1)],
            "action_design_class": "continuous_performance" if count == 1 else "state_reanchor",
        },
        "reference_image_task_keys": keys or [f"A{i + 1}" for i in range(count)],
    }
    if continuity is not None:
        value["keyframe_interpolation_gate"] = continuity
    return value


class VideoUnitAnchorCountGateTest(unittest.TestCase):
    def test_single_anchor_with_action_specific_reason_passes(self):
        plan = {
            "units": [unit(1, "Identity and scene stay stable while one continuous motion script controls the full action.")],
            "planned_reference_image_count": 1,
        }
        self.assertEqual(evaluate(plan)["status"], "PASS")

    def test_fixed_one_default_fails(self):
        plan = {
            "units": [unit(1, "One image per unit is the fixed default for this workflow.")],
            "planned_reference_image_count": 1,
        }
        self.assertEqual(evaluate(plan)["status"], "FAIL")

    def test_multi_anchor_requires_every_adjacent_pair(self):
        plan = {
            "units": [unit(
                3,
                "Two ownership transitions need explicit intermediate and terminal anchors to prevent a prop jump.",
                continuity={"status": "PASS", "adjacent_pairs_checked": 1},
            )],
            "planned_reference_image_count": 3,
        }
        self.assertEqual(evaluate(plan)["status"], "FAIL")

    def test_multi_anchor_with_complete_continuity_passes(self):
        plan = {
            "units": [unit(
                2,
                "A spirit separates from a seated body, so the unchanged body and completed separation need a terminal anchor.",
                continuity={"status": "PASS", "adjacent_pairs_checked": 1},
            )],
            "planned_reference_image_count": 2,
        }
        self.assertEqual(evaluate(plan)["status"], "PASS")

    def test_omni_multi_reference_with_semantic_coverage_passes(self):
        value = unit(
            2,
            "A later visible identity is absent from frame one and requires an admitted ordinary reference.",
        )
        value["reference_transport_strategy"] = "OMNI_MULTI_REFERENCE"
        value["semantic_reference_coverage_gate"] = {"status": "PASS", "references_checked": 2}
        self.assertEqual(evaluate({"units": [value], "planned_reference_image_count": 2})["status"], "PASS")

    def test_standard_multi_reference_with_semantic_coverage_passes(self):
        value = unit(
            2,
            "A later spatial plane is absent from frame one and requires a separately bound semantic reference.",
        )
        value["reference_transport_strategy"] = "STANDARD_MULTI_REFERENCE"
        value["semantic_reference_coverage_gate"] = {"status": "PASS", "references_checked": 2}
        self.assertEqual(evaluate({"units": [value], "planned_reference_image_count": 2})["status"], "PASS")

    def test_mechanical_uniform_batch_without_audit_fails(self):
        plan = {
            "units": [
                {**unit(1, f"Unit {index} has one stable identity and a continuous motion chain from its starting frame."), "unit_id": f"E99-CW-U{index:02d}"}
                for index in range(1, 5)
            ],
            "planned_reference_image_count": 4,
        }
        report = evaluate(plan)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("UNIFORM_COUNT_INDEPENDENCE_AUDIT_MISSING", {row["code"] for row in report["failures"]})

    def test_uniform_result_with_independent_distinct_assessments_passes(self):
        units = [
            {**unit(1, f"Unit {index} keeps one identity and scene while a continuous performance drives the complete beat."), "unit_id": f"E99-CW-U{index:02d}"}
            for index in range(1, 5)
        ]
        units[0]["anchor_count_decision"]["action_design_class"] = "dialogue_two_shot"
        units[1]["anchor_count_decision"]["action_design_class"] = "single_subject_investigation"
        units[2]["anchor_count_decision"]["action_design_class"] = "environmental_establishing"
        units[3]["anchor_count_decision"]["action_design_class"] = "continuous_combat"
        plan = {
            "units": units,
            "planned_reference_image_count": 4,
            "uniform_count_independence_audit": {
                "status": "PASS",
                "evaluated_individually": True,
                "distinct_action_design_classes": 3,
            },
        }
        self.assertEqual(evaluate(plan)["status"], "PASS")

    def test_multi_anchor_without_declared_need_fails(self):
        value = unit(
            2,
            "The unit claims two anchors but contains one stable identity and one continuous movement in one room.",
            continuity={"status": "PASS", "adjacent_pairs_checked": 1},
        )
        value["anchor_count_decision"]["criteria"] = {
            "continuous_motion_from_single_start": True,
            "identity_or_space_reanchor": False,
            "prop_ownership_transition": False,
            "non_interpolable_terminal_state": False,
        }
        self.assertEqual(evaluate({"units": [value], "planned_reference_image_count": 2})["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
