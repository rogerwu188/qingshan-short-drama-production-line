import unittest

from tools.video_generation_failure_policy import (
    classify_attempt,
    evaluate_failure_workflow,
)


class VideoGenerationFailurePolicyTest(unittest.TestCase):
    def test_router_mapping_is_transport_not_prompt_failure(self):
        self.assertEqual(
            classify_attempt({"error": "router mapping not found"}),
            "PROVIDER_TRANSPORT_FAILURE",
        )

    def test_provider_timeout_is_transient_even_with_task_id(self):
        self.assertEqual(
            classify_attempt({"task_id": "remote-1", "err_msg": "provider timeout"}),
            "PROVIDER_TRANSIENT_FAILURE",
        )

    def test_completed_bad_candidate_is_creative_failure(self):
        result = evaluate_failure_workflow({
            "attempts": [{
                "task_id": "remote-1",
                "remote_status": "completed",
                "output_path": "candidate.mp4",
                "qa_verdict": "FAIL",
                "actual_charged_credits": 64,
            }]
        })
        self.assertEqual(result["creative_attempt_count"], 1)
        self.assertEqual(result["paid_attempt_count"], 1)
        self.assertEqual(result["next_action"], "ATTEMPT_2_WITH_CHANGED_PROMPT")

    def test_zero_task_id_submit_failure_requires_recovery_retry(self):
        result = evaluate_failure_workflow({
            "attempts": [{
                "state": "submit_failed_terminal",
                "error": "missing task_id",
                "actual_charged_credits": 0,
            }]
        })
        self.assertEqual(result["creative_attempt_count"], 0)
        self.assertEqual(
            result["next_action"],
            "RETRY_AFTER_PROVIDER_RECOVERY_WITH_CHANGED_PROMPT_OR_TRANSPORT",
        )


if __name__ == "__main__":
    unittest.main()
