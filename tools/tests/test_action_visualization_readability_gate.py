import unittest

from tools.action_visualization_readability_gate import evaluate


class ActionVisualizationReadabilityGateTest(unittest.TestCase):
    def test_complete_reasoning_passes_without_requiring_specific_effect(self):
        plan = {"episode": "E00", "units": [{
            "unit_id": "E00-U01",
            "performance_spec": {"motion_beats": [{
                "intent": "stop a blade",
                "invisible_element": "resistance",
                "externalized_visible_phenomenon": "ice grows from the contacted floor and changes the attacker's footing",
                "ability_logic": "the character's power propagates through contacted moisture",
                "force_feedback": "the attacker's wrist and torso are pulled off line",
                "expression": "confidence to surprise",
                "viewer_read": "the ice caused the stab to miss",
            }]},
        }]}
        self.assertEqual(evaluate(plan)["status"], "PASS")

    def test_physical_result_without_visible_cause_fails(self):
        plan = {"episode": "E00", "units": [{
            "unit_id": "E00-U01",
            "performance_spec": {"motion_beats": [{
                "intent": "stop a blade",
                "invisible_element": "resistance",
                "externalized_visible_phenomenon": "",
                "ability_logic": "",
                "force_feedback": "the blade displacement is zero",
                "expression": "",
                "viewer_read": "the blade stopped",
            }]},
        }]}
        report = evaluate(plan)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("externalized_visible_phenomenon", report["failures"][0]["fields"])


if __name__ == "__main__":
    unittest.main()
