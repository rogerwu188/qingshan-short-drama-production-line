"""A finished action must not be restarted by the next unit.

The check reads structured declarations only.  Text similarity is deliberately
not used: it misreads a legitimate continuation and misses a restatement.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.build_video_unit_anchor_plan import build
from tools.unit_action_continuity_contract import evaluate


def unit(uid, *, event=None, phase=None, continues=None, repeat=None, **extra):
    contract = {}
    if event:
        contract["event_id"] = event
    if phase:
        contract["phase"] = phase
    if continues:
        contract["continues_event_id"] = continues
    if repeat:
        contract["authorized_repeat"] = repeat
    value = {"unit_id": uid, **extra}
    if contract:
        value["action_event_contract"] = contract
    return value


class ActionContinuityTests(unittest.TestCase):
    def test_no_declaration_is_not_applicable(self):
        verdict = evaluate(unit("U1"), unit("U2"))
        self.assertEqual(verdict["status"], "NOT_APPLICABLE")
        self.assertEqual(verdict["failures"], [])

    def test_continue_after_start_passes(self):
        verdict = evaluate(
            unit("U1", event="TELL-PASSWORD", phase="START"),
            unit("U2", event="TELL-PASSWORD", phase="CONTINUE", continues="TELL-PASSWORD"),
        )
        self.assertEqual(verdict["status"], "PASS")

    def test_continue_after_complete_fails(self):
        verdict = evaluate(
            unit("U1", event="TELL-PASSWORD", phase="COMPLETE"),
            unit("U2", event="TELL-PASSWORD", phase="CONTINUE", continues="TELL-PASSWORD"),
        )
        self.assertIn("ACTION_EVENT_CONTINUES_COMPLETED:U2:TELL-PASSWORD", verdict["failures"])

    def test_restarting_a_completed_action_fails(self):
        verdict = evaluate(
            unit("U1", event="STAMP-FOOT", phase="COMPLETE"),
            unit("U2", event="STAMP-FOOT", phase="START"),
        )
        self.assertIn("COMPLETED_ACTION_RESTARTED:U2:STAMP-FOOT", verdict["failures"])

    def test_restarting_inside_the_same_event_fails(self):
        verdict = evaluate(
            unit("U1", event="TELL-PASSWORD", phase="START"),
            unit("U2", event="TELL-PASSWORD", phase="START"),
        )
        self.assertIn("EVENT_STARTED_TWICE:U2:TELL-PASSWORD", verdict["failures"])

    def test_authorized_repeat_passes(self):
        verdict = evaluate(
            unit("U1", event="STAMP-FOOT", phase="COMPLETE"),
            unit("U2", event="STAMP-FOOT", phase="START",
                 repeat={"writer_authorized": True, "source_ref": "E99-S02-03",
                         "reason": "剧本要求同一动作在回忆里再出现一次"}),
        )
        self.assertEqual(verdict["status"], "PASS")
        self.assertTrue(verdict["authorized_repeat"])

    def test_unauthorized_repeat_reason_still_fails(self):
        verdict = evaluate(
            unit("U1", event="STAMP-FOOT", phase="COMPLETE"),
            unit("U2", event="STAMP-FOOT", phase="START",
                 repeat={"writer_authorized": True, "reason": "理由有但无出处"}),
        )
        self.assertIn("COMPLETED_ACTION_RESTARTED:U2:STAMP-FOOT", verdict["failures"])

    def test_a_new_event_can_start_after_the_previous_one_completed(self):
        verdict = evaluate(
            unit("U1", event="TELL-PASSWORD", phase="COMPLETE"),
            unit("U2", event="LEAVE-ROOM", phase="START"),
        )
        self.assertEqual(verdict["status"], "PASS")

    def test_continue_of_an_unrelated_event_fails(self):
        verdict = evaluate(
            unit("U1", event="TELL-PASSWORD", phase="START"),
            unit("U2", event="LEAVE-ROOM", phase="CONTINUE", continues="LEAVE-ROOM"),
        )
        self.assertIn("ACTION_EVENT_CONTINUES_UNRELATED:U2:LEAVE-ROOM after TELL-PASSWORD",
                      verdict["failures"])

    def test_invalid_phase_fails(self):
        verdict = evaluate(unit("U1"), unit("U2", event="X", phase="FINISHED"))
        self.assertIn("ACTION_EVENT_PHASE_INVALID:U2:FINISHED", verdict["failures"])


class AnchorPlanIntegrationTests(unittest.TestCase):
    def test_build_refuses_a_unit_that_restarts_the_previous_action(self):
        grouping = {"episode": "E99", "units": [
            {"unit_id": "U1", "scene_id": "SC1", "editorial_shot_ids": ["S1"],
             "action_event_contract": {"event_id": "STAMP-FOOT", "phase": "COMPLETE"}},
            {"unit_id": "U2", "scene_id": "SC1", "editorial_shot_ids": ["S2"],
             "action_event_contract": {"event_id": "STAMP-FOOT", "phase": "START"}},
        ]}
        editorial = {"shots": [
            {"shot_id": "S1", "prompt_spec": {"dialogue": "line"}},
            {"shot_id": "S2", "prompt_spec": {"dialogue": "line"}},
        ]}
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "S1-keyframe-v1.png").touch()
            Path(tmp, "S2-keyframe-v1.png").touch()
            with self.assertRaisesRegex(ValueError, "COMPLETED_ACTION_RESTARTED:U2:STAMP-FOOT"):
                build(grouping, editorial, Path(tmp))


if __name__ == "__main__":
    unittest.main()
