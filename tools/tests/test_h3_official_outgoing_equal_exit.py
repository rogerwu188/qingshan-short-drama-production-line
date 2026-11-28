"""OFFICIAL_REF_V1: an outgoing transition that equals the last beat's exit is covered by the rewritten
"By the end, ..." sentence (device 1205 E17-VU-001 PROVIDER_SEMANTIC_FACT_UNCOVERED:TRANSITION.OUTGOING).
Zero credits."""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import test_h3_official_ref_prompt as base  # noqa: E402
from tools import h3_official_ref_prompt as official  # noqa: E402
from tools.h3_provider_prompt_renderer import render_h3_prompt  # noqa: E402

EXIT = "John SimsJohn sets his pen down"  # the duplicated label prefix is what 1205 really sent


class OutgoingEqualsExitTest(unittest.TestCase):
    setUpClass = classmethod(base.OfficialFormatTest.setUpClass.__func__)
    setUp = base.OfficialFormatTest.setUp
    unit = base.OfficialFormatTest.unit

    def _unit_with_equal_outgoing(self):
        unit, plan = self.unit("S01-03")
        unit, plan = copy.deepcopy(unit), copy.deepcopy(plan)
        contract = unit["h3_provider_english_contract"]
        contract["beats"][-1]["exit_state"] = EXIT
        contract["transition"] = {"outgoing": EXIT + "."}
        plan["transition"] = {"outgoing": "source outgoing"}
        return unit, plan

    def test_equal_outgoing_is_covered_in_official_format(self):
        unit, plan = self._unit_with_equal_outgoing()
        text, receipt = render_h3_prompt(unit, plan)
        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(receipt["h3_prompt_format"], official.FORMAT)
        self.assertEqual(receipt["provider_semantic_coverage_receipt"]["status"], "PASS")
        self.assertIn("By the end, john SimsJohn sets his pen down.", text)
        self.assertNotIn("Hand off to the next shot on", text)  # equal exit: no extra handoff sentence

    def test_flat_matches_the_v2_sameness_test(self):
        self.assertEqual(official._flat("A b.  c;"), official._flat("a B c"))
        self.assertNotEqual(official._flat("a b"), official._flat("a c"))


if __name__ == "__main__":
    unittest.main()
