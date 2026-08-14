import json
import tempfile
import unittest
from pathlib import Path

from tools.line_heartbeat import record_line_heartbeat, validate_blocked_by


class LineHeartbeatTest(unittest.TestCase):
    def test_invalid_blocker_rejected_before_write(self):
        with self.assertRaises(ValueError):
            validate_blocked_by("REMOTE_VOICE_ASSET_REGISTRATION_CHANNEL")

    def test_heartbeat_writes_legal_blocker_and_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            path.write_text(json.dumps({"parallel_lines": [{"line_id": "E20_W1"}]}), encoding="utf-8")
            line = record_line_heartbeat(
                path,
                "E20_W1",
                active_work="VOICE_QA",
                blocked_by="REMOTE_VOICE_ASSET_REGISTRATION",
                blocker_ref="qa/voice.json",
                now="2026-07-18T18:00:00-07:00",
            )
            self.assertEqual(line["last_heartbeat_at"], "2026-07-18T18:00:00-07:00")
            self.assertEqual(json.loads(path.read_text())["parallel_lines"][0]["blocked_by"], "REMOTE_VOICE_ASSET_REGISTRATION")

    def test_none_clears_blocker_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            path.write_text(json.dumps({"parallel_lines": [{"line_id": "E20_W1", "blocked_since_at": "old"}]}), encoding="utf-8")
            line = record_line_heartbeat(path, "E20_W1", active_work="LOCAL_QA", now="2026-07-18T18:00:00-07:00")
            self.assertEqual(line["blocked_by"], "NONE")
            self.assertNotIn("blocked_since_at", line)
            self.assertIsNone(line["blocker_ref"])

