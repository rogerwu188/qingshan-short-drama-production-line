"""The cover of a burned-text run reaches the text the scan read in that run (fleet 2026-11-14, E13 S7).

A device's E13 burned 「能难倒我？」 at y 0.884-0.927, under the E13 band y 0.66-0.81.  The scan found the run
(18.25-19.0 s) but the blur covered only the band, so the verify refused the episode on every re-run.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "lines/nalu/runtime/tools"))

import burned_text_cover as btc  # noqa: E402
import build_burnin_subtitles as bbs  # noqa: E402

CFG = btc.policy()
LOW = (18.5, "能难倒我？", 0.93, 0.312, 0.884, 0.65, 0.927)
IN_BAND = (3.0, "许叔去过吗", 0.9, 0.3, 0.70, 0.7, 0.74)


class IntervalBandTests(unittest.TestCase):
    def test_run_below_the_band_widens_only_its_own_cover(self):
        hits = [IN_BAND, LOW]
        intervals = btc.scan(hits, CFG)
        self.assertEqual(len(intervals), 2)
        bands = btc.interval_bands(hits, CFG, intervals, episode="E13")
        base = btc.band_for("E13", CFG)
        self.assertEqual(bands[0], base)                       # text inside the band: cover unchanged
        self.assertEqual(bands[1]["y0"], base["y0"])
        self.assertGreater(bands[1]["y1"], 0.927)              # reaches under the burned line
        self.assertLessEqual(bands[1]["y1"], 1.0)
        self.assertEqual((bands[1]["x0"], bands[1]["x1"]), (base["x0"], base["x1"]))

    def test_noise_and_text_outside_the_search_window_do_not_widen(self):
        hits = [IN_BAND, (3.0, "灯笼高挂", 0.9, 0.3, 0.02, 0.7, 0.08), (3.0, "许叔", 0.3, 0.0, 0.85, 1.0, 0.9)]
        bands = btc.interval_bands(hits, CFG, btc.scan(hits, CFG), episode="E13")
        self.assertEqual(bands, [btc.band_for("E13", CFG)])

    def test_verify_still_refuses_the_line_when_it_stays_readable(self):
        captions = [{"text": "哼！不就是小学奥数水平的几何题，能难倒我？", "start": 14.237, "end": 19.077}]
        out = btc.verify([LOW], captions, CFG, episode="E13")
        self.assertEqual(out["status"], "FAIL")
        self.assertEqual(btc.verify([], captions, CFG, episode="E13")["status"], "PASS")

    def test_scan_cli_writes_one_band_per_run_and_load_covered_reads_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "intervals.json"
            rc = btc.main(["scan", str(Path(tmp) / "x.mp4"), "--episode", "E13", "--out", str(out)],
                          ocr=lambda _video, _fps: [IN_BAND, LOW])
            self.assertEqual(rc, 0)
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(len(data["bands"]), len(data["intervals"]))
            covered = btc.load_covered(out)
            self.assertEqual([c[:2] for c in covered], [tuple(i) for i in data["intervals"]])
            data.pop("bands"); out.write_text(json.dumps(data), encoding="utf-8")
            self.assertEqual(btc.load_covered(out), [])        # a scan from an older engine: no bands
            self.assertEqual(btc.load_covered(None), [])


class CoverGeometryTests(unittest.TestCase):
    BASE = (845, 192, 43, 677)  # the E13 band on a 720x1280 frame

    def test_low_run_is_covered_down_to_the_text_and_others_keep_the_band(self):
        hits = [IN_BAND, LOW]
        intervals = btc.scan(hits, CFG)
        covered = [(s, e, b) for (s, e), b in zip(intervals, btc.interval_bands(hits, CFG, intervals, episode="E13"))]
        geometry = bbs.cover_geometries(covered, intervals, self.BASE, 720, 1280)
        self.assertEqual(geometry[0], self.BASE)
        y, h, x0, x1 = geometry[1]
        self.assertEqual((y, x0, x1), (845, 43, 677))
        self.assertGreaterEqual(y + h, int(0.927 * 1280) + 1)  # the burned line's lower edge is inside the cover
        self.assertLessEqual(y + h, 1280)

    def test_scan_without_bands_covers_the_band_as_before(self):
        self.assertEqual(bbs.cover_geometries([], [[1.0, 2.0], [3.0, 4.0]], self.BASE, 720, 1280),
                         [self.BASE, self.BASE])


if __name__ == "__main__":
    unittest.main()
