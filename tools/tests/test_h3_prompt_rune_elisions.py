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
