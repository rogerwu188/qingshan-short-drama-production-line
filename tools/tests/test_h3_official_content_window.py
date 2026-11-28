"""OFFICIAL_REF_V1: the V2 lines stated before the first beat (content window, a non-equal inherited opening, the
"Throughout:" lock) reach the official description (device 1205 E17-VU-006
PROVIDER_SEMANTIC_FACT_UNCOVERED:PACING.CONTENT_WINDOW). Zero credits."""
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


class OfficialContentWindowTest(unittest.TestCase):
    setUpClass = classmethod(base.OfficialFormatTest.setUpClass.__func__)
    setUp = base.OfficialFormatTest.setUp
    unit = base.OfficialFormatTest.unit

    def _unit_with_content_window(self):
        unit, plan = self.unit("S01-03")
        unit, plan = copy.deepcopy(unit), copy.deepcopy(plan)
        duration = float(plan["duration_seconds"])
        plan["duration_authority"] = {**(plan.get("duration_authority") or {}),
                                      "authorized_content_seconds": round(duration - 1.5, 2)}
        return unit, plan, duration

    def test_content_window_is_covered_in_official_format(self):
        unit, plan, duration = self._unit_with_content_window()
        text, receipt = render_h3_prompt(unit, plan)
        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(receipt["h3_prompt_format"], official.FORMAT)
        self.assertEqual(receipt["provider_semantic_coverage_receipt"]["status"], "PASS")
        self.assertIn(f"The story takes {duration - 1.5:g} s of the {duration:g} s clip", text)

    def test_non_equal_incoming_is_stated(self):
        unit, plan, _ = self._unit_with_content_window()
        unit["h3_provider_english_contract"]["transition"] = {"incoming": "John is already halfway out of his chair"}
        plan["transition"] = {"incoming": "source incoming"}
        text, receipt = render_h3_prompt(unit, plan)
        self.assertEqual(receipt["provider_semantic_coverage_receipt"]["status"], "PASS")
        self.assertIn("Open directly from the inherited state: John is already halfway out of his chair.", text)


if __name__ == "__main__":
    unittest.main()
