import json
import math
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

try:
    import numpy as np
except ImportError:  # the portable CI runs on the system python without numpy
    np = None

from tools import dialogue_voice_metrics as dvm

SR = 48000


def sawtooth(freq_hz: float, seconds: float, amplitude: float = 0.3, sr: int = SR) -> np.ndarray:
    t = np.arange(int(sr * seconds)) / sr
    return amplitude * (2.0 * ((t * freq_hz) % 1.0) - 1.0)


@unittest.skipIf(np is None, "numpy not installed")
class F0Tests(unittest.TestCase):
    def test_sawtooth_120hz_within_five_percent(self):
        f0 = dvm.estimate_f0_median(sawtooth(120.0, 0.8), SR)
        self.assertIsNotNone(f0)
        self.assertLess(abs(f0 - 120.0) / 120.0, 0.05)

    def test_sawtooth_220hz_within_five_percent(self):
        f0 = dvm.estimate_f0_median(sawtooth(220.0, 0.8), SR)
        self.assertIsNotNone(f0)
        self.assertLess(abs(f0 - 220.0) / 220.0, 0.05)

    def test_two_voices_are_told_apart(self):
        low = dvm.estimate_f0_median(sawtooth(120.0, 0.6), SR)
        high = dvm.estimate_f0_median(sawtooth(220.0, 0.6), SR)
        self.assertGreater(high / low, 1.5)

    def test_noise_and_silence_return_none(self):
        rng = np.random.default_rng(0)
        self.assertIsNone(dvm.estimate_f0_median(rng.normal(0.0, 0.1, SR), SR))
        self.assertIsNone(dvm.estimate_f0_median(np.zeros(SR), SR))

    def test_too_few_voiced_frames_returns_none(self):
        # 50 ms of tone gives at most two 40 ms frames at a 10 ms hop -> below the 3-frame floor
        self.assertIsNone(dvm.estimate_f0_median(sawtooth(150.0, 0.05), SR))

    def test_out_of_range_tone_returns_none(self):
        self.assertIsNone(dvm.estimate_f0_median(sawtooth(40.0, 0.8), SR))


@unittest.skipIf(np is None, "numpy not installed")
class RmsTests(unittest.TestCase):
    def test_rms_dbfs_of_full_scale_sine(self):
        t = np.arange(SR) / SR
        value = dvm.rms_dbfs(np.sin(2 * np.pi * 440 * t))
        self.assertAlmostEqual(value, 20 * math.log10(1 / math.sqrt(2)), places=2)

    def test_rms_dbfs_scales_with_amplitude(self):
        loud = dvm.rms_dbfs(sawtooth(120.0, 0.5, amplitude=0.5))
        quiet = dvm.rms_dbfs(sawtooth(120.0, 0.5, amplitude=0.25))
        self.assertAlmostEqual(loud - quiet, 6.02, places=1)

    def test_rms_dbfs_empty_or_silent_is_none(self):
        self.assertIsNone(dvm.rms_dbfs(np.zeros(0)))
        self.assertIsNone(dvm.rms_dbfs(np.zeros(100)))


@unittest.skipIf(np is None, "numpy not installed")
class MeasureSegmentsTests(unittest.TestCase):
    def test_segments_measured_independently_and_text_not_copied(self):
        signal = np.concatenate([sawtooth(120.0, 1.0), np.zeros(int(0.5 * SR)), sawtooth(220.0, 1.0, amplitude=0.15)])
        rows = dvm.measure_segments(signal, SR, [
            {"start": 0.0, "end": 1.0, "speaker": "A", "text": "must not leak"},
            {"start": 1.5, "end": 2.5, "speaker": "B", "emotion": "calm"},
            {"start": 1.0, "end": 1.5},
        ])
        self.assertEqual(len(rows), 3)
        self.assertLess(abs(rows[0]["f0_median_hz"] - 120.0) / 120.0, 0.05)
        self.assertLess(abs(rows[1]["f0_median_hz"] - 220.0) / 220.0, 0.05)
        self.assertIsNone(rows[2]["f0_median_hz"])
        self.assertIsNone(rows[2]["rms_dbfs"])
        self.assertGreater(rows[0]["rms_dbfs"], rows[1]["rms_dbfs"])
        self.assertEqual(rows[0]["speaker"], "A")
        self.assertEqual(rows[1]["emotion"], "calm")
        self.assertNotIn("text", rows[0])
        self.assertEqual(rows[0]["duration_s"], 1.0)

    def test_strip_text(self):
        rows = dvm.strip_text([{"start": 0, "end": 1, "text": "x"}, {"start": 1, "end": 2}])
        self.assertTrue(all("text" not in r for r in rows))


