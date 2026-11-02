"""H3_BURNED_TEXT_COVER_V1: burned-text scan intervals and the post-burn verification (E12 2026-10-31)."""
from __future__ import annotations

import json
import pathlib
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
        self.assertFalse(btc.active({}, episode="E14"))
        self.assertTrue(btc.active({btc.FIELD: btc.POLICY_ID}, episode="E14"))
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

    def test_text_away_from_the_band_is_recorded_and_ignored(self):
        # line owner 2026-11-01: the bar hides the burned dialogue line; scene text far from the band is the
        # period/anachronism gate's business and must not fail the cover check
        # "许叔去过吗" is the caption this test's CAPTIONS carries at t=1.5, so use words that are NOT on screen
        out = btc.verify([hit(1.5, "冰老", y=(0.40, 0.44))], self.CAPTIONS, CFG)
        self.assertEqual(out["status"], "PASS")
        self.assertEqual(out["ignored_non_dialogue_text"][0]["reason"], "AWAY_FROM_BURN_BAND")

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


class VerifyScopeTests(unittest.TestCase):
    """E13 S7: a gate plaque away from the burn band is not the burned dialogue line the policy is about."""

    CAPTIONS = [{"text": "多谢邵兄好意", "start": 1.0, "end": 2.0}]

    def test_plaque_away_from_band_is_recorded_and_ignored(self):
        hits = [(1.2, "猿明", 0.9, 0.15, 0.01, 0.82, 0.14)]
        out = btc.verify(hits, self.CAPTIONS, CFG)
        self.assertEqual(out["status"], "PASS")
        self.assertEqual(out["ignored_non_dialogue_text"][0]["text"], "猿明")

    def test_text_near_the_band_outside_the_bar_still_fails(self):
        # near the band and NOT the caption on screen: a burned line the bar did not cover
        hits = [(1.2, "我们找冯易安", 0.9, 0.20, 0.84, 0.80, 0.90)]
        self.assertEqual(btc.verify(hits, self.CAPTIONS, CFG)["status"], "FAIL")

    def test_the_same_words_high_in_the_frame_are_a_burned_copy_not_our_caption(self):
        # The caption we draw sits on or at the band edge, never at y 0.02-0.10.  The same words up there are
        # the line H3 burned into the picture (knowledge-loop CASE_001 control: the rule must not hide it), so
        # they stay outside the bar and FAIL -- recorded as a hit, not silently ignored.
        hits = [(1.2, "多谢邵兄好意", 0.9, 0.20, 0.02, 0.80, 0.10)]
        out = btc.verify(hits, self.CAPTIONS, CFG)
        self.assertEqual(out["ignored_non_dialogue_text"][0]["reason"], "AWAY_FROM_BURN_BAND")
        # the same words within the band pad still count as a burned line and FAIL
        moved = [(1.2, "多谢邵兄好意", 0.9, 0.20, 0.58, 0.80, 0.64)]
        self.assertEqual(btc.verify(moved, self.CAPTIONS, CFG)["status"], "FAIL")


class CaptionPlateTests(unittest.TestCase):
    """E13 2026-11-01 viewing note: subtitles keep a transparent plate; only the burned-text bar is dark."""

    def test_bar_alpha_can_be_set_per_episode(self):
        policy = json.loads((pathlib.Path(__file__).resolve().parents[2]
                             / 'configs/H3_BURNED_TEXT_COVER_V1.json').read_text(encoding='utf-8'))
        self.assertIn('E13', policy['bar_rgba_by_episode'])
        self.assertLess(policy['bar_rgba_by_episode']['E13'][3], policy['bar_rgba'][3])

    def test_the_caption_plate_is_never_painted_dark(self):
        # The caption keeps its transparent plate (E13 note 「字幕底以前都是透明的」): nothing in the caption
        # block may paint a background.  It does sit INSIDE the cover band once a cover exists, so the burned
        # line is hidden under our one caption row instead of showing as a second row (E13「有两排字幕了」).
        source = (pathlib.Path(__file__).resolve().parents[2]
                  / 'lines/nalu/runtime/tools/build_burnin_subtitles.py').read_text(encoding='utf-8')
        caption_block = source[source.index('for i, (s_t, e_t, ln) in enumerate(events):'):
                               source.index('last = f"[v{len(events)}]"')]
        self.assertNotIn('cover["rgba"]', caption_block)
        self.assertIn('Image.new("RGBA", (W, LINE_H * len(rows) + 24), (0, 0, 0, 0))', caption_block)
        self.assertIn('if cover else H - MARGIN_BOTTOM - img.height', caption_block)


class CaptionOutsideBandTests(unittest.TestCase):
    """Our own transparent-plate caption sits just outside the band; it is not a burned line (E13 2026-11-01)."""

    CAPTIONS = [{"text": "或者年轻二十岁，", "start": 2.46, "end": 6.54}]

    def test_our_caption_just_below_the_band_is_ignored(self):
        hits = [(2.5, "或者年轻二十岁，", 0.98, 0.265, 0.813, 0.714, 0.848)]
        out = btc.verify(hits, self.CAPTIONS, CFG)
        self.assertEqual(out["status"], "PASS")
        self.assertEqual(out["ignored_non_dialogue_text"][0]["reason"], "CAPTION_ON_SCREEN")

    def test_a_burned_line_the_caption_does_not_match_still_fails(self):
        hits = [(2.5, "钱伯没撑过去", 0.98, 0.265, 0.813, 0.714, 0.848)]
        out = btc.verify(hits, self.CAPTIONS, CFG)
        self.assertEqual(out["status"], "FAIL")
