import unittest

from tools.retry_cap_gate import evaluate_unit, validate_submission_attempt


def attempt(number: int) -> dict:
    return {
        "attempt_no": number,
        "prompt_sha256": f"prompt-{number}",
        "qa_verdict": "FAIL",
        "defect_class": "PROMPT_SEMANTICS",
    }


class RetryCapGateTest(unittest.TestCase):
    def test_paid_retry_requires_durable_changed_prompt_contract(self):
        failures = validate_submission_attempt({"retry_attempt": 2, "prompt_sha256": "new"})
        self.assertIn("RETRY_FAILURE_MEMORY_MISSING", failures)
        self.assertIn("RETRY_MATERIAL_CHANGE_MISSING", failures)
        self.assertIn("RETRY_PRIOR_PROMPT_HISTORY_INCOMPLETE", failures)

    def test_final_paid_attempt_passes_only_with_closed_retry(self):
        task = {
            "retry_attempt": 3,
            "prompt_sha256": "third",
            "prior_prompt_sha256": ["first", "second"],
            "failure_memory": {"rule_id": "PF-TEST"},
            "material_change_from_prior_attempt": "changed motion and transport",
            "no_further_automatic_retry": True,
        }
        self.assertEqual(validate_submission_attempt(task), [])

    def test_version_rename_cannot_hide_unchanged_prompt(self):
        task = {
            "task_key": "SHOT-V99",
            "retry_attempt": 2,
            "prompt_sha256": "same",
            "prior_prompt_sha256": ["same"],
            "failure_memory": {"rule_id": "PF-TEST"},
            "material_change_from_prior_attempt": "claimed change",
        }
        self.assertIn("PROMPT_UNCHANGED_RETRY", validate_submission_attempt(task))

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
