import importlib.util
import unittest
from datetime import datetime
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[2] / "workflow/dashboard/build_status.py"
SPEC = importlib.util.spec_from_file_location("dashboard_build_status", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class DashboardLineHeartbeatWatchdogTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.fromisoformat("2026-07-16T20:30:00-07:00")

    def test_none_over_thirty_minutes_is_breach(self):
        rows = [{"line_id": "E17", "blocked_by": "NONE", "last_heartbeat_at": "2026-07-16T19:59:00-07:00"}]
        result = MODULE.parallel_line_sla_breaches(rows, now=self.now)
        self.assertEqual(result[0]["kind"], "IDLE_WITHOUT_BLOCKER")

    def test_remote_over_eighty_minutes_is_breach(self):
        rows = [{"line_id": "E18R", "blocked_by": "REMOTE_GENERATION", "last_heartbeat_at": "2026-07-16T19:00:00-07:00"}]
        result = MODULE.parallel_line_sla_breaches(rows, now=self.now)
        self.assertEqual(result[0]["kind"], "REMOTE_GENERATION_UNHARVESTED")

    def test_session_ended_is_not_breach(self):
        rows = [{"line_id": "E19R", "blocked_by": "SESSION_ENDED", "last_heartbeat_at": "2026-07-16T10:00:00-07:00"}]
        self.assertEqual(MODULE.parallel_line_sla_breaches(rows, now=self.now), [])


if __name__ == "__main__":
    unittest.main()
