import unittest

from tools.symbolic_shot_legibility_gate import evaluate


def symbolic_shot():
    intended = "One person is divided into greed, anger and delusion."
    return {
        "shot_id": "S1",
        "shot_kind": "avatar",
        "symbolic_shot": True,
        "intended_read": intended,
        "differentiation_spec": {
            "dimensions": ["body", "wardrobe", "expression", "pose"],
            "separate_prompt_segment_per_entity": True,
            "entities": [
                {"visual_label": "greed"},
                {"visual_label": "anger"},
                {"visual_label": "delusion"},
            ],
        },
        "script_hidden_visual_blind_test": {
            "status": "PASS",
            "observed_read": intended,
        },
    }


class SymbolicShotLegibilityGateTests(unittest.TestCase):
    def test_passes_differentiated_symbolic_shot(self):
        self.assertEqual(evaluate({"shots": [symbolic_shot()]})["status"], "PASS")

    def test_rejects_clone_like_symbolic_shot(self):
        shot = symbolic_shot()
        shot["differentiation_spec"]["dimensions"] = ["face"]
        shot["differentiation_spec"]["entities"] = [
            {"visual_label": "clone"},
            {"visual_label": "clone"},
            {"visual_label": "clone"},
        ]
        shot["script_hidden_visual_blind_test"]["observed_read"] = "Three identical men."
        report = evaluate({"shots": [shot]})
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("differentiation_dimensions_below_3:S1", report["failures"])
        self.assertIn("blind_read_mismatch:S1", report["failures"])


if __name__ == "__main__":
    unittest.main()
