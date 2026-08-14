import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "storyclaw_bridge_config.py"
SPEC = importlib.util.spec_from_file_location("storyclaw_bridge_config_test", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class StoryClawBridgeConfigTests(unittest.TestCase):
    def test_local_claude_primary_disables_remote_reads_and_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mode.json"
            path.write_text(
                '{"mode":"LOCAL_CLAUDE_PRIMARY","storyclaw_remote":'
                '{"read_enabled":false,"write_enabled":false}}',
                encoding="utf-8",
            )
            self.assertFalse(MODULE.storyclaw_reads_enabled(path))
            self.assertFalse(MODULE.storyclaw_writes_enabled(path))

    def test_force_override_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mode.json"
            path.write_text(
                '{"storyclaw_remote":{"read_enabled":false,"write_enabled":false}}',
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"STORYCLAW_BRIDGE_FORCE": "1"}):
                self.assertTrue(MODULE.storyclaw_reads_enabled(path))
                self.assertTrue(MODULE.storyclaw_writes_enabled(path))
