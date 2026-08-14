import unittest

from tools.mechanical_default_gate import evaluate


class MechanicalDefaultGateTests(unittest.TestCase):
    def test_mixed_unit_values_pass(self):
        payload = {"units": [{"duration_seconds": value} for value in (6, 8, 10, 12)], "variable_fields": ["duration_seconds"]}
        self.assertEqual(evaluate(payload)["status"], "PASS")

    def test_uniform_duration_without_audit_fails(self):
        payload = {"units": [{"duration_seconds": 10} for _ in range(4)], "variable_fields": ["duration_seconds"]}
        self.assertIn("uniform_variable_without_independence_audit:duration_seconds", evaluate(payload)["failures"])

    def test_uniform_result_with_independent_audit_passes(self):
        payload = {
            "units": [{"duration_seconds": 10} for _ in range(4)],
            "variable_fields": ["duration_seconds"],
            "mechanical_default_independence_audit": {
                "duration_seconds": {"status": "PASS", "evaluated_individually": True, "distinct_basis_count": 4, "rationale": "Four independently measured dialogue and action chains each require ten seconds."}
            },
        }
        self.assertEqual(evaluate(payload)["status"], "PASS")

    def test_unreviewed_global_default_fails(self):
        payload = {
            "units": [{"duration_seconds": value} for value in (6, 8, 10, 12)],
            "global_defaults": [{"field": "camera", "value": "medium"}],
        }
        self.assertIn("unreviewed_global_default:camera", evaluate(payload)["failures"])


if __name__ == "__main__":
    unittest.main()
