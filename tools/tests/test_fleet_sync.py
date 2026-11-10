"""Fleet channel on the device: whitelisted commands only, never breaks the tick (nalu-fleet, 2026-11-09)."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "nalu-claude-code" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import fleet_sync  # noqa: E402


class FleetSyncTest(unittest.TestCase):
    def cp(self, runtime: Path, resumed: list):
        return SimpleNamespace(roots=lambda: (runtime, runtime), current_episode=lambda: "E04",
                               resume=lambda ep, msg: resumed.append((ep, msg)) or {"status": "STARTED"})

    def test_whitelisted_commands(self):
        with tempfile.TemporaryDirectory() as d:
            rt, resumed = Path(d), []
            cp = self.cp(rt, resumed)
            ok, res, _ = fleet_sync.run_command(cp, {"type": "resume", "payload": {"message": "继续"}})
            self.assertTrue(ok)
            self.assertIn("继续", resumed[0][1])
            fleet_sync.run_command(cp, {"type": "pause"})
            self.assertTrue((rt / "series" / "PAUSED").exists())
            fleet_sync.run_command(cp, {"type": "unpause"})
            self.assertFalse((rt / "series" / "PAUSED").exists())
            self.assertFalse(fleet_sync.run_command(cp, {"type": "shell", "payload": {"cmd": "rm -rf /"}})[0])

    def test_update_is_scripted_and_resumes_a_blocked_episode_when_the_engine_moved(self):
        # …1324 E04: the agent-run FLEET_UPDATE set up the stale pin; the script reads the pin after self_update
        new_pin, calls, resumed, sha = "b" * 40, [], [], ["a" * 40]

        def fake_run(argv, timeout):
            calls.append(Path(argv[1]).name)
            if Path(argv[1]).name == "setup_host.sh":
                self.assertTrue((Path(argv[1]).parent / "configure_codex.py").is_file())  # siblings copied too
                self.assertEqual(argv[-1], new_pin)
                sha[0] = new_pin
            return 0, "NALU_SETUP: {}"
        saved = fleet_sync._run, fleet_sync._engine_sha, fleet_sync.disk_pin
        fleet_sync._run, fleet_sync._engine_sha, fleet_sync.disk_pin = fake_run, lambda e: sha[0], lambda: new_pin
        try:
            with tempfile.TemporaryDirectory() as d:
                cp = self.cp(Path(d), resumed)
                cp.status = lambda ep: {"status": "IDLE", "codex": {"nalu_status": {"state": "BLOCKED"}}}
                ok, res, extra = fleet_sync.run_command(cp, {"type": "update"})
        finally:
            fleet_sync._run, fleet_sync._engine_sha, fleet_sync.disk_pin = saved
        self.assertTrue(ok)
        self.assertEqual(extra, {})
        self.assertEqual(calls, ["self_update.sh", "setup_host.sh"])  # self_update first, then the new pin
        self.assertEqual(res["after"], new_pin[:12])
        self.assertIn(new_pin[:7], resumed[0][1])

    def test_setup_diagnostics_surface_the_failed_step(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "setup.log"
            log.write_text("start\nconfigure_codex: {\"status\": \"FAILED\", \"error\": \"x\"}\nend\n")
            out = "noise\nNALU_SETUP: " + json.dumps({"status": "BLOCKED", "failed_step": "codex_config",
                                                      "log": str(log), "steps": {"codex_config": "FAILED"}})
            diag = fleet_sync._setup_diagnostics(out)
        self.assertEqual((diag["setup_status"], diag["setup_failed_step"]), ("BLOCKED", "codex_config"))
        self.assertIn("configure_codex", diag["setup_log_tail"][0])

    def test_disk_pin_reads_the_installed_agents_md(self):
        import os
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d) / ".openclaw" / "workspace-x"
            ws.mkdir(parents=True)
            (ws / "AGENTS.md").write_text('NALU line\nbash "$S/setup_host.sh" --pin ' + "c" * 40 + "\n")
            saved = os.environ.get("HOME")
            os.environ["HOME"] = d
            try:
                self.assertEqual(fleet_sync.disk_pin(), "c" * 40)
            finally:
                os.environ["HOME"] = saved

    def test_disabled_or_failing_channel_never_raises(self):
        import os
        os.environ["NALU_FLEET_URL"] = "off"
        try:
            self.assertEqual(fleet_sync.sync(object(), {}), {})
        finally:
            os.environ.pop("NALU_FLEET_URL")
        os.environ["NALU_FLEET_URL"] = "http://127.0.0.1:9"  # nothing listens
        try:
            out = fleet_sync.sync(SimpleNamespace(roots=lambda: (Path("/nonexistent"), Path("/nonexistent"))), {})
            self.assertTrue(str(out.get("fleet", "")).startswith(("ERROR", "NOT_REGISTERED", "NO_DEVICE_SN")))
        finally:
            os.environ.pop("NALU_FLEET_URL")


if __name__ == "__main__":
    unittest.main()
