"""A unit is only asked about the outcome its own beat ends on.

CC_H3 audit follow-up (2026-10-27): the seq=19 plot facts were attached to a
unit whenever a manifest beat row merely INTERSECTED the unit's shots.  A beat
row spans every shot of a scene, so one action beat covering S04-01..04 put its
outcome ("the arrow hits, the deer drops") on both VU-009 and VU-010.  VU-009's
own beat ends at the release — the outcome is in the next unit — so the
reviewer correctly answered FAIL and the unit was rejected for a cut decision
nobody disputed.

The expectation now records whether the declared evidence shot is inside THIS
unit, and the runner marks the question NOT_APPLICABLE when it is not, while
still counting any other plot defect the reviewer raised.

Synthetic contract/manifest only — no episode text, ids or media.
"""

from __future__ import annotations

import unittest
from unittest import mock

from lines.nalu.runtime.tools import nalu_qa_common as common


def _expectations_for(manifest_rows, unit_shots):
    exp = object.__new__(common.Expectations)
    exp.episode = "T01"
    exp.contract = {"shots": []}
    with mock.patch.object(common, "read_json", return_value={"structure": manifest_rows}):
        return exp.seq19_expectations(unit_shots)


class OutcomeEvidenceScope(unittest.TestCase):
    def test_evidence_inside_this_unit_is_actionable(self):
        rows = [{"type": "action", "shot_ids": ["T-S01-01", "T-S01-02"],
                 "outcome": {"kind": "winner", "evidence_shot_id": "T-S01-02"}}]
        result = _expectations_for(rows, ["T-S01-01", "T-S01-02"])
        self.assertEqual(result["beat_type"], "action")
        self.assertTrue(result["action_outcome_evidence_in_unit"])

    def test_evidence_in_a_later_unit_is_marked_not_visible_here(self):
        """The exact audit shape: one beat row covers both units, the evidence
        shot sits in the second one."""
        rows = [{"type": "action", "shot_ids": ["T-S04-01", "T-S04-02", "T-S04-03"],
                 "outcome": {"kind": "winner", "evidence_shot_id": "T-S04-03"}}]
        first = _expectations_for(rows, ["T-S04-01", "T-S04-02"])
        second = _expectations_for(rows, ["T-S04-03"])
        self.assertIsNotNone(first["action_outcome"])
        self.assertFalse(first["action_outcome_evidence_in_unit"])
        self.assertTrue(second["action_outcome_evidence_in_unit"])

    def test_an_outcome_without_a_declared_evidence_shot_stays_actionable(self):
        rows = [{"type": "action", "shot_ids": ["T-S01-01"],
                 "outcome": {"kind": "injury"}}]
        result = _expectations_for(rows, ["T-S01-01"])
        self.assertTrue(result["action_outcome_evidence_in_unit"])

    def test_a_non_action_beat_is_unaffected(self):
        rows = [{"type": "reveal", "shot_ids": ["T-S01-01"], "outcome": None}]
        result = _expectations_for(rows, ["T-S01-01"])
        self.assertIsNone(result["action_outcome"])
        self.assertIsNone(result["action_outcome_evidence_in_unit"])


if __name__ == "__main__":
    unittest.main()
