"""Waking the agent heartbeat from the system tick (line owner 2026-11-28「这么慢？」): rate-limited, records the outcome."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "nalu-claude-code" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import fleet_sync  # noqa: E402
import heartbeat_kick  # noqa: E402


class HeartbeatKickTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved_home = os.environ.get("HOME")
        os.environ["HOME"] = self.tmp.name
        self.saved_run = fleet_sync._run_full
        self.calls: list[list[str]] = []

    def tearDown(self):
        fleet_sync._run_full = self.saved_run
        os.environ["HOME"] = self.saved_home or ""
        self.tmp.cleanup()

    def fake_openclaw(self, list_rc=0, list_out=None, run_out='{"ok": true, "enqueued": true, "runId": "r1"}'):
        jobs = list_out if list_out is not None else json.dumps({"jobs": [
            {"id": "rep", "name": "NALU进度汇报", "enabled": True},
            {"id": "hb", "name": "NALU心跳", "enabled": True}]})

        def run(argv, timeout, extra_env=None):
            self.calls.append(argv)
            if argv[:3] == ["openclaw", "cron", "list"]:
                return list_rc, jobs
            if argv[:3] == ["openclaw", "cron", "run"]:
                return 0, run_out
            return 1, ""
        fleet_sync._run_full = run

    def test_kick_runs_the_heartbeat_job_and_records_it(self):
        self.fake_openclaw()
        out = heartbeat_kick.kick_now("E17|x", "BLOCKED")
        self.assertTrue(out["ok"])
        self.assertEqual(self.calls[-1], ["openclaw", "cron", "run", "hb"])  # the heartbeat, not the report job
        self.assertEqual(heartbeat_kick.report()["job"], "NALU心跳")

    def test_a_cli_without_scope_is_reported_not_null(self):
        # …1101 2026-11-27: `missing scope: operator.read`, every agent_task ack said heartbeat_kick null
        self.fake_openclaw(list_rc=1, list_out='{"ok": false, "error": {"message": "missing scope: operator.read"}}')
        out = heartbeat_kick.kick_now("k", "r")
        self.assertFalse(out["ok"])
        self.assertIn("missing scope", out["error"])
        self.assertIn("missing scope", heartbeat_kick.report()["error"])
        self.fake_openclaw(run_out='{"ok": false, "error": "denied"}')
        self.assertFalse(heartbeat_kick.kick_now("k", "r")["ok"])

    def test_requests_are_rate_limited_and_capped_per_hand_off(self):
        now = 1_000_000.0
        self.assertEqual(heartbeat_kick.request("a", now=now, spawn=False)["status"], "SCHEDULED")
        skipped = heartbeat_kick.request("b", now=now + 60, spawn=False)
        self.assertEqual(skipped["status"], "SKIPPED")
        self.assertTrue(skipped["why"].startswith("RATE_LIMITED"))
        step = heartbeat_kick.MIN_INTERVAL_S + 1
        for i in range(1, heartbeat_kick.MAX_PER_KEY):
            self.assertEqual(heartbeat_kick.request("a", now=now + i * step, spawn=False)["status"], "SCHEDULED")
        capped = heartbeat_kick.request("a", now=now + 10 * step, spawn=False)
        self.assertTrue(capped["why"].startswith("MAX_KICKS_FOR_HAND_OFF"))
        self.assertEqual(heartbeat_kick.request("c", now=now + 11 * step, spawn=False)["status"], "SCHEDULED")

    def test_gateway_env_and_lock_wait_never_raise(self):
        self.assertIsInstance(heartbeat_kick.gateway_env(), dict)
        self.assertTrue(heartbeat_kick.wait_for_lock(Path(self.tmp.name) / "missing" / ".tick.lock", 1))
        lock = Path(self.tmp.name) / ".tick.lock"
        self.assertTrue(heartbeat_kick.wait_for_lock(lock, 1))
        import fcntl
        with open(lock, "w") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            self.assertFalse(heartbeat_kick.wait_for_lock(lock, 0.1))


if __name__ == "__main__":
    unittest.main()
