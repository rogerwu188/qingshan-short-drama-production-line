import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from validate_audit_timestamps import validate


class ValidateAuditTimestampsTest(unittest.TestCase):
    def write_payload(self, payload: dict) -> Path:
        handle = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump(payload, handle)
        handle.close()
        return Path(handle.name)

    def test_past_timestamp_passes(self) -> None:
        path = self.write_payload({"created_at": "2026-07-16T20:00:00-07:00"})
        now = datetime.fromisoformat("2026-07-16T21:00:00-07:00")
        self.assertEqual(validate(path, now), [])

    def test_future_timestamp_fails(self) -> None:
        path = self.write_payload({"reviewed_at": "2026-07-16T22:00:00-07:00"})
        now = datetime.fromisoformat("2026-07-16T21:00:00-07:00")
        failures = validate(path, now)
        self.assertEqual(len(failures), 1)
        self.assertIn("future_timestamp", failures[0])

    def test_nested_timestamp_is_checked(self) -> None:
        path = self.write_payload({"items": [{"tested_at": "2026-07-16T22:00:00-07:00"}]})
        now = datetime.fromisoformat("2026-07-16T21:00:00-07:00")
        failures = validate(path, now)
        self.assertIn("$.items[0].tested_at", failures[0])


if __name__ == "__main__":
    unittest.main()
