"""A silent unit whose scripted action is a mouth action must not also be told to keep every mouth closed.

Fleet 1037 E14 VU-001 (2026-11-16): the action beat required "opens her mouth in a large yawn" while the unit-wide
vocal rule said "every visible person keeps the mouth closed for the entire clip".
"""

from __future__ import annotations

import unittest

from tools import h3_provider_prompt_renderer as renderer
from tools.h3_provider_prompt_renderer import render_h3_prompt

try:  # reuse the renderer's own synthetic fixture builder
    from tools.tests.test_h3_shot_scope_v1 import A, B, build
except ImportError:  # not shipped in every portable bundle
    build = None


def vocal(text: str) -> str:
    return next(line for line in text.splitlines() if line.startswith("vocal_rule: "))


@unittest.skipIf(build is None, "H3 fixture builder unavailable")
class SilentMouthActionVocalRuleTest(unittest.TestCase):
    def _silent(self, action: str | None, cast: list[str]):
        unit, plan = build([{"cast": cast}, {"cast": cast}])
        unit["provider_scope_projection"]["visible_living_entity_instance_total"] = len(cast)
        if action:
            unit["h3_provider_english_contract"]["beats"][0]["primary_action"] = action
        return render_h3_prompt(unit, plan)[0]

    def test_yawn_is_not_contradicted_by_a_closed_mouth_rule(self):
        for cast in ([A], [A, B]):
            text = self._silent("Alpha stretches and opens her mouth in a large yawn", cast)
            self.assertIn("large yawn", text)
            self.assertNotIn("mouth closed", text)
            self.assertNotIn("closed mouth", text)
            self.assertIn(renderer.MOUTH_ACTION_EXEMPTION, vocal(text))
            self.assertIn("forms words", vocal(text))

    def test_plain_silent_unit_still_closes_mouths(self):
        self.assertIn("every visible person keeps the mouth closed for the entire clip", vocal(self._silent(None, [A, B])))
        self.assertIn("mouth", vocal(self._silent(None, [A])))
        self.assertNotIn(renderer.MOUTH_ACTION_EXEMPTION, self._silent(None, [A, B]))

    def test_detector_matches_mouth_actions_only(self):
        for text in ("She yawns widely", "he bites the apple", "Her jaw drops", "opens his mouth to breathe",
                     "sips the tea", "They kiss"):
            self.assertTrue(renderer.scripted_mouth_action([{"primary_action": text}]), text)
        for text in ("She walks to the window", "He habitually checks the lock", "a bitter smile", "great hall",
                     "primary action 1"):
            self.assertFalse(renderer.scripted_mouth_action([{"primary_action": text}]), text)

    def test_silent_beat_in_a_dialogue_unit_gets_the_exempting_clause(self):
        self.assertIn("forms no words", renderer.NO_SPEECH_BEAT_MOUTH_ACTION_CLAUSE.format(who="Alpha"))
        self.assertNotIn("mouth closed", renderer.NO_SPEECH_BEAT_MOUTH_ACTION_CLAUSE)


if __name__ == "__main__":
    unittest.main()
