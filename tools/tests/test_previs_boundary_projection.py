"""Previs boundaries project the EXISTING camera/transition/action-continuity
contracts onto real clip-order adjacency.

CC_H3 audit 2026-10-26 §四-缺口A: a previs timeline with only shot id, start,
duration and a static image could not show whether two shots cut together with
any rhythm; two different camera/action designs produced byte-identical "PASS"
previs output.  This module must not re-implement those contracts — it reads
grouped_transition_contract / grouped_camera_contract / unit_action_continuity_contract
exactly as the rest of the engine already validates with.

Synthetic shots only — no episode text, task ids, media or absolute paths from
any production line.
"""

from __future__ import annotations

import unittest

from tools import episode_previs as previs


def _unit(uid, shots, family, direction, start_framing, end_framing, action=None,
         transition=None, scene_id="T-SC"):
    row = {
        "unit_id": uid, "scene_id": scene_id, "editorial_shot_ids": shots,
        "camera_plan": {
            "shot_scale": "MEDIUM", "camera_height": "EYE_LEVEL", "camera_side": "AXIS_A",
            "motion_family": family, "motion_direction": direction,
            "lens_intent": "synthetic", "axis_relation": "synthetic",
            "start_framing": start_framing, "end_framing": end_framing,
            "motivation": "synthetic motivation long enough",
        },
    }
    if action is not None:
        row["action_event_contract"] = action
    if transition is not None:
        row["transition_contract"] = transition
    return row


def _timeline(shot_ids):
    return [{"shot_id": sid, "start": float(i * 3), "duration": 3.0, "dialogue": []}
            for i, sid in enumerate(shot_ids)]


class BoundaryReflectsRealAdjacency(unittest.TestCase):
    def test_locked_baseline_vs_repeated_pan_and_restart_differ(self):
        """The exact audit reproduction: two units, LOCKED cameras and no action
        declaration, versus the same two units turned into a same-direction pan
        with a COMPLETE action restarted as START.  Previs boundaries must differ."""
        shots = ["T-S01", "T-S02"]
        timeline = _timeline(shots)

        baseline = {"units": [
            _unit("T-VU01", ["T-S01"], "LOCKED", "NONE", "A holds", "A holds"),
            _unit("T-VU02", ["T-S02"], "LOCKED", "NONE", "B holds", "B holds"),
        ]}
        changed = {"units": [
            _unit("T-VU01", ["T-S01"], "PAN", "LEFT_TO_RIGHT", "A stands", "A stands facing door",
                 action={"event_id": "STAND_UP", "phase": "COMPLETE"}),
            _unit("T-VU02", ["T-S02"], "PAN", "LEFT_TO_RIGHT", "A stands again", "A stands again facing door",
                 action={"event_id": "STAND_UP", "phase": "START"}),
        ]}

        before = previs.build_boundaries(baseline, timeline, {})
        after = previs.build_boundaries(changed, timeline, {})

        self.assertNotEqual(before, after, "camera and action design changed; boundaries must not be identical")
        self.assertEqual(before[0]["camera"]["from_motion"], "LOCKED:NONE")
        self.assertEqual(after[0]["camera"]["from_motion"], "PAN:LEFT_TO_RIGHT")
        self.assertEqual(before[0]["action_continuity"]["status"], "NOT_APPLICABLE")
        self.assertEqual(after[0]["action_continuity"]["status"], "FAIL")
        self.assertIn("COMPLETED_ACTION_RESTARTED:T-VU02:STAND_UP",
                      after[0]["action_continuity"]["failures"])

    def test_no_declared_transition_is_reported_not_invented(self):
        units = {"units": [
            _unit("T-VU01", ["T-S01"], "LOCKED", "NONE", "A holds", "A holds"),
            _unit("T-VU02", ["T-S02"], "LOCKED", "NONE", "B holds", "B holds"),
        ]}
        boundaries = previs.build_boundaries(units, _timeline(["T-S01", "T-S02"]), {})
        self.assertEqual(boundaries[0]["transition"]["status"], "NOT_DECLARED")

    def test_declared_transition_surfaces_its_structured_facts(self):
        transition = {
            "from_unit_id": "T-VU01", "to_unit_id": "T-VU02",
            "boundary_id": "BND-T-VU01-T-VU02",
            "cut_reason": "REACTION_CUT", "space_relation": "SAME_SUBSPACE",
            "authorship": "DIRECTOR_AUTHORED", "transition_device": "GAZE_MATCH",
            "outgoing_handle_seconds": 0.8, "incoming_handle_seconds": 0.8,
            "plot_motivation": "A's reaction reveals the new information to the audience",
            "visual_bridge": "A's raised eyes carry into B's matching look", "action_bridge": "A looks up then B looks back",
            "sound_bridge": "room tone continues unbroken", "axis_strategy": "stays on axis A side",
            "continuity_intent": "no reset, no replay of the prior beat",
            "source_terminal_state": {"scene_id": "T-SC", "space": {"global": "G", "location": "L", "subspace": "S"},
                                      "camera_framing": "A holds", "camera_side": "AXIS_A", "blocking": "A seated at table"},
            "target_initial_state": {"scene_id": "T-SC", "space": {"global": "G", "location": "L", "subspace": "S"},
                                     "camera_framing": "B holds", "camera_side": "AXIS_A", "blocking": "B seated at table"},
            "anchor_semantic_requirements": {"target_visible_characters": [], "target_visible_props": [],
                                             "target_space_anchors": ["L"], "empty_establishing_frame_allowed": True},
        }
        units = {"units": [
            _unit("T-VU01", ["T-S01"], "LOCKED", "NONE", "A holds", "A holds"),
            _unit("T-VU02", ["T-S02"], "LOCKED", "NONE", "B holds", "B holds", transition=transition),
        ]}
        boundaries = previs.build_boundaries(units, _timeline(["T-S01", "T-S02"]), {})
        row = boundaries[0]["transition"]
        self.assertEqual(row["status"], "DECLARED")
        self.assertEqual(row["cut_reason"], "REACTION_CUT")
        self.assertIn("reaction reveals", row["plot_motivation"])

    def test_single_unit_has_no_boundaries(self):
        self.assertEqual(previs.build_boundaries({"units": [_unit("T-VU01", ["T-S01"], "LOCKED", "NONE", "x", "x")]},
                                                  _timeline(["T-S01"]), {}), [])
        self.assertEqual(previs.build_boundaries(None, _timeline(["T-S01"]), {}), [])

    def test_dialogue_crossing_the_cut_is_flagged(self):
        units = {"units": [
            _unit("T-VU01", ["T-S01"], "LOCKED", "NONE", "A speaks", "A speaks"),
            _unit("T-VU02", ["T-S02"], "LOCKED", "NONE", "B listens", "B listens"),
        ]}
        timeline = _timeline(["T-S01", "T-S02"])
        dialogue_by_shot = {"T-S01": [{"speaker_id": "CHAR-A", "seconds": 2.0}]}
        boundaries = previs.build_boundaries(units, timeline, dialogue_by_shot)
        self.assertTrue(boundaries[0]["dialogue_crosses_cut"])


if __name__ == "__main__":
    unittest.main()
