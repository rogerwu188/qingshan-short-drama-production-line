import unittest

from tools.video_generation_failure_policy import (
    classify_attempt,
    evaluate_failure_workflow,
)


class VideoGenerationFailurePolicyTest(unittest.TestCase):
    def test_insufficient_credits_is_provider_failure_and_does_not_consume_attempt(self):
        result = evaluate_failure_workflow({
            "media_kind": "VIDEO",
            "attempts": [{
                "attempt_no": 1,
                "error": "Giggle API: insufficient credits",
                "charge_status": "VERIFIED_ZERO",
            }],
        })
        self.assertEqual(result["latest_failure_class"], "PROVIDER_INSUFFICIENT_CREDITS")
        self.assertEqual(result["creative_attempt_count"], 0)
        self.assertEqual(result["paid_attempt_count"], 0)
        self.assertEqual(result["status"], "BLOCKED_ON_INPUT_PROVIDER_FAILURE")
        self.assertIn("credits_restored=true", result["human_notification"]["required_resolution_fields"])

    def test_insufficient_credits_resumes_after_verified_replenishment(self):
        result = evaluate_failure_workflow({
            "media_kind": "VIDEO",
            "attempts": [{"attempt_no": 1, "error": "积分不足", "charge_status": "VERIFIED_ZERO"}],
            "provider_resolution": {
                "status": "VERIFIED_RESOLVED",
                "evidence_ref": "workflow/tasks/credits_restored.json",
                "credits_restored": True,
            },
        })
        self.assertEqual(result["next_action"], "RESUME_GENERATION_AFTER_VERIFIED_PROVIDER_RESOLUTION")

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
                "prompt_sha256": "bad-prompt",
                "failure_reason": "frozen actor",
                "do_not_repeat": "one physical action only",
            }]
        })
        self.assertEqual(result["creative_attempt_count"], 1)
        self.assertEqual(result["paid_attempt_count"], 1)
        self.assertEqual(result["next_action"], "AUTO_REWRITE_PROMPT_AND_SUBMIT_ATTEMPT_2")
        self.assertEqual(result["prompt_failure_records"][0]["prompt_sha256"], "bad-prompt")
        self.assertEqual(result["prompt_rewrite_contract"]["next_creative_attempt"], 2)

    def test_zero_task_id_submit_failure_stops_for_human(self):
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
            "BLOCKED_ON_INPUT_PROVIDER_FAILURE_REQUIRES_HUMAN",
        )
        self.assertTrue(result["human_notification"]["notify_human"])

    def test_three_prompt_failures_stop_and_report_prompt_reasons(self):
        attempts = [
            {
                "attempt_no": number,
                "prompt_sha256": f"prompt-{number}",
                "failure_class": "CANDIDATE_QA_FAILURE",
                "failure_reason": reason,
                "do_not_repeat": memory,
                "remote_status": "completed",
                "output_path": f"candidate-{number}.mp4",
                "qa_verdict": "FAIL",
                "actual_charged_credits": 64,
            }
            for number, reason, memory in [
                (1, "two simultaneous actions caused frozen actors", "one action only"),
                (2, "camera move obscured lip performance", "fixed camera"),
                (3, "dialogue truncated at clip end", "finish line before final second"),
            ]
        ]
        result = evaluate_failure_workflow({"attempts": attempts})
        self.assertEqual(result["status"], "BLOCKED_ON_INPUT_PROMPT_ATTEMPTS_EXHAUSTED")
        self.assertEqual(
            result["next_action"],
            "BLOCKED_ON_INPUT_PROMPT_ATTEMPTS_EXHAUSTED_REQUIRES_HUMAN",
        )
        self.assertEqual(len(result["human_notification"]["prompt_failure_records"]), 3)
        self.assertEqual(
            result["human_notification"]["prompt_failure_records"][2]["failure_reason"],
            "dialogue truncated at clip end",
        )

    def test_three_image_failures_advance_to_attempt_four(self):
        attempts = [
            {
                "attempt_no": number,
                "prompt_sha256": f"image-prompt-{number}",
                "failure_class": "CANDIDATE_QA_FAILURE",
                "failure_reason": f"image defect {number}",
                "do_not_repeat": f"avoid image defect {number}",
                "output_path": f"candidate-{number}.png",
                "qa_verdict": "FAIL",
            }
            for number in range(1, 4)
        ]
        result = evaluate_failure_workflow({"media_type": "IMAGE", "attempts": attempts})
        self.assertEqual(result["creative_attempt_limit"], 10)
        self.assertEqual(result["next_action"], "AUTO_REWRITE_PROMPT_AND_SUBMIT_ATTEMPT_4")
        self.assertFalse(result["human_notification"]["notify_human"])


if __name__ == "__main__":
    unittest.main()
