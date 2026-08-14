import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "run_regression_ci.py"
SPEC = importlib.util.spec_from_file_location("run_regression_ci", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class SpeechDensityGateTests(unittest.TestCase):
    def payload(self, count):
        return {
            "segments": [
                {"start": index * 2.0, "end": index * 2.0 + 1.0, "text": "这是对白"}
                for index in range(count)
            ]
        }

    def test_passes_at_fifteen_segments_per_minute(self):
        result = MODULE.speech_density_stats(self.payload(45), 180.0)
        self.assertEqual(result["status"], "PASS")

    def test_fails_between_threshold_and_redline(self):
        result = MODULE.speech_density_stats(self.payload(36), 180.0)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("speech_density_below_threshold:12.00", result["failures"])

    def test_redlines_below_ten_segments_per_minute(self):
        result = MODULE.speech_density_stats(self.payload(27), 180.0)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("speech_density_redline:9.00", result["failures"])

    def test_missing_asr_segments_fails(self):
        result = MODULE.speech_density_stats({}, 180.0)
        self.assertEqual(result["status"], "MISSING")

    def test_non_chinese_segments_do_not_count(self):
        result = MODULE.speech_density_stats(
            {"segments": [{"start": 0, "end": 1, "text": "hello"}]},
            180.0,
        )
        self.assertEqual(result["segment_count"], 0)


if __name__ == "__main__":
    unittest.main()
