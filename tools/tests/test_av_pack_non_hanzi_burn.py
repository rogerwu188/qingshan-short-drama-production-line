"""Final-review evidence pack: burned text in any script (deep review 1485 E09, 2026-11-23).

H3 burned the romanised line 「SeinMa, Ee miyte!」 into the caption band of a Japanese episode, right on top of our
caption 「セイン様、目を開けて！」.  The pack counted hanzi only and took every caption-sized read in the caption band
as ours, so neither the local OCR suspects nor the final review saw it.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lines/nalu/runtime/tools"))

import av_evidence_pack as ap  # noqa: E402

BAND = (0.19, 0.80, 0.80, 0.84)        # caption band, caption-sized glyphs (h 0.04)
CAPTIONS = [{"start": 61.9, "end": 64.4, "rows": ["セイン様、目を開けて！"], "text": "セイン様、目を開けて！"},
            {"start": 64.4, "end": 68.4, "rows": ["ナー帝国の毒だ。", "心臓へ回る前に止める。"],
             "text": "ナー帝国の毒だ。心臓へ回る前に止める。"}]


class NonHanziBurnTests(unittest.TestCase):
    def setUp(self):
        self.at = ap.caption_lookup(CAPTIONS)

    def classify(self, t, text, score=0.93, geom=BAND):
        return ap.classify_box(t, text, score, geom, 124.7, self.at)

    def test_romanised_line_over_our_caption_is_burned(self):
        self.assertEqual(self.classify(62.0, "SeinMa, Ee miyte!"), "BURNED")

    def test_our_caption_and_its_misreads_stay_ours(self):
        self.assertEqual(self.classify(62.5, "セイン様、目を開けて！"), "OURS")
        self.assertEqual(self.classify(63.0, "セイン線目を開けぞ！"), "OURS")       # misread of our caption
        self.assertEqual(self.classify(64.6, "心臓へ回る前に止める。"), "OURS")
        self.assertEqual(self.classify(64.3, "ナー帝国の毒だ。"), "OURS")          # next cue within the slack

    def test_caption_band_text_with_no_caption_on_screen_is_burned(self):
        self.assertEqual(self.classify(70.0, "レイちゃん、逃げて"), "BURNED")

    def test_kana_and_hangul_count_as_glyphs(self):
        big = (0.2, 0.40, 0.8, 0.46)     # big glyphs mid-frame
        self.assertEqual(ap.classify_box(30.0, "いやだよ", 0.9, big, 124.7), "BURNED")
        self.assertEqual(ap.classify_box(30.0, "안녕하세요", 0.9, big, 124.7), "BURNED")
        self.assertEqual(ap.classify_box(30.0, "Ok", 0.9, big, 124.7), "LOW_CONFIDENCE")   # 2 Latin letters
        self.assertEqual(ap.classify_box(30.0, "Hello there", 0.65, big, 124.7), "LOW_CONFIDENCE")

    def test_without_captions_the_band_is_ours_as_before(self):
        self.assertEqual(ap.classify_box(62.0, "SeinMa, Ee miyte!", 0.93, BAND, 124.7, None), "OURS")
        self.assertIsNone(ap.caption_lookup([]))

    def test_latin_caption_lines_are_not_foreign(self):
        self.assertFalse(ap.foreign_to_caption("I will stop it", "I will stop it here."))
        self.assertTrue(ap.foreign_to_caption("Sein, open your eyes", "セイン様、目を開けて！"))

    def test_caption_language(self):
        self.assertEqual(ap.caption_language("セイン様、目を開けて！"), "ja")
        self.assertEqual(ap.caption_language("눈을 떠"), "ko")
        self.assertEqual(ap.caption_language("睁开眼睛"), "zh")


if __name__ == "__main__":
    unittest.main()
