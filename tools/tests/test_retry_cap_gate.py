import unittest

from tools.retry_cap_gate import evaluate_unit


def attempt(number: int) -> dict:
    return {
        "attempt_no": number,
        "prompt_sha256": f"prompt-{number}",
        "qa_verdict": "FAIL",
        "defect_class": "PROMPT_SEMANTICS",
    }


class RetryCapGateTest(unittest.TestCase):
    def test_third_failure_requires_terminal_decision(self):
        result = evaluate_unit({"unit_id": "R02", "attempts": [attempt(1), attempt(2), attempt(3)]})
        self.assertEqual(result["max_attempts"], 3)
        self.assertIn("STALLED_NO_TERMINAL_DECISION", {row["code"] for row in result["violations"]})

    def test_fourth_attempt_is_forbidden_even_after_switch(self):
        result = evaluate_unit({
            "unit_id": "R02",
            "attempts": [attempt(1), attempt(2), attempt(3), attempt(4)],
            "terminal_decision": {"action": "SWITCH_COVERAGE", "replacement_plan": "macro insert"},
        })
        self.assertIn("ATTEMPT_CAP_EXCEEDED", {row["code"] for row in result["violations"]})

    def test_second_failure_advances_to_third_changed_prompt(self):
        result = evaluate_unit({"unit_id": "R02", "attempts": [attempt(1), attempt(2)]})
        self.assertEqual(result["next_action"], "ATTEMPT_3_WITH_CHANGED_PROMPT")


if __name__ == "__main__":
    unittest.main()
