"""device_sn.py: env first, then cache, then hardware; vendor placeholders are not serials (owner 2026-11-05)."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills/nalu-claude-code/scripts"))

import device_sn as dsn  # noqa: E402


class DeviceSnTests(unittest.TestCase):
    def test_placeholders_are_not_serials(self):
        for junk in ("To be filled by O.E.M.", "Default string", "System Serial Number", "0", "", "  \n"):
            self.assertEqual(dsn.clean(junk), "")
        self.assertEqual(dsn.clean("SCA1QCF3OMSS\n"), "SCA1QCF3OMSS")
        self.assertEqual(dsn.clean("has space"), "")

    def test_env_wins_then_cache_then_hardware(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"NALU_RUNTIME_ROOT": tmp}, clear=False):
            os.environ.pop("NALU_DEVICE_SN", None)
            with mock.patch.object(dsn, "hardware_serial", return_value=("HW123", "dmidecode")):
                self.assertEqual(dsn.resolve(), ("HW123", "dmidecode"))
            self.assertEqual((Path(tmp) / "credentials/device_sn").read_text().strip(), "HW123")
            with mock.patch.object(dsn, "hardware_serial", side_effect=AssertionError("cache must be used")):
                self.assertEqual(dsn.resolve()[0], "HW123")
            with mock.patch.dict(os.environ, {"NALU_DEVICE_SN": "ENV_SN"}):
                self.assertEqual(dsn.resolve(), ("ENV_SN", "env:NALU_DEVICE_SN"))

    def test_sudo_is_never_interactive(self):
        calls = []
        with mock.patch.object(dsn, "_run", side_effect=lambda argv: calls.append(argv) or ""), \
                mock.patch.object(dsn.Path, "read_text", side_effect=OSError):
            dsn.hardware_serial()
        self.assertIn(["sudo", "-n", "dmidecode", "-s", "system-serial-number"], calls)


if __name__ == "__main__":
    unittest.main()
