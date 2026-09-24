import importlib.util
from pathlib import Path
import unittest

MODULE = Path(__file__).resolve().parents[2] / "lines/nalu/runtime/tools/build_burnin_subtitles.py"
spec = importlib.util.spec_from_file_location("burnin_mapping", MODULE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CaptionMappingTests(unittest.TestCase):
    def test_source_trim_rebases(self):
        self.assertEqual(module.caption_window({"start": 10, "duration": 4, "in": 3}, 4, 5, 0), (11, 12))

    def test_removed_dialogue_not_resurrected_by_padding(self):
        clip = {"start": 10, "duration": 4, "in": 3}
        self.assertIsNone(module.caption_window(clip, 1, 3))
        self.assertIsNone(module.caption_window(clip, 7, 8))

    def test_tail_guard_does_not_cut_speech(self):
        start, end = module.caption_window({"start": 20, "duration": 5.056}, 3, 4.98)
        self.assertGreaterEqual(end, 24.98)
        self.assertLessEqual(end, 25.056)

    def test_normal_silence_still_clears_cut(self):
        self.assertEqual(module.caption_window({"duration": 5}, 3.5, 4.6, 0.3), (3.2, 4.75))

    def test_partial_interval_clamped(self):
        self.assertEqual(module.caption_window({"duration": 2, "in": 3}, 2, 6, 0), (0, 2))

    def test_retiming_rejected_like_renderer(self):
        for key in ("speed", "playbackRate"):
            with self.assertRaises(ValueError):
                module.caption_window({"duration": 3, key: 1.2}, 0, 1)

    def test_invalid_times_fail(self):
        for value in (-1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                module.caption_window({"duration": value}, 0, 1)


if __name__ == "__main__":
    unittest.main()
