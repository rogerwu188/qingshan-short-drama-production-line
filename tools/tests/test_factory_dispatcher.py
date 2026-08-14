import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.factory_dispatcher import (
    ROUTE_REGISTRY_SCHEMA,
    dispatch_once,
    route_registry_path,
)


class FactoryDispatcherTests(unittest.TestCase):
    def make_event(self, root: Path) -> Path:
        event_dir = root / "tenants/t1/control/events"
        event_dir.mkdir(parents=True)
        now = datetime.now(timezone.utc)
        event = {
            "event_id": "evt-1",
            "tenant_id": "t1",
            "project_id": "p1",
            "episode_id": "E01",
            "stage": "FULL_SERIES_WRITER",
            "from_agent": "qingshan-producer-supervisor",
            "to_agent": "qingshan-claude-writer",
            "admission_sha": "a" * 64,
            "artifact_sha": "b" * 64,
            "idempotency_key": "t1:p1:E01:writer",
            "project_root": "/srv/factory/projects/p1",
            "project_facts_abs": "/srv/factory/projects/p1/source/facts/chapter_facts.jsonl",
            "project_checkpoint_abs": "/srv/factory/projects/p1/source/corpus/checkpoint.tsv",
            "attempt": 0,
            "created_at": now.isoformat(),
            "not_before": (now - timedelta(seconds=1)).isoformat(),
            "expires_at": (now + timedelta(hours=1)).isoformat(),
        }
        path = event_dir / "evt-1.json"
        path.write_text(json.dumps(event), encoding="utf-8")
        return path

    def test_dry_run_is_ready_and_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.make_event(root)
            first = dispatch_once(root, dry_run=True)
            second = dispatch_once(root, dry_run=True)
            self.assertEqual(first["status"], "PASS")
            self.assertEqual(first["processed"], 1)
            self.assertEqual(second["processed"], 1)
            self.assertEqual(
                second["outcomes"][0]["status"], "DRY_RUN_READY"
            )
            route = first["outcomes"][0]["route"]
            self.assertEqual(route["agent_id"], "qingshan-claude-writer")
            self.assertFalse(route["session_discovery_used"])
            registry = json.loads(
                route_registry_path(root).read_text(encoding="utf-8")
            )
            self.assertEqual(registry["schema"], ROUTE_REGISTRY_SCHEMA)
            self.assertFalse(registry["session_discovery_required"])

    def test_missing_wake_adapter_blocks_real_dispatch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.make_event(root)
            result = dispatch_once(root, dry_run=False)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(
                result["outcomes"][0]["status"], "BLOCKED_NO_WAKE_ADAPTER"
            )
            self.assertEqual(
                result["outcomes"][0]["route"]["transport"],
                "direct_agent_id",
            )

    def test_direct_agent_id_dispatch_does_not_list_sessions(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.make_event(root)
            command = "printf 'WAKE:%s' {agent_id}"
            with patch.dict(
                os.environ, {"QINGSHAN_AGENT_WAKE_COMMAND": command}, clear=False
            ):
                result = dispatch_once(root, dry_run=False)
            self.assertEqual(result["status"], "PASS")
            outcome = result["outcomes"][0]
            self.assertEqual(outcome["status"], "DISPATCHED")
            self.assertEqual(
                outcome["route"]["agent_id"], "qingshan-claude-writer"
            )
            self.assertFalse(outcome["route"]["session_discovery_used"])
            binding = Path(outcome["active_job_binding"])
            self.assertTrue(binding.is_file())
            binding_data = json.loads(binding.read_text(encoding="utf-8"))
            self.assertEqual(binding_data["status"], "DISPATCHED")
            self.assertEqual(
                binding_data["project_paths"]["project_facts_abs"],
                "/srv/factory/projects/p1/source/facts/chapter_facts.jsonl",
            )
            journal = Path(outcome["task_journal"])
            self.assertTrue(journal.is_file())
            journal_record = json.loads(journal.read_text(encoding="utf-8"))
            self.assertEqual(journal_record["status"], "DISPATCHED")
            self.assertEqual(
                journal_record["record_sha"],
                outcome["task_journal_record_sha"],
            )

    def test_rejects_route_registry_that_requires_session_discovery(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.make_event(root)
            path = route_registry_path(root)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "schema": ROUTE_REGISTRY_SCHEMA,
                        "session_discovery_required": True,
                        "targets": {},
                    }
                ),
                encoding="utf-8",
            )
            result = dispatch_once(root, dry_run=True)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(
                result["outcomes"][0]["status"],
                "BLOCKED_INVALID_AGENT_ROUTE",
            )

    def test_writer_event_requires_absolute_project_paths(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            event_path = self.make_event(root)
            event = json.loads(event_path.read_text(encoding="utf-8"))
            event["project_facts_abs"] = "facts/chapter_facts.jsonl"
            event_path.write_text(json.dumps(event), encoding="utf-8")
            result = dispatch_once(root, dry_run=True)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertIn(
                "not_absolute:project_facts_abs",
                result["outcomes"][0]["failures"],
            )


if __name__ == "__main__":
    unittest.main()
