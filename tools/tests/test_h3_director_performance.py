"""CAMERA_GRAMMAR_V1 dialogue delivery: the writer's performance replaces the brisk canned clause.

Unstamped units keep the canned clause byte-identically (synthetic fixture).
"""

from __future__ import annotations

import hashlib
import unittest

from tools.h3_provider_prompt_renderer import render_h3_prompt
from tools.tests.test_h3_shot_scope_v1 import A, LOCKED, build

CANNED = "Delivery: clear, connected, naturally brisk speech without stretched syllables"
TAIL = ("Natural human speech with real breaths and pauses; expressive intonation "
        "with clear rises and falls in pitch and volume, the key words stressed; never a flat read-aloud tone.")


def unit_plan(*, stamped: bool, performance: dict | None) -> tuple[dict, dict]:
    camera = {**LOCKED, **({"camera_grammar": "CAMERA_GRAMMAR_V1"} if stamped else {})}
    unit, plan = build([{"cast": [A], "speaker": A}], camera_plan=camera)
    unit["provider_scope_projection"]["visible_living_entity_instance_total"] = 1
    plan["beats"][0]["dialogue_delivery"] = {"chinese_characters_per_second": 4.5}
    if performance is not None:
        unit["ordered_prompt_specs"][0]["action"] = {"performance": performance}
    return unit, plan


def beat_line(text: str) -> str:
    return next(line for line in text.splitlines() if line.startswith("[0s-3s]"))


class DirectorPerformanceTest(unittest.TestCase):
    def test_delivery_en_replaces_the_canned_clause(self):
        perf = {"emotion": "厌", "delivery_en": "cold and contemptuous, low and clipped, a beat of silence before the second sentence"}
        text, receipt = render_h3_prompt(*unit_plan(stamped=True, performance=perf))
        line = beat_line(text)
        self.assertIn("Performance: cold and contemptuous, low and clipped, a beat of silence before the "
                      "second sentence. " + TAIL, line)
        self.assertNotIn(CANNED, text)
        self.assertEqual(receipt["status"], "PASS")

    def test_emotion_word_maps_when_delivery_en_missing(self):
        perf = {"emotion": "厌", "delivery": "普通话，清晰自然，情绪只影响语气，音色严格同登记参考。"}
        line = beat_line(render_h3_prompt(*unit_plan(stamped=True, performance=perf))[0])
        self.assertIn("Performance: contemptuous. " + TAIL, line)
        line = beat_line(render_h3_prompt(*unit_plan(stamped=True, performance={"emotion": "冷静中带疑、紧张"}))[0])
        self.assertIn("Performance: cold, suspicious, tense. ", line)

    def test_cjk_delivery_en_falls_back_to_the_emotion_map(self):
        perf = {"emotion": "怒", "delivery_en": "愤怒"}
        self.assertIn("Performance: angry. ", beat_line(render_h3_prompt(*unit_plan(stamped=True, performance=perf))[0]))

    def test_unmapped_or_missing_performance_keeps_the_canned_clause(self):
        for perf in (None, {"emotion": "focused"}, {"emotion": "若有所思"}):
            line = beat_line(render_h3_prompt(*unit_plan(stamped=True, performance=perf))[0])
            self.assertIn(CANNED, line)
            self.assertNotIn("Performance:", line)

    def test_unstamped_units_ignore_performance_and_stay_byte_identical(self):
        baseline, _ = render_h3_prompt(*unit_plan(stamped=False, performance=None))
        perf = {"emotion": "厌", "delivery_en": "cold and contemptuous"}
        text, _ = render_h3_prompt(*unit_plan(stamped=False, performance=perf))
        self.assertEqual(text, baseline)
        self.assertIn(CANNED, text)
        self.assertNotIn("Performance:", text)
        # sha256 of the renderer output for this fixture.  Re-pinned 2026-10-28 (10,000-rune
        # budget fix, E12-VU-003): "Start from X. Force origin: X." no longer repeats X when
        # force_origin equals entry_state; confirmed as the only text change by diffing old vs new.
        self.assertEqual(hashlib.sha256(text.encode()).hexdigest(), PINNED)


PINNED = "a50f6df329cbfcaae1bd79f276879941ff7010a51db3a88029374e892b3f3efe"

if __name__ == "__main__":
    unittest.main()
