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
            self.assertEqual(fleet_sync.run_command(cp, {"type": "update"})[2],
                             {"action": "AGENT", "reason": "FLEET_UPDATE"})
            fleet_sync.run_command(cp, {"type": "pause"})
            self.assertTrue((rt / "series" / "PAUSED").exists())
            fleet_sync.run_command(cp, {"type": "unpause"})
            self.assertFalse((rt / "series" / "PAUSED").exists())
            self.assertFalse(fleet_sync.run_command(cp, {"type": "shell", "payload": {"cmd": "rm -rf /"}})[0])

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
