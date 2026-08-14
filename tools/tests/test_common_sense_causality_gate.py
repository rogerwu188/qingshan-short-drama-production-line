import unittest

from tools.common_sense_causality_gate import evaluate


def valid_unit():
    return {
        "unit_id": "U01",
        "causality": {
            "applicable": True,
            "purpose": "封住唯一出口",
            "intended_effect": "对手无法从门口逃离",
            "preconditions": ["门已关闭", "门闩位于室内搭扣"],
            "mechanism_chain": ["门闩落入两侧搭扣", "门板受推力时由门框承力"],
            "visible_causality": "门闩两端都卡入搭扣，推门时门框颤动但门不开",
            "viewer_read": "门确实被从内侧封死",
            "counterfactual_test": {
                "opponent_can_bypass": False,
                "reasoning": "房间没有第二出口，门闩不能从门外取下",
            },
            "prop_function_status": "PASS",
            "evidence_refs": ["storyboard://U01/C2"],
        },
    }


class CommonSenseCausalityGateTests(unittest.TestCase):
    def test_complete_causality_chain_passes(self):
        self.assertEqual(evaluate({"units": [valid_unit()]})["status"], "PASS")

    def test_bypass_possible_fails(self):
        unit = valid_unit()
        unit["causality"]["counterfactual_test"]["opponent_can_bypass"] = True
        result = evaluate({"units": [unit]})
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("U01:counterfactual_bypass_not_disproved", result["failures"])

    def test_missing_visible_causality_fails(self):
        unit = valid_unit()
        del unit["causality"]["visible_causality"]
        self.assertEqual(evaluate({"units": [unit]})["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
