"""Subtitle line breaking (owner 2026-11-19): 「我和我姐姐差点被你的同伴对付了」 / 「！」 left the mark alone on row 2."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lines/nalu/runtime/tools"))

import build_burnin_subtitles as bbs  # noqa: E402

LINES = ["我和我姐姐差点被你的同伴对付了！", "她有别的任务，先让你们长个记性。", "能，你直接进去就好了。",
         "看着就是家里横惯了的二世祖，打架经验哪里及得上矿区混的老手鹿竹。", "「你说什么」他问道我不知道你在说什么啊",
         "这些小孩看着……就是家里横惯了的二世祖", "啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊！！", "一二三四五六七八九十一二三四五六",
         "おまえはもう死んでいる。なにっ！？そんなばかな！", "（冷笑）你以为你是谁啊，竟敢在这里撒野？"]


def rows(text):
    return bbs.wrap(text).split("\\N")


class KinsokuWrapTests(unittest.TestCase):
    def test_the_reported_line_does_not_orphan_its_punctuation(self):
        out = rows("我和我姐姐差点被你的同伴对付了！")
        self.assertEqual(len(out), 2)
        self.assertNotEqual(out[-1], "！")
        self.assertLessEqual(abs(len(out[0]) - len(out[1])), 1)          # balanced

    def test_rules_hold_for_every_row(self):
        for text in LINES:
            out = rows(text)
            self.assertEqual("".join(out), text)
            for i, row in enumerate(out):
                self.assertGreater(len(row), 1, (text, out))                  # never a one-character row
                self.assertLessEqual(len(row), 16, (text, out))
                if i > 0:
                    self.assertNotIn(row[0], bbs.NO_LINE_START, (text, out))  # no row starts with closing punct
                if i < len(out) - 1:
                    self.assertNotIn(row[-1], bbs.NO_LINE_END, (text, out))   # no row ends with an opening bracket

    def test_short_lines_unchanged(self):
        self.assertEqual(bbs.wrap("能，你直接进去就好了。"), "能，你直接进去就好了。")

    def test_english_and_korean_never_leave_a_lone_mark(self):
        out = bbs.wrap_en("I cannot believe you really did that to me !").split("\\N")
        self.assertTrue(all(len(r.replace(" ", "")) > 1 for r in out), out)
        self.assertNotIn(out[-1][:1], bbs.NO_LINE_START)
        ko = bbs.wrap_ko("이제야 왔구나 기다렸어 정말 오래 기다렸어 !").split("\\N")
        self.assertTrue(all(len(r.replace(" ", "")) > 1 for r in ko), ko)

    def test_cue_splitter_never_starts_a_cue_with_closing_punctuation(self):
        text = "我和我姐姐差点被你的同伴对付了！你们到底想怎么样？还不快给我滚出去！"
        cues = bbs.split_cues(text, lambda c: len(bbs.wrap(c).split("\\N")) <= 1, "zh")
        self.assertEqual("".join(cues), text)
        for c in cues[1:]:
            self.assertNotIn(c[0], bbs.NO_LINE_START, cues)
        self.assertTrue(all(len(c) > 1 for c in cues), cues)


if __name__ == "__main__":
    unittest.main()


class JapanesePhraseWrapTests(unittest.TestCase):
    """Deep review 1485 E09 (2026-11-23): the zh character wrap split 変えられる and hung の on row 2."""

    def test_e09_lines_break_at_phrase_boundaries(self):
        self.assertEqual(bbs.wrap_ja("一人で結末を変えられると思い上がった。"), "一人で結末を変えられると\\N思い上がった。")
        self.assertEqual(bbs.wrap_ja("褒美を、オルソー家の生路に変えますわ。"), "褒美を、オルソー家の\\N生路に変えますわ。")

    def test_kinsoku_and_width_still_hold(self):
        for text in LINES + ["一人で結末を変えられると思い上がった。", "放逐の日は、三日後に決まりました。"]:
            out = bbs.wrap_ja(text).split("\\N")
            self.assertEqual("".join(out), text)
            for i, row in enumerate(out):
                self.assertGreater(len(row), 1, out)
                self.assertLessEqual(len(row), 16, out)
                if i:
                    self.assertNotIn(row[0], bbs.NO_LINE_START, out)

    def test_break_costs(self):
        text = "一人で結末を変えられると"
        self.assertLess(bbs.ja_break_cost(text, 3), 0)       # で｜結
        self.assertGreater(bbs.ja_break_cost(text, 4), 0)    # 結｜末
        self.assertGreater(bbs.ja_break_cost(text, 8), 0)    # 変え｜ら... hiragana run
        self.assertGreater(bbs.ja_break_cost("家の", 1), 0)  # kanji stem | particle

    def test_zh_wrap_unchanged(self):
        self.assertEqual(bbs.wrap("我和我姐姐差点被你的同伴对付了！"), bbs.wrap("我和我姐姐差点被你的同伴对付了！", 15, "zh"))

    def test_ja_cue_split_prefers_phrase_boundary(self):
        text = "一人で結末を変えられると思い上がった。それでも私は、あなたを守りたかった。"
        cues = bbs.split_cues(text, lambda c: len(bbs.wrap_ja(c).split("\\N")) <= 1, "ja")
        self.assertEqual("".join(cues), text)
        for c in cues[1:]:
            self.assertNotIn(c[0], bbs.NO_LINE_START, cues)
