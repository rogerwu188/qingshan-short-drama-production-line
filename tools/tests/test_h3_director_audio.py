"""CAMERA_GRAMMAR_V1 audio hygiene for H3 (lab Holmes E01 unit ASR, synthetic fixture).

Reference-sample words echoed into other units, babble after a short line in a long slot and H3-baked
music between shots.  Unstamped units stay byte-identical (pinned in test_h3_director_performance).
"""

from __future__ import annotations

import unittest

from tools.h3_provider_prompt_renderer import render_h3_prompt
from tools.tests.test_h3_director_performance import unit_plan
from tools.tests.test_h3_director_prompt import vu012

TIMBRE = "Each @Audio reference supplies timbre only; never speak or echo its words"
SILENT = ("After the tagged line ends nobody speaks again: the remaining seconds are silent room tone "
          "and natural movement, no mumbling, no extra words.")
MUSIC = "No background music, score or soundtrack in this clip; only dialogue, foley and ambience"


def line(text: str, prefix: str) -> str:
    return next(row for row in text.splitlines() if row.startswith(prefix))


class DirectorAudioTest(unittest.TestCase):
    def test_stamped_dialogue_unit_gets_timbre_only_silence_and_no_music(self):
        text, _ = render_h3_prompt(*unit_plan(stamped=True, performance=None))
        self.assertIn(TIMBRE, line(text, "voice_binding: "))
        self.assertIn("exclusive voice @Audio1", line(text, "voice_binding: "))
        self.assertTrue(line(text, "vocal_rule: ").endswith(SILENT))
        self.assertIn(MUSIC, line(text, "negative_constraints: "))

    def test_stamped_silent_insert_gets_only_the_music_negative(self):
        text, _ = render_h3_prompt(*vu012(stamped=True))
        self.assertNotIn(TIMBRE, text)
        self.assertNotIn(SILENT, text)
        self.assertIn(MUSIC, line(text, "negative_constraints: "))

    def test_unstamped_units_get_none_of_it(self):
        for text in (render_h3_prompt(*unit_plan(stamped=False, performance=None))[0],
                     render_h3_prompt(*vu012(stamped=False))[0]):
            self.assertNotIn(TIMBRE, text)
            self.assertNotIn(SILENT, text)
            self.assertNotIn(MUSIC, text)


if __name__ == "__main__":
    unittest.main()
