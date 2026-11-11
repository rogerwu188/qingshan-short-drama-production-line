"""Q1 must not ask about a hard-continuation unit's keyframe (E04 S5, 2026-11-11).

A unit whose opening anchor is PREVIOUS_UNIT_REAL_FINAL_FRAME starts from the previous unit's real
tail and has no S5 keyframe task.  Its first reference key names the previous unit
("E04-VU-008:..."), which used to be taken as the first shot id: the Q1 request then carried a
missing E04-VU-008-keyframe-v1.png with empty expectations and the episode blocked.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines" / "nalu" / "runtime" / "tools"
for _p in (TOOLS, ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import nalu_qa_common as qc  # noqa: E402


def _expectations(tmp: Path, units: list[dict]) -> qc.Expectations:
    anchor_plan = tmp / "anchor.json"
    anchor_plan.write_text(json.dumps({"units": units}), encoding="utf-8")
    keyframes = tmp / "keyframes"
    keyframes.mkdir()
    exp = qc.Expectations.__new__(qc.Expectations)
    exp.episode = "E04"
    exp.contract = {}
    exp.p = SimpleNamespace(anchor_plan=anchor_plan,
                            keyframe=lambda shot_id: keyframes / f"{shot_id}-keyframe-v1.png")
    exp.units = {u["unit_id"]: u for u in units}
    exp.shots = {"E04-S02-05": {}, "E04-S02-06": {}}
    return exp


class HardContinuationQ1Test(unittest.TestCase):
    UNIT = {"unit_id": "E04-VU-009",
            "reference_image_task_keys": ["E04-VU-008:FINAL_FRAME"],
            "editorial_shot_ids": ["E04-S02-06"],
            "opening_anchor_contract": {"source": "PREVIOUS_UNIT_REAL_FINAL_FRAME",
                                        "previous_unit_id": "E04-VU-008"}}

    def test_first_shot_ignores_previous_unit_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            exp = _expectations(Path(tmp), [self.UNIT])
            self.assertEqual(exp._unit_first_shot_id(self.UNIT), "E04-S02-06")
            own = {"reference_image_task_keys": ["E04-S02-05:KEYFRAME"], "editorial_shot_ids": ["E04-S02-05"]}
            self.assertEqual(exp._unit_first_shot_id(own), "E04-S02-05")

    def test_hard_continuation_unit_is_not_a_q1_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            exp = _expectations(Path(tmp), [self.UNIT])
            self.assertEqual(exp.keyframe_items(), [])
            self.assertEqual([r["unit_id"] for r in exp.keyframe_items_skipped_continuity_derived],
                             ["E04-VU-009"])

    def test_both_tail_sources_are_deferred(self):
        self.assertEqual(qc.TAIL_SOURCED_OPENINGS,
                         {"CONTINUITY_DERIVED_KEYFRAME", "PREVIOUS_UNIT_REAL_FINAL_FRAME"})


if __name__ == "__main__":
    unittest.main()
