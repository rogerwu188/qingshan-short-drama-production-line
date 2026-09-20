import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.validate_three_episode_concurrency import (
    PORTABLE_POLICY,
    default_policy_path,
    validate,
)


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

    def test_public_template_has_no_live_episode_or_fail_open_state(self):
        policy = json.loads(Path(PORTABLE_POLICY).read_text(encoding="utf-8"))
        self.assertEqual(policy["status"], "REQUIRES_PROJECT_CONFIGURATION")
        self.assertEqual(policy["current_slots"], [])
        self.assertEqual(policy["next_episode_queue"], [])
        self.assertEqual(
            policy["conditional_machine_admission_policy"]["status"],
            "DISABLED_IN_PUBLIC_BOOTSTRAP",
        )
        self.assertIn("current_slot_count_mismatch", validate(policy, {}))
        serialized = json.dumps(policy, ensure_ascii=False)
        for private_marker in ("E32", "E35", "ROGER-", "platform_publication_receipt"):
            self.assertNotIn(private_marker, serialized)

    def test_current_portable_chooses_public_template(self):
        with patch.dict(os.environ, {"NALU_POLICY_PROFILE": "CURRENT_PORTABLE"}):
            self.assertEqual(default_policy_path(), PORTABLE_POLICY)


if __name__ == "__main__":
    unittest.main()
