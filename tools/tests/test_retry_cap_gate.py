import unittest

from tools.retry_cap_gate import evaluate_unit, validate_submission_attempt


def attempt(number: int) -> dict:
    return {
        "attempt_no": number,
        "prompt_sha256": f"prompt-{number}",
        "qa_verdict": "FAIL",
        "defect_class": "PROMPT_SEMANTICS",
        "failure_memory": {"do_not_repeat": f"prompt-semantic-error-{number}"},
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

    def test_image_fourth_attempt_is_allowed_with_changed_prompt_memory(self):
        task = {
            "media_type": "IMAGE",
            "retry_attempt": 4,
            "creative_attempt_ordinal": 4,
            "prompt_sha256": "fourth-image-prompt",
            "prior_prompt_sha256": ["first", "second", "third"],
            "failure_memory": {"rule_id": "IMAGE-CONTENT-FAILURE-3"},
            "material_change_from_prior_attempt": "remove split screen and keep one frame",
        }
        self.assertEqual(validate_submission_attempt(task), [])

    def test_image_attempt_cap_is_ten(self):
        attempts = [dict(attempt(number), output_path=f"candidate-{number}.png") for number in range(1, 11)]
        result = evaluate_unit({"unit_id": "KF-01", "media_type": "IMAGE", "attempts": attempts})
        self.assertEqual(result["max_attempts"], 10)
        self.assertTrue(result["attempts_exhausted"])

    def test_second_failure_advances_to_third_changed_prompt(self):
        result = evaluate_unit({"unit_id": "R02", "attempts": [attempt(1), attempt(2)]})
        self.assertEqual(result["next_action"], "AUTO_REWRITE_PROMPT_AND_SUBMIT_ATTEMPT_3")

    def test_refunded_provider_timeouts_stop_for_human_without_exhausting_attempts(self):
        attempts = [
            {
                "attempt_no": number,
                "task_id": f"task-{number}",
                "provider_error": "provider timeout",
                "actual_charged_credits": 0,
                "charge_status": "FAILED_ZERO_NET_AFTER_REFUND",
                "prompt_sha256": f"prompt-{number}",
            }
            for number in (1, 2, 3)
        ]
        result = evaluate_unit({"unit_id": "R02", "attempts": attempts})
        self.assertEqual(result["attempts_used"], 0)
        self.assertEqual(result["paid_attempt_count"], 0)
        self.assertEqual(result["provider_failure_count"], 3)
        self.assertFalse(result["attempts_exhausted"])
        self.assertEqual(
            result["next_action"],
            "BLOCKED_ON_INPUT_PROVIDER_FAILURE_REQUIRES_HUMAN",
        )

    def test_provider_failure_cannot_auto_switch_to_coverage(self):
        result = evaluate_unit({
            "unit_id": "R02",
            "attempts": [{
                "attempt_no": 1,
                "provider_error": "router mapping not found",
                "actual_charged_credits": 0,
                "prompt_sha256": "prompt-1",
            }],
            "terminal_decision": {
                "action": "SWITCH_COVERAGE",
                "replacement_plan": "silent still montage",
            },
        })
        self.assertIn(
            "PROVIDER_FAILURE_CANNOT_TRIGGER_CREATIVE_FALLBACK",
            {row["code"] for row in result["violations"]},
        )

    def test_dialogue_retirement_requires_specific_human_approval(self):
        result = evaluate_unit({
            "unit_id": "R02",
            "attempts": [attempt(1), attempt(2), attempt(3)],
            "terminal_decision": {
                "action": "SCRIPT_EQUIVALENT_ADJUSTMENT",
                "retires_spoken_dialogue": True,
            },
        })
        codes = {row["code"] for row in result["violations"]}
        self.assertIn("SCRIPT_EQUIVALENT_REQUIRES_EXPLICIT_HUMAN_APPROVAL", codes)
        self.assertIn("DIALOGUE_RETIREMENT_REQUIRES_EXPLICIT_HUMAN_APPROVAL", codes)

    def test_submission_ordinal_can_exceed_three_after_only_provider_failures(self):
        task = {
            "retry_attempt": 4,
            "creative_attempt_ordinal": 1,
            "prompt_sha256": "fourth-submission-first-creative",
            "prior_prompt_sha256": ["first", "second", "third"],
            "prior_failure_classifications": [
                "PROVIDER_TRANSPORT_FAILURE",
                "PROVIDER_TRANSIENT_FAILURE",
                "SUBMISSION_NOT_ACCEPTED",
            ],
            "failure_memory": {"rule_id": "PF-PROVIDER"},
            "material_change_from_prior_attempt": "simplified prompt and repaired route",
            "provider_resolution_status": "VERIFIED_RESOLVED",
            "provider_resolution_ref": "workflow/provider_resolutions/route-incident-1.json",
        }
        self.assertEqual(validate_submission_attempt(task), [])

    def test_provider_failure_cannot_retry_without_human_resolution(self):
        task = {
            "retry_attempt": 2,
            "creative_attempt_ordinal": 1,
            "prompt_sha256": "second-submission",
            "prior_prompt_sha256": ["first"],
            "prior_failure_classifications": ["PROVIDER_TRANSIENT_FAILURE"],
            "failure_memory": {"rule_id": "PF-PROVIDER"},
            "material_change_from_prior_attempt": "reduced prompt",
        }
        failures = validate_submission_attempt(task)
        self.assertIn("PROVIDER_FAILURE_REQUIRES_HUMAN_RESOLUTION", failures)
        self.assertIn("PROVIDER_RESOLUTION_EVIDENCE_MISSING", failures)


if __name__ == "__main__":
    unittest.main()
