import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.agent_task_journal import (
    append_task_record,
    atomic_json,
    read_and_verify_journal,
    recover_task_state,
)


class AgentTaskJournalTests(unittest.TestCase):
    def test_append_chain_and_recover_active_job(self):
        with tempfile.TemporaryDirectory() as td:
            shared = Path(td)
            first = append_task_record(
                shared,
                "qingshan-claude-writer",
                job_id="job-1",
                status="DISPATCHED",
                event="dispatch",
            )
            second = append_task_record(
                shared,
                "qingshan-claude-writer",
                job_id="job-1",
                status="RUNNING",
                event="checkpoint",
                details={"last_n": 469},
            )
            self.assertEqual(first["record"]["sequence"], 1)
            self.assertEqual(second["record"]["sequence"], 2)
            self.assertEqual(
                second["record"]["previous_sha"], first["record"]["record_sha"]
            )
            active = (
                shared
                / "factory/agents/qingshan-claude-writer/active_job.json"
            )
            atomic_json(
                active,
                {
                    "schema": "qingshan.factory.active_job_binding.v1",
                    "status": "RUNNING",
                    "job_id": "job-1",
                },
            )
            recovered = recover_task_state(
                shared, "qingshan-claude-writer"
            )
            self.assertTrue(recovered["active_job_valid"])
            self.assertTrue(recovered["resume_required"])
            self.assertEqual(recovered["journal_records"], 2)

    def test_detects_journal_tampering(self):
        with tempfile.TemporaryDirectory() as td:
            shared = Path(td)
            result = append_task_record(
                shared,
                "qingshan-ai-aduit",
                job_id="job-2",
                status="DISPATCHED",
                event="dispatch",
            )
            journal = Path(result["journal_path"])
            record = json.loads(journal.read_text(encoding="utf-8"))
            record["status"] = "PASS"
            journal.write_text(json.dumps(record) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "record_sha mismatch"):
                read_and_verify_journal(journal)


if __name__ == "__main__":
    unittest.main()
