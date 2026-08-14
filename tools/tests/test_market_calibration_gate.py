import unittest

from tools.market_calibration_gate import validate


def policy():
    return {
        "event_layer": {"frozen_fields": ["information_nodes", "causal_chain"]},
        "performance_layer": {
            "allowed_fields": ["opening_method", "narrative_engine"]
        },
        "evidence_policy": {
            "decision_window": "T+72h",
            "minimum_plays_for_inference": 500,
            "same_direction_hypotheses_required": 3,
            "maximum_episodes_affected_per_change": 5,
        },
        "approval_chain": ["CODEX_PROPOSAL", "CLAUDE_REVIEW", "ROGER_APPROVAL"],
    }


def entry(episode, plays, status, direction="completion_rate_up"):
    return {
        "episode": episode,
        "variable": "opening_method",
        "hypothesis": "test",
        "expected_direction": direction,
        "decision_window": "T+72h",
        "plays": plays,
        "result": "PENDING_T72",
        "inference_status": status,
    }


class MarketCalibrationGateTests(unittest.TestCase):
    def test_accepts_record_only_low_sample_ledger(self):
        report = validate(
            policy(),
            {"entries": [entry("E17", 11, "RECORD_ONLY_INSUFFICIENT_SAMPLE")]},
        )
        self.assertEqual(report["status"], "PASS")

    def test_rejects_low_sample_as_decision_eligible(self):
        report = validate(
            policy(), {"entries": [entry("E17", 11, "DECISION_ELIGIBLE")]}
        )
        self.assertIn(
            "low_sample_must_be_record_only:E17",
            report["failures"],
        )

    def test_rejects_event_change_without_roger_and_weak_evidence(self):
        ledger = {
            "entries": [
                entry("E17", 900, "DECISION_ELIGIBLE"),
                entry("E18", 900, "DECISION_ELIGIBLE"),
            ]
        }
        proposal = {
            "changed_fields": ["information_nodes"],
            "affected_episodes": ["E20"],
            "evidence_direction": "completion_rate_up",
            "approvals": {},
        }
        report = validate(policy(), ledger, proposal)
        self.assertTrue(
            any(
                failure.startswith("event_layer_change_without_roger_approval")
                for failure in report["failures"]
            )
        )
        self.assertTrue(
            any(
                failure.startswith("same_direction_evidence_below_minimum")
                for failure in report["failures"]
            )
        )

    def test_accepts_bounded_performance_change_after_three_evidence_and_approvals(self):
        ledger = {
            "entries": [
                entry("E17", 900, "DECISION_ELIGIBLE"),
                entry("E18", 900, "DECISION_ELIGIBLE"),
                entry("E19", 900, "DECISION_ELIGIBLE"),
            ]
        }
        proposal = {
            "changed_fields": ["opening_method"],
            "affected_episodes": ["E20", "E21"],
            "evidence_direction": "completion_rate_up",
            "approvals": {
                "CODEX_PROPOSAL": "C2SC-353",
                "CLAUDE_REVIEW": "CL2X-FUTURE",
                "ROGER_APPROVAL": "ROGER-FUTURE",
            },
        }
        report = validate(policy(), ledger, proposal)
        self.assertEqual(report["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
