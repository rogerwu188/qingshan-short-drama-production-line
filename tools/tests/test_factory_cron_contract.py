import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.factory_cron_contract import validate_cron_spec


class FactoryCronContractTests(unittest.TestCase):
    def valid_spec(self):
        root = "/srv/factory/projects/p1"
        facts = root + "/source/facts/chapter_facts.jsonl"
        checkpoint = root + "/source/corpus/checkpoint.tsv"
        return {
            "owner_agent_id": "qingshan-claude-writer",
            "target_agent_id": "qingshan-claude-writer",
            "route_mode": "owner_current",
            "session_discovery_required": False,
            "project_root": root,
            "project_facts_abs": facts,
            "project_checkpoint_abs": checkpoint,
            "idempotency_key": "p1:writer:470",
            "payload": f"PROJECT_ROOT={root} FACTS={facts} CHECKPOINT={checkpoint}",
        }

    def valid_writer_staged_spec(self):
        spec = self.valid_spec()
        spec.update(
            {
                "owner_agent_id": "qingshan-producer-supervisor",
                "target_agent_id": "qingshan-claude-writer",
                "route_mode": "direct_agent_id",
            }
        )
        return spec

    def test_accepts_owner_cron_with_absolute_paths(self):
        self.assertEqual(validate_cron_spec(self.valid_spec()), [])

    def test_rejects_relative_paths_and_session_discovery(self):
        spec = self.valid_writer_staged_spec()
        spec["project_facts_abs"] = "facts/chapter_facts.jsonl"
        spec["session_discovery_required"] = True
        spec["payload"] += " sessions.list"
        failures = validate_cron_spec(spec)
        self.assertIn("not_absolute:project_facts_abs", failures)
        self.assertIn("session_discovery_must_be_false", failures)
        self.assertIn("payload_uses_session_discovery", failures)

    def test_rejects_payload_that_drops_bound_paths(self):
        spec = self.valid_writer_staged_spec()
        spec["payload"] = "continue next chapter"
        failures = validate_cron_spec(spec)
        self.assertIn("payload_missing_bound_path:project_root", failures)
        self.assertIn("payload_missing_bound_path:project_facts_abs", failures)
        self.assertIn("payload_missing_bound_path:project_checkpoint_abs", failures)

    def test_writer_staged_cron_accepts_completion_chained_one_shot(self):
        spec = self.valid_writer_staged_spec()
        spec.update(
            {
                "job_kind": "writer_staged_facts",
                "dispatch_mode": "completion_chained_one_shot",
                "one_shot_delay_seconds": 15,
                "non_overlap_required": True,
                "auto_advance_on_pass": True,
                "max_phases_per_tick": 1,
                "heartbeat_noop_seconds": 180,
                "retry_backoff_seconds": [60, 120, 240, 480, 900],
            }
        )
        self.assertEqual(validate_cron_spec(spec), [])
        spec["one_shot_delay_seconds"] = 1
        spec["non_overlap_required"] = False
        failures = validate_cron_spec(spec)
        self.assertIn("writer_staged_one_shot_delay_invalid", failures)
        self.assertIn("writer_staged_non_overlap_required", failures)

    def test_writer_staged_watchdog_is_not_primary_driver(self):
        spec = self.valid_writer_staged_spec()
        spec.update(
            {
                "job_kind": "writer_staged_facts",
                "dispatch_mode": "watchdog",
                "interval_seconds": 300,
                "stale_after_seconds": 420,
                "non_overlap_required": True,
                "max_phases_per_tick": 1,
                "heartbeat_noop_seconds": 180,
                "retry_backoff_seconds": [60, 120, 240, 480, 900],
            }
        )
        self.assertEqual(validate_cron_spec(spec), [])
        spec["interval_seconds"] = 1800
        self.assertIn(
            "writer_staged_watchdog_interval_invalid", validate_cron_spec(spec)
        )

    def test_writer_cannot_self_spawn_staged_dispatch_chain(self):
        spec = self.valid_writer_staged_spec()
        spec.update(
            {
                "job_kind": "writer_staged_facts",
                "dispatch_mode": "completion_chained_one_shot",
                "one_shot_delay_seconds": 15,
                "non_overlap_required": True,
                "auto_advance_on_pass": True,
                "max_phases_per_tick": 1,
                "heartbeat_noop_seconds": 180,
                "retry_backoff_seconds": [60, 120, 240, 480, 900],
                "owner_agent_id": "qingshan-claude-writer",
                "route_mode": "owner_current",
            }
        )
        failures = validate_cron_spec(spec)
        self.assertIn("writer_staged_dispatch_owner_must_be_producer", failures)
        self.assertIn("writer_staged_dispatch_must_direct_route_writer", failures)


if __name__ == "__main__":
    unittest.main()
