#!/usr/bin/env python3
"""Korean / Japanese dialogue shot length: static_design_gate R8 and writer self-check seq29 5a agree.

Device 0080 (KO-01 이런 연애, E01 S1, CURRENT_PORTABLE, 2026-11-19): R8 demanded >= 4.0 s for E01-S01-02 while 5a
capped the same line at 2.5 s -- no target_seconds satisfied both.  R8 timed a Korean line on the zh path whenever
the contract was not CAMERA_GRAMMAR_V1 (Hangul uncounted, a romanised ``Speaker：`` label counted letter by letter)
and only stripped a fullwidth label inside 8 characters; 5a stripped labels inside 24 characters, timed Hangul at
5.0 syllables/s and ignored the shot's ``speech_units_per_second``.  Both now call
nalu_prompt_rules.dialogue_min_seconds for ja / ko.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines/nalu/runtime/tools"
for _path in (str(TOOLS), str(ROOT / "tools"), str(ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader
    spec.loader.exec_module(module)
    return module


npr = load("nalu_prompt_rules", TOOLS / "nalu_prompt_rules.py")
gate = load("static_design_gate", TOOLS / "static_design_gate.py")
seq29 = load("nalu_writer_selfcheck_seq29", TOOLS / "nalu_writer_selfcheck_seq29.py")
sud = load("speaking_unit_duration", ROOT / "tools/speaking_unit_duration.py")

TARGETS = [x / 2 for x in range(1, 25)]  # 0.5 .. 12.0 s


def contract(dialogue, seconds, language, *, stamped=False, delivery=None):
    shot = {"shot_id": "E01-S01-02", "scene_id": "E01-S01", "target_seconds": seconds,
            "prompt_spec": {"camera_plan": {"motion_family": "LOCKED", "camera_side": "FRONT", "shot_scale": "MEDIUM"},
                            "dialogue": dialogue, "action": {"primary_action": "걷는다"}}}
    if delivery:
        shot["dialogue_delivery"] = dict(delivery)
    out = {"episode": "E01", "dialogue_language": language, "shots": [shot]}
    if stamped:
        out["camera_grammar_policy"] = "CAMERA_GRAMMAR_V1"
    return out


def r8_flags(c):
    return [f for f in gate.evaluate(c, dict(gate.POLICY), current_policy=True)["failures"] if ":R8_" in f]


def r5a_flags(c):
    return [f for f in seq29.evaluate(c)["failures"] if f.startswith("R5A_")]


def passing_targets(dialogue, language, **kw):
    return [t for t in TARGETS
            if not r8_flags(contract(dialogue, t, language, **kw)) and not r5a_flags(contract(dialogue, t, language, **kw))]


class KoreanJapaneseDialogueDurationTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict(os.environ, {"NALU_POLICY_PROFILE": "CURRENT_PORTABLE"})
        patcher.start()
        self.addCleanup(patcher.stop)

    # ----------------------------------------------------------------- the device conflict
    def test_device_0080_korean_line_has_a_length_both_rules_accept(self):
        # device shape: a 14-letter romanised label + fullwidth separator beyond R8's old 8-character window, unstamped
        # (S1) contract -> before the fix R8 >= 14 / 4.0 + 0.5 = 4.0 s, 5a <= 1.5 + 1.0 = 2.5 s
        for dialogue in ("CHAR-WON-UGYEONG：가자, 지금.", "Won U-gyeong：가자, 지금.", "CHAR-WON-UGYEONG: 가자, 지금.",
                         "원우경：가자, 지금."):
            for stamped in (False, True):
                with self.subTest(dialogue=dialogue, stamped=stamped):
                    ok = passing_targets(dialogue, "ko", stamped=stamped)
                    self.assertTrue(ok, f"no target_seconds satisfies R8 and seq29 5a for {dialogue!r}")
                    # 4 syllables / 5.0 + 0.5 = 1.3 -> 1.5 s: both rules share the same floor
                    self.assertEqual(ok[0], 1.5)
                    self.assertEqual(npr.dialogue_min_seconds(dialogue, None, "ko"), 1.5)

    def test_korean_r8_floor_equals_seq29_derived(self):
        line = "Sa Je-yeon: 이제야 왔구나. 기다렸어."
        derived = seq29.derived_dialogue_seconds(line, 4.0, None, "ko")
        self.assertEqual(derived, 2.5)  # 10 syllables / 5.0 + 0.5
        self.assertFalse(r8_flags(contract(line, derived, "ko")))
        self.assertTrue(r8_flags(contract(line, derived - 0.5, "ko")))

    def test_japanese_line_has_a_length_both_rules_accept(self):
        for dialogue in ("Sakura Aoi：もう行くよ。", "さくら：もう行くよ。", "佐藤：行け。"):
            for stamped in (False, True):
                with self.subTest(dialogue=dialogue, stamped=stamped):
                    ok = passing_targets(dialogue, "ja", stamped=stamped)
                    self.assertTrue(ok, f"no target_seconds satisfies R8 and seq29 5a for {dialogue!r}")
                    self.assertEqual(ok[0], npr.dialogue_min_seconds(dialogue, None, "ja"))

    # ----------------------------------------------------------------- one rate source
    def test_authored_speech_units_per_second_is_read_by_every_rule(self):
        line = "사제연: 이제야 왔구나. 기다렸어."   # 10 syllables
        slow = {"speech_units_per_second": 4.0, "chinese_characters_per_second": 9.0}
        need = npr.dialogue_min_seconds(line, slow, "ko")
        self.assertEqual(need, 3.0)  # 10 / 4.0 + 0.5 = 3.0
        self.assertEqual(seq29.derived_dialogue_seconds(line, 9.0, slow, "ko"), need)
        self.assertEqual(passing_targets(line, "ko", delivery=slow)[0], need)
        self.assertEqual(passing_targets(line, "ko", stamped=True, delivery=slow)[0], need)
        self.assertAlmostEqual(sud.estimated_line_seconds(line, "ko", slow), round(10 / 4.0 + 2 * 0.16, 3))
        # zh / en ignore speech_units_per_second (unchanged)
        self.assertEqual(sud.estimated_line_seconds("甲：你来了。", "zh", {"speech_units_per_second": 1.0}),
                         sud.estimated_line_seconds("甲：你来了。", "zh", {}))

    # ----------------------------------------------------------------- R8 floor <= speaking-unit maximum
    def test_r8_floor_fits_the_speaking_unit_for_every_line_the_writer_may_write(self):
        # NALU_CRAFT_STANDARD S-08: ko <= 18 syllables, ja <= 22 characters
        for language, unit, longest in (("ko", "가", 18), ("ja", "あ", 22)):
            for n in range(1, longest + 1):
                line = "A：" + unit * n
                with self.subTest(language=language, units=n):
                    need = npr.dialogue_min_seconds(line, None, language)
                    self.assertLessEqual(need, sud.MAX_SECONDS)
                    unit_row = sud.speaking_duration(4, line, language)
                    self.assertNotIn("WRITER_SPLIT", unit_row["action"])
                    duration = unit_row["duration_seconds"]
                    self.assertGreaterEqual(duration, need)               # R8 accepts the compiled unit length
                    self.assertLessEqual(duration, max(need + seq29.TEMPLATE_TOLERANCE_S, sud.MIN_SECONDS))
                    self.assertTrue(passing_targets(line, language, stamped=True))
            # longer than the speaking unit: the writer splits it; both rules still agree on the floor
            long_line = "A：" + unit * (longest + 6)
            with self.subTest(language=language, units=longest + 6):
                self.assertGreater(npr.dialogue_min_seconds(long_line, None, language), sud.MAX_SECONDS)
                self.assertTrue(sud.speaking_duration(4, long_line, language)["action"].startswith("WRITER_SPLIT_REQUIRED"))
                self.assertEqual(passing_targets(long_line, language)[0],
                                 npr.dialogue_min_seconds(long_line, None, language))

    # ----------------------------------------------------------------- zh / en untouched
    def test_zh_and_en_lines_keep_their_own_paths(self):
        self.assertIsNone(npr.dialogue_min_seconds("甲：你终于来了。", None, "zh"))
        self.assertIsNone(npr.dialogue_min_seconds("Holmes: You have come at last.", None, "en"))
        self.assertIsNone(npr.dialogue_min_seconds("Holmes: You have come at last.", None, None))
        zh = contract("林动：你终于来了，我等了三天。", 2.0, "zh")
        self.assertEqual(r8_flags(zh), ["E01-S01-02:R8_DIALOGUE_SHOT_SHORTER_THAN_3S"])
        self.assertEqual(seq29.derived_dialogue_seconds("林动：你终于来了，我等了三天。", None), 3.0)


if __name__ == "__main__":
    unittest.main()
