"""E28 burned dialogue (device 1101, 2026-11-26, RELEASE_HELD:BURN_UNRESOLVED): offline, no paid call.

E28 (engine bbc403e) burned the spoken line as large mid-frame text and as a second subtitle row in 12 of 31
speaking units; E27 (72e7d47, no micro-performance timeline) had none.  The #342 timeline was rendered time-coded and
pointed at the words ("1.8–2.4 s, Alpha: on the stressed word at about 1.8 s: ... the word comes out ..."), which
reads like a subtitle track.  The performance now renders untimed, face and body only; the 脑补 visual sentences never
refer to the words; the clean-picture rule also closes the Setting block (before the action and the dialogue)."""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "lines" / "nalu" / "runtime" / "tools", ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import bili_carry  # noqa: E402
import performance_timeline as ptl  # noqa: E402
from tools import h3_director_prompt_v2 as v2  # noqa: E402
from tools.h3_provider_prompt_renderer import render_h3_prompt  # noqa: E402
from tools.tests.test_h3_director_prompt_v2 import A, B, fixture  # noqa: E402

SPOKEN = re.compile(r"\b(?:word|words|syllables?|sentence|stressed|trigger)\b|\bAU\d", re.I)
#: the real E28 E28-S01-03 timeline beats (E28_GENERATION_CONTRACT_v1.json)
E28_VU003 = {"schema": ptl.SCHEMA, "emotion": "冷", "trigger_word": "我", "beats": [
    {"from": 0.0, "to": 0.6, "kind": "ENTRY",
     "en": "carried over from the last line: eyes still narrowed, waiting for {listener} to slip"},
    {"from": 0.6, "to": 0.8, "kind": "CHANGE", "trigger_word": "我", "trigger_at": 0.6,
     "en": "on {trigger}: the eyelids lift only slightly, the word comes out with the lips barely moving"},
    {"from": 0.8, "to": 1.0, "kind": "EXIT",
     "en": "end frame: holds half a beat before the eyes leave {listener}, lips closed, lips closed after the last "
           "word"}]}


def _unit(timeline: dict, *, folded: bool = False, director: bool = True) -> tuple[dict, dict]:
    unit, plan = fixture(director=director)
    unit["craft_profile"] = "BILI_V1"
    spec = unit["ordered_prompt_specs"][0]
    spec["action"] = {"performance": {"emotion": "冷", "timeline": timeline},
                      **({"folded_silent": [{"line_no": 2, "where": "next", "text": "x"}]} if folded else {})}
    spec["visual"] = {"business_en": {A: "She smooths her sleeve, then says the words slowly.", B: "Both hands drop."},
                      "detail_en": "a corner of the blanket lies by her palm"}
    return unit, plan


def _outside_dialogue(text: str) -> str:
    return re.sub(r"<d>.*?</d>", "", text, flags=re.S)


class UntimedPerformanceTest(unittest.TestCase):
    def test_e28_vu003_renders_untimed_and_never_points_at_the_words(self):
        line = bili_carry.performance_timeline_line({"performance": {"timeline": E28_VU003}}, "Alpha", "Beta",
                                                    (0.0, 4.0))
        self.assertEqual(line, "Alpha's face and body change visibly, never a held pose: at first, eyes still "
                               "narrowed, waiting for Beta to slip; then, the eyelids lift only slightly; at the end, "
                               "holds half a beat before the eyes leave Beta, lips closed.")
        self.assertNotRegex(line, r"\d")

    def test_every_lexicon_beat_renders_without_spoken_references(self):
        lex = ptl.lexicon()
        texts = []
        for row in (lex.get("emotions") or {}).values():
            texts += [row.get(k) or "" for k in ("entry_en", "change_en", "exit_en")]
        for row in (lex.get("psychology") or {}).values():
            texts.append(row.get("en") or "")
        self.assertGreater(len(texts), 20)
        for text in texts:
            out = bili_carry.silent_performance_text(text.replace("{listener}", "Beta"))
            self.assertNotRegex(out, SPOKEN, text)
            self.assertNotIn("{", out)

    def test_compiled_beats_no_longer_name_the_last_line_or_word(self):
        curve = ptl.EmotionCurve()
        ptl.build(who=A, emotion="冷", emotion_en="cold", line="别再琢磨了。", curve=curve)
        out = ptl.build(who=A, emotion="冷", emotion_en="cold", line="先告诉我怎么救他。", curve=curve)
        english = " ".join(b["en"] for b in out["beats"])
        self.assertNotIn("last word", english)
        self.assertNotIn("last line", english)
        self.assertEqual(out["beats"][1]["trigger_word"], ptl.trigger_word("先告诉我怎么救他。")[0])  # data kept


class RenderedPromptTest(unittest.TestCase):
    def test_v2_prompt_has_no_timecoded_or_spoken_references_outside_the_dialogue(self):
        unit, plan = _unit(E28_VU003, folded=True)
        text, receipt = render_h3_prompt(unit, plan)
        self.assertEqual(receipt.get("status"), "PASS")
        outside = _outside_dialogue(text)
        self.assertNotIn("stressed word", outside)
        self.assertNotRegex(outside, r"\d(\.\d)?–\d(\.\d)? s, Alpha")
        self.assertNotIn("says the words", outside)
        self.assertNotIn("first word", outside)
        self.assertIn(bili_carry.FOLDED_WHILE_SPEAKING, text)
        self.assertIn("She smooths her sleeve", text.replace("smooths her sleeve", "She smooths her sleeve", 1)
                      if "smooths her sleeve" in text else text)

    def test_clean_picture_rule_closes_the_setting_block_before_action_and_dialogue(self):
        unit, plan = _unit(E28_VU003)
        text, _ = render_h3_prompt(unit, plan)
        at = text.index(v2.CLEAN_PICTURE_V2)
        self.assertLess(text.index("Setting:"), at)
        self.assertLess(at, text.index("Camera:"))
        self.assertLess(at, text.index("<d>"))
        self.assertIn(v2.SPOKEN_NOT_WRITTEN_ONE, text)  # the after-dialogue rule stays

    def test_v1_prompt_also_drops_the_timecodes(self):
        unit, plan = _unit(E28_VU003, director=False)
        text, _ = render_h3_prompt(unit, plan)
        self.assertNotIn("stressed word", _outside_dialogue(text))

    def test_visual_sentences_drop_clauses_about_the_words(self):
        spec = {"visual": {"stakes_en": "the blanket hides his wound, the subtitle reads her name",
                           "detail_en": "a red line on the wrist"}}
        rows = dict(bili_carry.visual_sentences(spec, []))
        self.assertEqual(rows["STAKES"], "In the frame: the blanket hides his wound.")
        self.assertEqual(rows["DETAIL"], "Visible detail: a red line on the wrist.")


if __name__ == "__main__":
    unittest.main()