@unittest.skipIf(np is None, "numpy not installed")
class EburParsingTests(unittest.TestCase):
    def test_parse_float_rejects_nan(self):
        self.assertIsNone(dvm._parse_float("nan"))
        self.assertIsNone(dvm._parse_float("-inf"))
        self.assertEqual(dvm._parse_float("-16.0"), -16.0)

    def test_window_lufs_short_window_is_none_without_ffmpeg_call(self):
        # below 400 ms no ebur128 block exists; must not fabricate a number
        self.assertIsNone(dvm.measure_window_lufs(Path("does-not-exist.wav"), 0.0, 0.2))


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not available")
@unittest.skipIf(np is None, "numpy not installed")
class FfmpegRoundTripTests(unittest.TestCase):
    def setUp(self):
        import soundfile as sf

        self.tmp = tempfile.TemporaryDirectory(prefix="dvm_test_")
        self.wav = Path(self.tmp.name) / "tone.wav"
        signal = np.concatenate([sawtooth(120.0, 1.0), np.zeros(int(0.5 * SR)), sawtooth(220.0, 1.0)])
        sf.write(str(self.wav), signal.astype(np.float32), SR)

    def tearDown(self):
        self.tmp.cleanup()

    def test_window_lufs_is_measured_and_louder_window_is_louder(self):
        first = dvm.measure_window_lufs(self.wav, 0.0, 1.0)
        self.assertIsNotNone(first)
        self.assertGreater(first, -40.0)
        self.assertLess(first, 0.0)
        quiet = dvm.measure_window_lufs(self.wav, 1.0, 1.5)
        self.assertIsNone(quiet)  # digital silence: ebur128 reports below the -60 floor -> None

    def test_program_loudness_parses_integrated_and_true_peak(self):
        loud = dvm.measure_program_loudness(self.wav)
        self.assertIsNotNone(loud["integrated_lufs"])
        self.assertIsNotNone(loud["true_peak_dbtp"])
        self.assertLess(loud["true_peak_dbtp"], 0.0)

    def test_cli_writes_schema_without_text(self):
        segments = Path(self.tmp.name) / "segments.json"
        segments.write_text(json.dumps([{"start": 0.0, "end": 1.0, "text": "secret", "speaker": "A"},
                                        {"start": 1.5, "end": 2.5}]), encoding="utf-8")
        out = Path(self.tmp.name) / "metrics.json"
        rc = dvm.main(["--media", str(self.wav), "--segments-json", str(segments), "--out", str(out)])
        self.assertEqual(rc, 0)
        payload = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema"], dvm.SCHEMA)
        self.assertEqual(len(payload["media_sha256"]), 64)
        self.assertEqual(len(payload["segments"]), 2)
        self.assertNotIn("text", payload["segments"][0])
        self.assertEqual(payload["segments"][0]["speaker"], "A")
        self.assertLess(abs(payload["segments"][0]["f0_median_hz"] - 120.0) / 120.0, 0.05)
        self.assertLess(abs(payload["segments"][1]["f0_median_hz"] - 220.0) / 220.0, 0.05)
        self.assertIsNotNone(payload["segments"][0]["lufs_window"])


if __name__ == "__main__":
    unittest.main()
