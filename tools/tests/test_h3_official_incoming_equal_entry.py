"""OFFICIAL_REF_V1: an incoming transition that equals the first beat's entry is covered by the rewritten
"Continuing straight from the previous shot ..." sentence (device 1205 E17-VU-002
PROVIDER_SEMANTIC_FACT_UNCOVERED:TRANSITION.INCOMING). Zero credits."""
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

ENTRY = "John SimsJohn sets his pen down"  # the duplicated label prefix is what 1205 really sent


class IncomingEqualsEntryTest(unittest.TestCase):
    setUpClass = classmethod(base.OfficialFormatTest.setUpClass.__func__)
    setUp = base.OfficialFormatTest.setUp
    unit = base.OfficialFormatTest.unit

    def _unit_with_equal_incoming(self):
        unit, plan = self.unit("S01-03")
        unit, plan = copy.deepcopy(unit), copy.deepcopy(plan)
        contract = unit["h3_provider_english_contract"]
        contract["beats"][0]["entry_state"] = ENTRY
        contract["beats"][0].pop("force_origin", None)  # V2 then defaults FORCE_ORIGIN to the raw entry as well
        contract["transition"] = {"incoming": ENTRY + "."}
        plan["transition"] = {"incoming": "source incoming"}
        return unit, plan

    def test_equal_incoming_is_covered_in_official_format(self):
        unit, plan = self._unit_with_equal_incoming()
        text, receipt = render_h3_prompt(unit, plan)
        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(receipt["h3_prompt_format"], official.FORMAT)
        self.assertEqual(receipt["provider_semantic_coverage_receipt"]["status"], "PASS")
        self.assertIn("Continuing straight from the previous shot with no reset, john SimsJohn sets his pen down.",
                      text)
        self.assertNotIn("Open directly from the inherited state", text)  # equal entry: no extra sentence


if __name__ == "__main__":
    unittest.main()
