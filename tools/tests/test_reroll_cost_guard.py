import unittest

from tools.reroll_cost_guard import evaluate


POLICY = {
    "max_rerolls_per_shot": 2,
    "episode_reroll_shot_fraction": 0.15,
    "same_reason_distinct_shot_limit": 2,
}


class RerollCostGuardTests(unittest.TestCase):
    def test_block_failure_can_use_second_and_final_reroll(self):
        result = evaluate(
            POLICY,
            {"events": []},
            shot_id="S1",
            reroll_number=2,
            failure_tier="BLOCK",
            failure_reason="FREEZE",
            total_paid_tasks=20,
        )
        self.assertEqual(result["status"], "PASS_AUTO_REROLL_ALLOWED")
        self.assertIn("FINAL_AUTOMATIC_REROLL_FOR_SHOT", result["warnings"])

    def test_advise_never_auto_rerolls(self):
        result = evaluate(
            POLICY,
            {"events": []},
            shot_id="S1",
            reroll_number=1,
            failure_tier="ADVISE",
            failure_reason="BRIGHTNESS_EDGE",
            total_paid_tasks=20,
        )
        self.assertEqual(result["status"], "BLOCK_AUTO_REROLL")

    def test_third_reroll_is_blocked(self):
        result = evaluate(
            POLICY,
            {"events": []},
            shot_id="S1",
            reroll_number=3,
            failure_tier="BLOCK",
            failure_reason="FREEZE",
            total_paid_tasks=20,
        )
        self.assertIn("PER_SHOT_REROLL_LIMIT_EXCEEDED", result["failures"])

    def test_episode_budget_is_enforced(self):
        ledger = {
            "events": [
                {"shot_id": "S1", "outcome": "SUBMITTED"},
                {"shot_id": "S2", "outcome": "SUBMITTED"},
                {"shot_id": "S3", "outcome": "SUBMITTED"},
            ]
        }
        result = evaluate(
            POLICY,
            ledger,
            shot_id="S4",
            reroll_number=1,
            failure_tier="BLOCK",
            failure_reason="FREEZE",
            total_paid_tasks=20,
        )
        self.assertIn("EPISODE_REROLL_BUDGET_EXCEEDED", result["failures"])

    def test_same_reason_on_two_other_shots_requires_system_fix(self):
        ledger = {
            "events": [
                {
                    "shot_id": "S1",
                    "outcome": "SUBMITTED",
                    "failure_reason": "IDENTITY_DRIFT",
                },
                {
                    "shot_id": "S2",
                    "outcome": "SUBMITTED",
                    "failure_reason": "IDENTITY_DRIFT",
                },
            ]
        }
        result = evaluate(
            POLICY,
            ledger,
            shot_id="S3",
            reroll_number=1,
            failure_tier="BLOCK",
            failure_reason="IDENTITY_DRIFT",
            total_paid_tasks=30,
        )
        self.assertIn(
            "REPEATED_REASON_REQUIRES_PROMPT_OR_ASSET_FIX", result["failures"]
        )


if __name__ == "__main__":
    unittest.main()
