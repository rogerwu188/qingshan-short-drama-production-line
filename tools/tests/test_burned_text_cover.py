"""H3_BURNED_TEXT_COVER_V1: burned-text scan intervals and the post-burn verification (E12 2026-10-31)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import burned_text_cover as btc  # noqa: E402

CFG = btc.policy()


def hit(t, text, *, conf=0.9, y=(0.70, 0.74), x=(0.3, 0.7)):
    return (t, text, conf, x[0], y[0], x[1], y[1])


class PolicyTests(unittest.TestCase):
    def test_e12_listed_and_contract_declaration_wins(self):
        self.assertTrue(btc.active({}, episode="E12"))
        self.assertFalse(btc.active({}, episode="E13"))
        self.assertTrue(btc.active({btc.FIELD: btc.POLICY_ID}, episode="E13"))
        self.assertFalse(btc.active({btc.FIELD: "NONE"}, episode="E12"))

    def test_band_covers_every_measured_e12_burn(self):
        band = CFG["band"]
        for y0, y1, x0, x1 in ((0.67, 0.71, 0.29, 0.71), (0.76, 0.80, 0.35, 0.64), (0.71, 0.75, 0.09, 0.91)):
            self.assertTrue(band["y0"] <= y0 and y1 <= band["y1"] and band["x0"] <= x0 and x1 <= band["x1"])


class ScanTests(unittest.TestCase):
    def test_runs_are_merged_padded_and_filtered(self):
        hits = [hit(1.0, "许叔去过吗"), hit(1.25, "许叔去过吗"), hit(1.5, "许叔去过吗"),
                hit(3.0, "我们找冯易安"),
                hit(5.0, "000", conf=0.9),                      # numeric texture noise
                hit(6.0, "许叔", conf=0.4),                     # low confidence
                hit(7.0, "灯笼", y=(0.05, 0.10))]              # outside the search band
        self.assertEqual(btc.scan(hits, CFG), [[0.75, 2.0], [2.75, 3.5]])

    def test_gap_under_half_a_second_joins(self):
        self.assertEqual(btc.merge_intervals([1.0, 1.5], step=0.25, gap=0.5, pad=0.0), [[1.0, 1.75]])
        self.assertEqual(len(btc.merge_intervals([1.0, 2.0], step=0.25, gap=0.5, pad=0.0)), 2)


class VerifyTests(unittest.TestCase):
    CAPTIONS = [{"text": "许叔去过吗？", "start": 1.0, "end": 2.0}]

    def test_caption_on_the_bar_passes(self):
        out = btc.verify([hit(1.5, "许叔去过吗")], self.CAPTIONS, CFG)
        self.assertEqual(out["status"], "PASS")

    def test_text_outside_the_bar_fails(self):
        out = btc.verify([hit(1.5, "许叔去过吗", y=(0.40, 0.44))], self.CAPTIONS, CFG)
        self.assertEqual(out["status"], "FAIL")
        self.assertEqual(len(out["text_outside_bar"]), 1)

    def test_burned_line_bleeding_through_where_no_caption_is_shown_fails(self):
        out = btc.verify([hit(3.0, "我们找冯易安")], self.CAPTIONS, CFG)
        self.assertEqual(out["status"], "FAIL")
        self.assertEqual(out["text_inside_bar_not_the_caption"][0]["caption_on_screen"], "")

    def test_caption_changing_within_half_a_sampling_step_passes(self):
        caps = [{"text": "算了，等我们赶到后", "start": 4.86, "end": 9.54},
                {"text": "不要说深山大泽，", "start": 9.54, "end": 11.06}]
        self.assertEqual(btc.verify([hit(9.5, "不要说深山大泽")], caps, CFG)["status"], "PASS")
        self.assertEqual(btc.verify([hit(9.0, "不要说深山大泽")], caps, CFG)["status"], "FAIL")

    def test_second_line_of_a_two_line_caption_passes(self):
        caps = [{"text": "去过那里，被震撼了，逐渐认清现实，", "start": 19.18, "end": 23.08}]
        self.assertEqual(btc.verify([hit(19.0, "逐渐认清现实")], caps, CFG)["status"], "PASS")

    def test_cli_writes_receipts_with_injected_ocr(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            rep = tmp / "subs.json"; rep.write_text(json.dumps({"rows": self.CAPTIONS}))
            rc = btc.main(["verify", str(tmp / "v.mp4"), "--captions", str(rep), "--out", str(tmp / "c.json")],
                          ocr=lambda video, fps: [hit(1.5, "许叔去过吗")])
            self.assertEqual(rc, 0)
            self.assertEqual(json.loads((tmp / "c.json").read_text())["status"], "PASS")
            rc = btc.main(["scan", str(tmp / "v.mp4"), "--out", str(tmp / "i.json")],
                          ocr=lambda video, fps: [hit(1.0, "许叔去过吗")])
            self.assertEqual(rc, 0)
            self.assertEqual(json.loads((tmp / "i.json").read_text())["intervals"], [[0.75, 1.5]])


if __name__ == "__main__":
    unittest.main()
