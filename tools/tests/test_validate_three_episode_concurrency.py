import unittest

from tools.validate_three_episode_concurrency import validate


class ThreeEpisodeConcurrencyTest(unittest.TestCase):
    def setUp(self):
        self.policy = {
            "target_concurrent_episode_lines": 3,
            "current_slots": [
                {"episode": "E17"},
                {"episode": "E18R"},
                {"episode": "E19R"},
            ],
            "override_policy": {
                "allowed_roles": ["SUPERVISOR", "PRODUCER"],
                "required_fields": ["authorization_ref", "authorized_role", "effective_at", "new_slots_or_concurrency"],
            },
        }
        self.ledger = {
            "parallel_lines": [
                {"episode": "E17", "active_work": "fine cut"},
                {"episode": "E18R", "blocked_by": "voice mapping", "blocker_ref": "CL2X-237"},
                {"episode": "E19R", "active_work": "static candidates"},
            ]
        }

    def test_valid_three_episode_allocation(self):
        self.assertEqual(validate(self.policy, self.ledger), [])

    def test_missing_line_fails(self):
        self.ledger["parallel_lines"].pop()
        self.assertIn("missing_parallel_line:E19R", validate(self.policy, self.ledger))

    def test_unattributed_override_fails(self):
        self.policy["active_override"] = {"authorized_role": "AGENT"}
        errors = validate(self.policy, self.ledger)
        self.assertIn("override_role_not_authorized", errors)
        self.assertTrue(any(row.startswith("override_missing_fields:") for row in errors))

    def test_roger_authorized_runtime_override_validates_one_slot(self):
        self.policy["runtime_override"] = {
            "decision_ref": "CL2X-617",
            "target_concurrent_episode_lines": 1,
            "mode": "SINGLE_EPISODE_WORKFLOW_DEBUG",
        }
        self.policy["current_slots"] = [{"episode": "E17"}]
        self.assertEqual(validate(self.policy, self.ledger), [])


if __name__ == "__main__":
    unittest.main()
