"""H3_BURNED_TEXT_COVER_V1 tight cover (owner 2026-11-19, a published 《摄政王她又来找茬了》 episode, device 0841).

The cover used to be the whole burn band (E14: y 0.66-0.95, x 0.01-0.99): a blurred rectangle over the bottom ~30 %
of the frame, over the speaker's chest and the table, with our caption 「她有别的任务，先让你们长个记性。」 on top.
Now only the text OCR read is blurred, tightly, for its run; big boxes and faces are flagged, never blurred;
set-dressing text (embroidery, scrolls) is ignored; a single large burned glyph (「能」) is caught; our caption
moves clear of any blurred box.
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


def area(b):
    return (b["x1"] - b["x0"]) * (b["y1"] - b["y0"])


class TightBoxTests(unittest.TestCase):
    def test_box_is_the_text_plus_a_small_margin_not_the_band(self):
        hits = [IN_BAND, (3.25, "许叔去过吗", 0.9, 0.31, 0.701, 0.69, 0.741)]
        intervals = btc.scan(hits, CFG)
        boxes = btc.interval_boxes(hits, CFG, intervals)
        self.assertEqual(len(boxes), 1)
        (box,) = boxes[0]
        self.assertEqual(box["action"], "BLUR")
        m = CFG["cover"]["margin"]
        self.assertAlmostEqual(box["x0"], 0.3 - m, places=3)
        self.assertAlmostEqual(box["y1"], 0.741 + m, places=3)
        self.assertLess(area(box), 0.05)                     # the old E14 band was ~0.28 of the frame
        self.assertLess(area(box), CFG["cover"]["max_area_fraction"])

    def test_each_run_gets_its_own_box_only_for_its_own_time(self):
        hits = [IN_BAND, LOW]
        intervals = btc.scan(hits, CFG)
        self.assertEqual(len(intervals), 2)
        boxes = btc.interval_boxes(hits, CFG, intervals)
        self.assertGreater(boxes[1][0]["y0"], 0.86)          # the low line is covered where it is ...
        self.assertLess(boxes[0][0]["y1"], 0.76)             # ... and the other run keeps its own box
        covered = list(zip([i[0] for i in intervals], [i[1] for i in intervals], boxes))
        px = bbs.blur_boxes_px(covered, 720, 1280)
        self.assertEqual([(s, e) for s, e, _ in px], [tuple(i) for i in intervals])
        for _s, _e, (x, y, w, h) in px:
            self.assertTrue(x % 2 == 0 and y % 2 == 0 and w % 2 == 0 and h % 2 == 0)
            self.assertLess(w * h, 0.12 * 720 * 1280)

    def test_text_in_two_places_stays_two_boxes(self):
        hits = [IN_BAND, (3.0, "这是另一行字", 0.9, 0.35, 0.86, 0.65, 0.89)]
        boxes = btc.interval_boxes(hits, CFG, btc.scan(hits, CFG))
        self.assertEqual(len(boxes[0]), 2)

    def test_box_over_the_area_cap_is_flagged_not_blurred(self):
        big = (5.0, "画面上的超大字幕文字", 0.95, 0.05, 0.56, 0.95, 0.80)   # 0.9 x 0.24 = 0.216 of the frame
        boxes = btc.interval_boxes([big], CFG, btc.scan([big], CFG))
        self.assertEqual(boxes[0][0]["action"], "SKIP")
        self.assertEqual(boxes[0][0]["reason"], "AREA_OVER_CAP")
        self.assertEqual(bbs.blur_boxes_px([(4.75, 5.5, boxes[0])], 720, 1280), [])

    def test_box_touching_a_face_is_flagged_not_blurred(self):
        hits = [IN_BAND]
        intervals = btc.scan(hits, CFG)
        face = {3.0: [(0.35, 0.45, 0.65, 0.71)]}             # a chin reaching into the text box
        boxes = btc.interval_boxes(hits, CFG, intervals, faces=face)
        self.assertEqual((boxes[0][0]["action"], boxes[0][0]["reason"]), ("SKIP", "OVERLAPS_FACE"))
        far = {3.0: [(0.35, 0.20, 0.65, 0.50)]}
        self.assertEqual(btc.interval_boxes(hits, CFG, intervals, faces=far)[0][0]["action"], "BLUR")
        other_time = {9.0: [(0.35, 0.45, 0.65, 0.71)]}       # a face in another run does not matter
        self.assertEqual(btc.interval_boxes(hits, CFG, intervals, faces=other_time)[0][0]["action"], "BLUR")


class FalsePositiveTests(unittest.TestCase):
    def test_small_vertical_or_off_centre_text_is_not_a_burned_line(self):
        embroidery = (3.0, "福寿安康", 0.9, 0.42, 0.70, 0.52, 0.712)    # glyphs 1.2 % of frame height
        scroll = (3.0, "山高水长", 0.9, 0.80, 0.56, 0.84, 0.86)         # a vertical column, at the side
        side = (3.0, "某某商号", 0.9, 0.02, 0.70, 0.30, 0.74)          # far off-centre signage
        low_conf = (3.0, "许叔去过吗", 0.4, 0.3, 0.70, 0.7, 0.74)
        for h in (embroidery, scroll, side, low_conf):
            self.assertEqual(btc.scan([h], CFG), [], h)
        self.assertEqual(btc.verify([embroidery, scroll, side], [], CFG)["status"], "PASS")

    def test_a_single_large_glyph_of_the_dialogue_is_caught(self):
        # owner 2026-11-19: H3 rendered a big white 「能」 under our caption 「能，你直接进去就好了。」
        neng = (7.0, "能", 0.92, 0.45, 0.86, 0.55, 0.92)
        chars = set("能你直接进去就好了")
        self.assertEqual(len(btc.scan([neng], CFG, chars)), 1)
        self.assertEqual(btc.interval_boxes([neng], CFG, btc.scan([neng], CFG, chars), chars)[0][0]["action"], "BLUR")
        self.assertEqual(btc.scan([neng], CFG, set("别的字")), [])                       # not a dialogue character
        self.assertEqual(btc.scan([(7.0, "能", 0.92, 0.48, 0.86, 0.52, 0.885)], CFG, chars), [])  # small glyph

    def test_contract_dialogue_chars(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = Path(tmp) / "c.json"
            c.write_text(json.dumps({"audio_contract": {"dialogue_units": [{"text": "能，你直接进去就好了。"}]}},
                                    ensure_ascii=False), encoding="utf-8")
            self.assertIn("能", btc.contract_dialogue_chars(c))
            self.assertIsNone(btc.contract_dialogue_chars(None))


class ScanCliTests(unittest.TestCase):
    def test_scan_cli_writes_boxes_and_flags_and_load_covered_reads_them(self):
        big = (9.0, "画面上的超大字幕文字", 0.95, 0.05, 0.56, 0.95, 0.80)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "intervals.json"
            calls = []
            rc = btc.main(["scan", str(Path(tmp) / "x.mp4"), "--episode", "E13", "--out", str(out)],
                          ocr=lambda _v, _f: [IN_BAND, LOW, big],
                          faces=lambda _v, times: calls.append(times) or {})
            self.assertEqual(rc, 0)
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(len(data["boxes"]), len(data["intervals"]))
            self.assertEqual([f["reason"] for f in data["flagged_for_review"]], ["AREA_OVER_CAP"])
            self.assertTrue(calls and calls[0])                  # faces measured for the runs that would blur
            covered = btc.load_covered(out)
            self.assertEqual([c[:2] for c in covered], [tuple(i) for i in data["intervals"]])
            data.pop("boxes"); out.write_text(json.dumps(data), encoding="utf-8")
            self.assertEqual(btc.load_covered(out), [])          # an older whole-band scan is never replayed

    def test_verify_reports_text_in_a_flagged_box_without_failing(self):
        big = (9.0, "画面上的超大字幕文字", 0.95, 0.05, 0.56, 0.95, 0.80)
        intervals = btc.scan([big], CFG)
        covered = [(s, e, b) for (s, e), b in zip(intervals, btc.interval_boxes([big], CFG, intervals))]
        out = btc.verify([big], [], CFG, covered=covered)
        self.assertEqual(out["status"], "PASS")
        self.assertEqual(len(out["flagged_for_review"]), 1)
        self.assertEqual(btc.verify([big], [], CFG)["status"], "FAIL")   # without the scan it is still a hit

    def test_verify_still_refuses_the_line_when_it_stays_readable(self):
        captions = [{"text": "哼！不就是小学奥数水平的几何题，能难倒我？", "start": 14.237, "end": 19.077}]
        self.assertEqual(btc.verify([LOW], captions, CFG, episode="E13")["status"], "FAIL")


class CaptionPlacementTests(unittest.TestCase):
    H = 1280

    def test_caption_without_a_blur_keeps_its_place(self):
        self.assertEqual(bbs.caption_y(1000, 110, (100, 620), 1.0, 2.0, [], self.H), 1000)

    def test_caption_never_sits_on_a_blurred_box(self):
        blur = [(1.0, 3.0, (200, 990, 320, 60))]              # burned line at y 990-1050, our caption at 1000
        y = bbs.caption_y(1000, 110, (100, 620), 1.5, 2.5, blur, self.H)
        self.assertTrue(y >= 1050 or y + 110 <= 990, y)
        # the same box on screen at another time does not move the caption
        self.assertEqual(bbs.caption_y(1000, 110, (100, 620), 4.0, 5.0, blur, self.H), 1000)

    def test_caption_goes_above_when_there_is_no_room_below(self):
        blur = [(1.0, 3.0, (200, 1080, 320, 120))]
        y = bbs.caption_y(1000, 110, (100, 620), 1.5, 2.5, blur, self.H)
        self.assertLessEqual(y + 110, 1080)

    def test_verify_accepts_our_caption_where_it_was_drawn(self):
        # moved above a blurred box: y 0.60-0.66, outside the E13 band, still our caption
        captions = [{"text": "能，你直接进去就好了。", "start": 6.0, "end": 8.0, "y0": 0.60, "y1": 0.66}]
        hit = (7.0, "能，你直接进去就好了。", 0.95, 0.25, 0.605, 0.75, 0.655)
        self.assertEqual(btc.verify([hit], captions, CFG, episode="E13")["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
