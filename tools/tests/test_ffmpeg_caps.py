import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ffmpeg_caps  # noqa: E402

NEW = "Filter alimiter\n  Audio lookahead limiter.\nalimiter AVOptions:\n   level_in          <double>\n   latency           <boolean>    ..F.A....T. compensate delay (default false)\n"
OLD = "Filter alimiter\n  Audio lookahead limiter.\nalimiter AVOptions:\n   level_in          <double>\n   asc_level         <double>\n"


class FfmpegCapsTest(unittest.TestCase):
    def setUp(self):
        ffmpeg_caps.filter_has_option.cache_clear()

    def _probe(self, text):
        return mock.patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 0, text, ""))

    def test_new_ffmpeg_keeps_latency(self):
        with self._probe(NEW):
            self.assertEqual(ffmpeg_caps.alimiter_latency("ff-new"), ":latency=1")

    def test_old_ffmpeg_drops_latency(self):
        """Device …1485: an ffmpeg whose alimiter has no latency option failed every S7 level step."""
        with self._probe(OLD):
            self.assertEqual(ffmpeg_caps.alimiter_latency("ff-old"), "")

    def test_unprobeable_ffmpeg_keeps_historical_argument(self):
        with mock.patch.object(subprocess, "run", side_effect=OSError("no ffmpeg")):
            self.assertEqual(ffmpeg_caps.alimiter_latency("ff-missing"), ":latency=1")


if __name__ == "__main__":
    unittest.main()
