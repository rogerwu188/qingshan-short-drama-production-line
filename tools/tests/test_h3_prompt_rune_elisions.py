"""Regression: H3 renderer elides only byte-identical restatements.

These elisions keep E12-class multi-shot units inside the 10,000-rune provider
budget without shortening any unique text.  A clause that adds a new fact must
always survive verbatim, and every elided fact must still be reachable as
coverage evidence.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.h3_provider_prompt_renderer import (
    _beat,
    _collapse_shared_unit_policy,
    _condense_feedback,
    _condense_sound_quotes,
)

ACTION = (
    "Qinming raises his hand and catches a few glowing petals, his fingers "
    "tinted faintly red by their light"
)
EXIT = "Qinming cradles a few glowing petals in his hand"


class FeedbackElisionTest(unittest.TestCase):
    def test_verbatim_restatement_collapses(self):
        feedback = (
            f"Qinming initiates “{ACTION}” -> the snow road receives -> "
            f"the result settles at “{EXIT}”; contact first; then the jaw"
        )
        out = _condense_feedback(feedback, {"primary_action": ACTION, "exit_state": EXIT})
        self.assertNotIn(ACTION, out)
        self.assertLess(len(out), len(feedback))

    def test_feedback_with_new_fact_survives_verbatim(self):
        feedback = "Qinming's hand trembles once before he lets the petals fall"
        out = _condense_feedback(feedback, {"primary_action": ACTION, "exit_state": EXIT})
        self.assertEqual(out, feedback)

    def test_short_feedback_is_untouched(self):
        out = _condense_feedback("he nods", {"primary_action": ACTION, "exit_state": EXIT})
        self.assertEqual(out, "he nods")


class SoundQuoteElisionTest(unittest.TestCase):
    def test_exact_action_quote_collapses(self):
        rows = [f'reinforce one causal contact sound for "{ACTION}" once']
        out = _condense_sound_quotes(rows, [{"primary_action": ACTION}])
        self.assertNotIn(ACTION, out[0])
        self.assertIn("the action stated for that shot", out[0])

    def test_non_action_text_survives(self):
        rows = ["distant wind over the snow road, cloth stirring"]
        out = _condense_sound_quotes(rows, [{"primary_action": ACTION}])
        self.assertEqual(out, rows)

    def test_sentence_initial_action_quote_still_collapses(self):
        # A beat's own primary_action is capitalised sentence-initial ("The
        # petals ..."), but a sound row always quotes it mid-sentence, so the
        # row embeds the lower-cased opening word.  A case-sensitive `action
        # in text` check misses this row while matching sibling rows whose
        # action happens to open with a proper noun (E12-VU-003: the row that
        # silently kept its full quote carried ~200 duplicate runes).
        capitalised_action = (
            "The petals in the distant mountain forest are densely packed like "
            "burning crimson clouds and the snow between the trees is washed red"
        )
        rows = [f'reinforce one causal contact sound for "{capitalised_action[0].lower()}{capitalised_action[1:]}" once']
        out = _condense_sound_quotes(rows, [{"primary_action": capitalised_action}])
        self.assertNotIn(capitalised_action[0].lower() + capitalised_action[1:], out[0])
        self.assertIn("the action stated for that shot", out[0])

    def test_action_differing_mid_sentence_is_not_falsely_collapsed(self):
        # Guard against the lower-cased fallback over-matching: a row whose
        # quoted text merely starts with the same lower-cased letter but is
        # otherwise a different sentence must survive verbatim.
        action = "The flock of birds rises into the night sky chasing the petals"
        rows = ['reinforce one causal contact sound for "the weather turns colder near the ridge line tonight" once']
        out = _condense_sound_quotes(rows, [{"primary_action": action}])
        self.assertEqual(out, rows)


class ForceOriginElisionTest(unittest.TestCase):
    def _translated(self, entry_state, force_origin):
        return {
            "entry_state": entry_state,
            "force_origin": force_origin,
            "primary_action": ACTION,
            "exit_state": EXIT,
        }

    def _source(self, index=1):
        return {"source_index": index, "start_seconds": 0, "end_seconds": 2}

    def test_force_origin_equal_to_entry_state_is_not_repeated(self):
        # A beat that simply continues the inherited pose has force_origin ==
        # entry_state; "Start from X. Force origin: X." then restates the same
        # sentence twice for no new fact (E12-VU-003, over the 10,000-rune
        # provider limit with three such beats in one unit).
        state = "The flock of birds rises into the night sky; the two stand on the snow road"
        line, evidence = _beat(self._source(), self._translated(state, state), dialogue_binding=None)
        self.assertEqual(line.count(state), 1)
        self.assertNotIn("Force origin:", line)
        # the fact is still recorded for the coverage gate even though the
        # clause itself is not rendered a second time
        self.assertEqual(evidence["BEAT.1.FORCE_ORIGIN"], state)

    def test_distinct_force_origin_still_renders_in_full(self):
        entry = "Qinming stands at the edge of the snow road"
        origin = "A sudden gust tears through the forest and scatters the petals"
        line, evidence = _beat(self._source(), self._translated(entry, origin), dialogue_binding=None)
        self.assertIn(f"Start from {entry}.", line)
        self.assertIn(f"Force origin: {origin}.", line)
        self.assertEqual(evidence["BEAT.1.FORCE_ORIGIN"], origin)


class SharedTailElisionTest(unittest.TestCase):
    def test_identical_unit_wide_tail_emitted_once(self):
        tail = (
            "; unit music policy: three purely instrumental score passages, "
            "everything else native on-site sound"
        )
        rows = [f"first shot contact sound{tail}", f"second shot contact sound{tail}",
                f"third shot contact sound{tail}"]
        out = _collapse_shared_unit_policy(rows)
        self.assertEqual(out[0], rows[0])
        self.assertNotIn("three purely instrumental score passages", out[1])
        self.assertNotIn("three purely instrumental score passages", out[2])
        self.assertEqual(sum(1 for row in out if "three purely instrumental" in row), 1)

    def test_short_shared_text_is_untouched(self):
        rows = ["a; b", "c; b"]
        self.assertEqual(_collapse_shared_unit_policy(rows), rows)

    def test_single_row_untouched(self):
        self.assertEqual(_collapse_shared_unit_policy(["only row"]), ["only row"])


if __name__ == "__main__":
    unittest.main()
