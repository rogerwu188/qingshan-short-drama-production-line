"""CAMERA_GRAMMAR_V1 DIRECTOR_PROMPT_V2 dialogue Delivery (owner 2026-11-04, lab 化神 E04 "语音声调起伏不够大，没有感情").

Delivery leads with the emotion and the writer's contour; anti-error meta (once / immediately / timbre / do not
echo the reference) and the generic "Natural breathing ... never a flat read" tail are not rendered, and a redo
note is said once per prompt after the dialogue.
"""

from __future__ import annotations

import unittest

from tools import h3_provider_prompt_renderer as h3v1
from tools.h3_director_prompt_v2 import stamped_delivery
from tools.h3_provider_prompt_renderer import render_h3_prompt
from tools.tests.test_h3_director_prompt_v2 import fixture

E04_REDO = ("Say the authored line immediately at the start, once, dry and matter-of-fact. The previous take added "
            "unwanted introductory speech; this take has no introductory words, no invented syllables, no extra words.")
E04_TEMPLATE = "Begin urgently, lift pitch on the warning, then drop the final phrase; preserve the same voice timbre."
BOILERPLATE = "Natural breathing, clear rises and falls, never a flat read."


def render_with(performance: dict | None, **kwargs) -> str:
    unit, plan = fixture(**kwargs)
    plan["beats"][0]["dialogue_delivery"] = {"chinese_characters_per_second": 4.5}
    if performance is not None:
        unit["ordered_prompt_specs"][0].setdefault("action", {})["performance"] = performance
    return render_h3_prompt(unit, plan)[0]


def delivery_line(text: str) -> str:
    return next(line for line in text.splitlines() if line.startswith("Delivery"))


class StampedDeliveryTest(unittest.TestCase):
    def test_emotion_leads_and_the_contour_follows(self):
        perf = {"emotion": "怒", "delivery_en": "voice climbing on 'clean house' and slamming the last word; a beat "
                                                "of silence before"}
        self.assertEqual(stamped_delivery(perf), (
            "Delivery: Angry — voice climbing on 'clean house' and slamming the last word, a beat of silence "
            "before.", []))

    def test_anti_error_meta_is_dropped_and_the_redo_note_split_out(self):
        delivery, redo = stamped_delivery({"emotion": "倦", "delivery_en": E04_REDO})
        self.assertEqual(delivery, "Delivery: Weary — dry and matter-of-fact.")
        self.assertEqual(redo, ["The previous take added unwanted introductory speech."])
        delivery, _ = stamped_delivery({"emotion": "怒", "delivery_en": E04_TEMPLATE})
        self.assertEqual(delivery, "Delivery: Angry — begin urgently, lift pitch on the warning, then drop the "
                                   "final phrase.")
        delivery, _ = stamped_delivery({"emotion": "冷", "delivery_en": (
            "Speak the short question once, starting immediately; do not quote or echo the voice-reference sample. "
            "Keep his firm low timbre, stress the final word with a frustrated upward inflection.")})
        self.assertEqual(delivery, "Delivery: Cold — stress the final word with a frustrated upward inflection.")

    def test_emotion_already_in_the_contour_is_not_repeated(self):
        delivery, _ = stamped_delivery({"emotion": "厌", "delivery_en": "cold and contemptuous, low and clipped"})
        self.assertEqual(delivery, "Delivery: Cold and contemptuous, low and clipped.")

    def test_emotion_only_and_nothing(self):
        self.assertEqual(stamped_delivery({"emotion": "怒"})[0], "Delivery: Angry, the pitch and volume rising and "
                                                                  "falling with the meaning, the key word stressed.")
        self.assertEqual(stamped_delivery({"emotion": "focused"}), ("", []))
        self.assertEqual(stamped_delivery({"emotion": "focused", "delivery_en": "愤怒"}), ("", []))
        self.assertEqual(stamped_delivery(None), ("", []))

    def test_long_contour_is_cut_on_a_clause_boundary(self):
        long = ", ".join(f"then rise sharply on word {n}" for n in range(1, 20))
        delivery, _ = stamped_delivery({"delivery_en": long})
        self.assertLess(len(delivery), 270)
        self.assertTrue(delivery.endswith(("word 8.", "word 9.")), delivery)


class StampedPromptTest(unittest.TestCase):
    def test_prompt_delivery_has_no_boilerplate_and_one_redo_note(self):
        text = render_with({"emotion": "倦", "delivery_en": E04_REDO})
        self.assertEqual(delivery_line(text), "Delivery: Weary — dry and matter-of-fact.")
        self.assertNotIn(BOILERPLATE, text)
        self.assertNotIn("immediately", text)
        self.assertEqual(text.count("The previous take added unwanted introductory speech."), 1)
        self.assertLess(text.index(h3v1.ONLY_THIS_LINE), text.index("The previous take added unwanted"))
        self.assertLess(text.index("The previous take added unwanted"), text.index("\n\nSound: "))

    def test_without_performance_the_canned_clause_stays(self):
        self.assertTrue(delivery_line(render_with(None)).startswith(
            "Delivery: clear, connected, naturally brisk speech"))

    def test_unstamped_v2_keeps_the_previous_wording(self):
        text = render_with({"emotion": "怒", "delivery_en": E04_TEMPLATE}, director=False)
        self.assertIn("Delivery: " + E04_TEMPLATE.rstrip(".") + ". " + BOILERPLATE, text)


if __name__ == "__main__":
    unittest.main()
