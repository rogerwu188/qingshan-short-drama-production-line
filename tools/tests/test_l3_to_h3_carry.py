"""tools/check_l3_to_h3_carry.py (CHANGE_SPEC WP4 acceptance, report only): the English twins of what the
screenplay says reach the H3 prompt of their unit."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools import check_l3_to_h3_carry as carry
from tools.h3_provider_prompt_renderer import render_h3_prompt
from tools.tests.test_bili_v1_carry import authored
from tools.tests.test_h3_director_prompt_v2 import fixture


def contract() -> dict:
    return {"shots": [{"shot_id": "T-S01", "prompt_spec": {
        "action": {"business_en": "sets the war token on the table",
                   "listener_reaction_en": "Beta's fingers tighten on the armrest",
                   "lead_in_reaction_en": "Alpha exhales once"},
        "props": [{"prop_id": "PROP-TOKEN", "description_en": "a palm-sized black iron war token"}]}}]}


class CarryReport(unittest.TestCase):
    def test_bili_v1_render_carries_the_twins(self):
        unit, plan = fixture()
        authored(unit, bili=True)
        unit["ordered_prompt_specs"][0]["action"]["lead_in_reaction_en"] = (
            "Alpha exhales once and sets the war token on the table")
        text, _ = render_h3_prompt(unit, plan)
        report = carry.carry(contract(), {"T-S01": text})
        self.assertEqual(report["status"], "PASS", report["shots"])
        self.assertGreaterEqual(report["carry"], 0.95)

    def test_legacy_render_misses_them(self):
        unit, plan = fixture(style=False)
        authored(unit, bili=False)
        text, _ = render_h3_prompt(unit, plan)
        report = carry.carry(contract(), {"T-S01": text})
        self.assertEqual(report["status"], "BELOW_TARGET")
        self.assertIn("armrest", report["shots"][0]["missing"]["listener_reaction_en"])

    def test_cli_reads_the_grouped_manifest_and_prompt_dir(self):
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            (tmp / "c.json").write_text(json.dumps(contract()))
            (tmp / "g.json").write_text(json.dumps({"units": [{"unit_id": "U1",
                                                               "ordered_prompt_specs": [{"shot_id": "T-S01"}]}]}))
            (tmp / "p").mkdir()
            (tmp / "p" / "U1.txt").write_text("nothing relevant")
            argv = ["--contract", str(tmp / "c.json"), "--grouped-manifest", str(tmp / "g.json"),
                    "--prompt-dir", str(tmp / "p"), "--out", str(tmp / "r.json")]
            self.assertEqual(carry.main(argv), 0)
            self.assertEqual(json.loads((tmp / "r.json").read_text())["status"], "BELOW_TARGET")
            self.assertEqual(carry.main(argv + ["--require"]), 1)


if __name__ == "__main__":
    unittest.main()
