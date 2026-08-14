import importlib.util
import os
import tempfile
import unittest
from unittest import mock
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "youtube_shorts_runtime_gate.py"
SPEC = importlib.util.spec_from_file_location("youtube_shorts_runtime_gate", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class YoutubeShortsRuntimeGateTests(unittest.TestCase):
    def test_target_passes(self):
        self.assertEqual(MODULE.evaluate(179.0, 179.0, 180.0), ("PASS", True))

    def test_margin_warns_but_remains_eligible(self):
        self.assertEqual(
            MODULE.evaluate(179.5, 179.0, 180.0),
            ("PASS_WITH_MARGIN_WARNING", True),
        )

    def test_over_hard_limit_fails(self):
        self.assertEqual(
            MODULE.evaluate(180.001, 179.0, 180.0),
            ("FAIL_YOUTUBE_SHORTS_RUNTIME", False),
        )

    def test_ffprobe_env_override_is_portable(self):
        with tempfile.TemporaryDirectory() as tmp:
            probe = Path(tmp) / "ffprobe"
            probe.write_text("probe", encoding="utf-8")
            with mock.patch.dict(os.environ, {"FFPROBE": str(probe)}):
                self.assertEqual(MODULE.ffprobe_path(), probe)


if __name__ == "__main__":
    unittest.main()
