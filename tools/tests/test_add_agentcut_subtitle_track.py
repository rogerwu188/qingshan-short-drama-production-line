import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "add_agentcut_subtitle_track.py"
SPEC = importlib.util.spec_from_file_location("add_agentcut_subtitle_track", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class AddAgentCutSubtitleTrackTests(unittest.TestCase):
    def test_explicit_cross_platform_font_is_resolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            font = Path(tmp) / "NotoSansCJK-Regular.ttc"
            font.write_bytes(b"font")
            self.assertEqual(MODULE.resolve_subtitle_font(str(font)), str(font.resolve()))

    def test_missing_explicit_font_fails_closed(self):
        with self.assertRaises(SystemExit):
            MODULE.resolve_subtitle_font("/missing/cjk-font.ttc")


if __name__ == "__main__":
    unittest.main()
